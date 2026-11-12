"""Testes da fila de envio (manual em lote e automático). Sem rede: o Gmail é simulado."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["MEU_VENDEDOR_DATA"] = tempfile.mkdtemp(prefix="mv-test-sender-")
os.environ.pop("GOOGLE_PLACES_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from app import config, db, gmail  # noqa: E402
from app.main import app  # noqa: E402
from app.sender import Sender  # noqa: E402

QUARTA_10H = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)  # quarta-feira, dentro do horário


class SenderTests(unittest.TestCase):
    def setUp(self):
        if config.DB_PATH.exists():
            config.DB_PATH.unlink()
        self.c = TestClient(app, base_url="http://127.0.0.1:8765")
        self.settings = {"mode": "manual", "daily_limit": 10, "interval_min_s": 60, "interval_max_s": 120,
                         "days": [True] * 7, "hour_start": "09:00", "hour_end": "18:00"}
        self.t = QUARTA_10H
        self.sent = []
        self.s = Sender(settings_fn=lambda: self.settings, send_fn=self._send,
                        now_fn=lambda: self.t, rand=lambda lo, hi: hi)
        # os envios gravam a hora do relógio simulado, não a real
        p = mock.patch.object(db, "now", lambda: self.t.isoformat(timespec="seconds"))
        p.start()
        self.addCleanup(p.stop)
        db.set_setting("gmail_token", {"refresh_token": "x", "email": "eu@x.com"})
        db.set_setting("gmail_client", {"client_id": "id", "client_secret": "sec"})

    def _send(self, to, subject, body):
        self.sent.append(to)
        return "thr-" + to

    def _draft(self, name, email, status="pending"):
        lead = db.add_leads([{"place_id": name, "name": name, "email": email, "address": "", "phone": "", "website": ""}], "x")
        lid = [l for l in db.list_leads() if l["name"] == name][0]["id"]
        d = db.add_draft(lid, "email", "Olá", "Assunto")
        db.update_draft(d, status=status)
        return d

    def test_manual_sends_nothing_until_user_starts(self):
        self._draft("A", "a@a.com", "approved")
        self.assertEqual(self.s.step(), "off")
        self.assertEqual(self.sent, [])

    def test_approve_all_then_send_in_batch_respecting_interval(self):
        for n in "ABC":
            self._draft(n, n.lower() + "@x.com")
        self.assertEqual(self.c.post("/api/drafts/approve-all", json={}).json()["approved"], 3)
        self.s.start_queue()
        self.assertEqual(self.s.step(), "sent")
        self.assertEqual(self.s.step(), "waiting")       # intervalo entre envios
        self.t += timedelta(seconds=130)
        self.assertEqual(self.s.step(), "sent")
        self.t += timedelta(seconds=130)
        self.assertEqual(self.s.step(), "sent")
        self.assertEqual(self.s.step(), "idle")          # fila acabou
        self.assertFalse(self.s.queue_on)
        self.assertEqual(self.sent, ["a@x.com", "b@x.com", "c@x.com"])

    def test_manual_never_sends_pending_or_rejected(self):
        self._draft("A", "a@a.com", "pending")
        self._draft("B", "b@b.com", "rejected")
        self.s.start_queue()
        self.assertEqual(self.s.step(), "idle")
        self.assertEqual(self.sent, [])

    def test_auto_sends_without_approval_but_never_rejected(self):
        self.settings["mode"] = "auto"
        d = self._draft("A", "a@a.com", "pending")
        self._draft("B", "b@b.com", "rejected")
        self.assertEqual(self.s.step(), "sent")
        self.assertEqual(self.sent, ["a@a.com"])
        self.assertEqual(db.get_draft(d)["status"], "approved")
        self.t += timedelta(seconds=130)
        self.assertEqual(self.s.step(), "idle")

    def test_limits_apply_in_both_modes(self):
        self.settings.update(mode="auto", daily_limit=1)
        self._draft("A", "a@a.com")
        self._draft("B", "b@b.com")
        self.assertEqual(self.s.step(), "sent")
        self.t += timedelta(seconds=200)
        self.assertEqual(self.s.step(), "waiting")
        self.assertIn("Limite diário", self.s.status()["reason"])
        self.t = QUARTA_10H.replace(hour=23)             # fora do horário
        self.settings["daily_limit"] = 50
        self.assertEqual(self.s.step(), "waiting")
        self.assertIn("horário", self.s.status()["reason"])

    def test_draft_without_email_is_skipped(self):
        self.settings["mode"] = "auto"
        self._draft("A", "")
        self.assertEqual(self.s.step(), "idle")
        self.assertEqual(self.sent, [])

    def test_error_pauses_until_resume(self):
        self.settings["mode"] = "auto"
        self._draft("A", "a@a.com")
        self.s.send_fn = mock.Mock(side_effect=gmail.GmailError("recusado"))
        self.assertEqual(self.s.step(), "error")
        self.assertIn("recusado", self.s.status()["error"])
        self.assertEqual(self.s.step(), "error")         # não fica tentando em loop
        self.s.send_fn = self._send
        self.s.resume()
        self.assertEqual(self.s.step(), "sent")

    def test_start_requires_gmail(self):
        db.set_setting("gmail_token", {})
        with self.assertRaises(gmail.GmailError):
            self.s.start_queue()

    def test_endpoints(self):
        self.assertEqual(self.c.get("/api/sender/status").json()["mode"], "manual")
        body = self.c.get("/api/send-settings").json()
        self.assertEqual(self.c.put("/api/send-settings", json=dict(body, mode="auto")).status_code, 200)
        self.assertEqual(self.c.get("/api/send-settings").json()["mode"], "auto")
        self.assertEqual(self.c.post("/api/sender/stop").status_code, 200)
        db.set_setting("gmail_token", {})
        self.assertEqual(self.c.post("/api/sender/start").status_code, 400)  # sem Gmail conectado


if __name__ == "__main__":
    unittest.main()
