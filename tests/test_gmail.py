"""Testes do Gmail (sem rede) e das regras de envio."""
import base64
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["MEU_VENDEDOR_DATA"] = tempfile.mkdtemp(prefix="mv-test-gmail-")
os.environ.pop("GOOGLE_PLACES_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from app import config, db, gmail, limits  # noqa: E402
from app.main import app  # noqa: E402


def _t(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


class LimitsTests(unittest.TestCase):
    S = {"days": [True] * 5 + [False] * 2, "hour_start": "09:00", "hour_end": "18:00", "daily_limit": 2, "interval_min_s": 60}

    def test_rules(self):
        quarta = _t(2026, 11, 4, 10, 0)
        self.assertIsNone(limits.check(self.S, [], quarta))
        self.assertIn("dia", limits.check(self.S, [], _t(2026, 11, 7, 10, 0)))  # sábado
        self.assertIn("horário", limits.check(self.S, [], _t(2026, 11, 4, 20, 0)))
        dois = [_t(2026, 11, 4, 9, 10).isoformat(), _t(2026, 11, 4, 9, 30).isoformat()]
        self.assertIn("Limite diário", limits.check(self.S, dois, quarta))
        self.assertIn("Aguarde", limits.check(dict(self.S, interval_min_s=120), [_t(2026, 11, 4, 9, 59).isoformat()], quarta))
        self.assertIsNone(limits.check(self.S, [_t(2026, 11, 4, 9, 59).isoformat()], quarta))  # 60 s já passaram
        ontem = [_t(2026, 11, 3, 9, 30).isoformat()] * 5
        self.assertIsNone(limits.check(self.S, ontem, quarta))  # o limite é por dia


class GmailTests(unittest.TestCase):
    def setUp(self):
        if config.DB_PATH.exists():
            config.DB_PATH.unlink()
        self.c = TestClient(app, base_url="http://127.0.0.1:8765")

    def _connect(self):
        db.set_setting("gmail_client", {"client_id": "id", "client_secret": "sec"})
        db.set_setting("gmail_token", {"refresh_token": "r", "access_token": "a",
                                       "expires_at": time.time() + 3000, "email": "eu@gmail.com"})

    def _approved_email_draft(self, email="dono@loja.com"):
        db.add_leads([{"place_id": "g1", "name": "Loja", "email": email}])
        lid = db.list_leads()[0]["id"]
        did = self.c.post("/api/drafts", json={"lead_id": lid, "channel": "email", "subject": "Ideia", "body": "Olá"}).json()["id"]
        self.c.patch(f"/api/drafts/{did}", json={"status": "approved"})
        return did

    def _open_hours(self):
        s = dict(self.c.get("/api/send-settings").json(), days=[True] * 7, hour_start="00:00", hour_end="23:59")
        self.c.put("/api/send-settings", json=s)

    def test_auth_url_and_forged_state(self):
        with self.assertRaises(gmail.GmailError):
            gmail.auth_url()
        db.set_setting("gmail_client", {"client_id": "id", "client_secret": "sec"})
        url = gmail.auth_url()
        self.assertIn("code_challenge_method=S256", url)
        self.assertIn("gmail.send", url)
        self.assertEqual(self.c.get("/api/gmail/callback?code=x&state=forjado").status_code, 400)

    def test_send_ok_then_not_twice(self):
        self._connect(); self._open_hours()
        did = self._approved_email_draft()
        with mock.patch.object(gmail, "_http", return_value={"threadId": "T1", "id": "M1"}) as http:
            r = self.c.post(f"/api/drafts/{did}/send")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["thread_id"], "T1")
        texto = base64.urlsafe_b64decode(http.call_args.kwargs["json_body"]["raw"]).decode()
        self.assertIn("dono@loja.com", texto)
        self.assertEqual(self.c.get("/api/stats").json()["email"]["sent"], 1)
        self.assertEqual(self.c.post(f"/api/drafts/{did}/send").status_code, 409)

    def test_send_blocked_cases(self):
        self._connect(); self._open_hours()
        did = self._approved_email_draft()
        self.c.patch(f"/api/drafts/{did}", json={"status": "pending"})
        self.assertEqual(self.c.post(f"/api/drafts/{did}/send").status_code, 409)  # não aprovado
        self.assertEqual(self.c.post("/api/drafts/999/send").status_code, 404)
        db.update_lead(db.list_leads()[0]["id"], email="")
        self.c.patch(f"/api/drafts/{did}", json={"status": "approved"})
        self.assertEqual(self.c.post(f"/api/drafts/{did}/send").status_code, 409)  # sem e-mail

    def test_send_respects_daily_limit(self):
        self._connect()
        s = dict(self.c.get("/api/send-settings").json(), days=[True] * 7, hour_start="00:00", hour_end="23:59", daily_limit=1, interval_min_s=0)
        self.c.put("/api/send-settings", json=s)
        a = self._approved_email_draft()
        with mock.patch.object(gmail, "_http", return_value={"threadId": "T1"}):
            self.assertEqual(self.c.post(f"/api/drafts/{a}/send").status_code, 200)
            db.add_leads([{"place_id": "g2", "name": "Outra", "email": "x@y.com"}])
            lid = [l for l in db.list_leads() if l["place_id"] == "g2"][0]["id"]
            b = self.c.post("/api/drafts", json={"lead_id": lid, "channel": "email", "body": "oi"}).json()["id"]
            self.c.patch(f"/api/drafts/{b}", json={"status": "approved"})
            r = self.c.post(f"/api/drafts/{b}/send")
        self.assertEqual(r.status_code, 429)
        self.assertIn("Limite diário", r.json()["detail"])

    def test_header_injection_is_neutralized(self):
        raw = gmail.build_raw("a@b.com\nBcc: x@y.com", "Oi\r\nBcc: z@y.com", "corpo")
        cabecalho = base64.urlsafe_b64decode(raw).decode().split("\n\n")[0]
        self.assertNotIn("\nBcc:", cabecalho)

    def test_check_replies_marks_only_real_replies(self):
        self._connect()
        did = self._approved_email_draft()
        db.set_thread(did, "T1"); db.mark_sent(did)
        meu = {"labelIds": ["SENT"], "payload": {"headers": [{"name": "From", "value": "eu@gmail.com"}]}}
        resposta = {"labelIds": ["INBOX"], "snippet": "Tenho interesse",
                    "payload": {"headers": [{"name": "From", "value": "Dono <dono@loja.com>"}]}}
        with mock.patch.object(gmail, "_http", return_value={"messages": [meu]}):
            self.assertEqual(self.c.post("/api/gmail/check-replies").json(), {"checked": 1, "replies": 0})
        with mock.patch.object(gmail, "_http", return_value={"messages": [meu, resposta]}):
            self.assertEqual(self.c.post("/api/gmail/check-replies").json(), {"checked": 1, "replies": 1})
        self.assertEqual(self.c.get("/api/stats").json()["email"]["replied"], 1)
        self.assertEqual(self.c.get("/api/drafts").json()[0]["reply_text"], "Tenho interesse")


if __name__ == "__main__":
    unittest.main()
