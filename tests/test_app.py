"""Testes do painel e da busca (sem rede: o Google Places é simulado)."""
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["MEU_VENDEDOR_DATA"] = tempfile.mkdtemp(prefix="mv-test-")
os.environ.pop("GOOGLE_PLACES_API_KEY", None)

from fastapi.testclient import TestClient  # noqa: E402

from app import config, db, drafts, places  # noqa: E402
from app.main import app  # noqa: E402

FAKE_PLACE = {
    "id": "p1", "displayName": {"text": "Moda Bela"}, "formattedAddress": "Rua A, 1",
    "nationalPhoneNumber": "(19) 3000-0000", "websiteUri": "https://modabela.example",
    "googleMapsUri": "https://maps.example/p1", "rating": 4.6, "userRatingCount": 120,
}


class Base(unittest.TestCase):
    def setUp(self):
        if config.DB_PATH.exists():
            config.DB_PATH.unlink()
        self.c = TestClient(app, base_url="http://127.0.0.1:8765")


class PanelTests(Base):
    def test_index_and_i18n(self):
        self.assertEqual(self.c.get("/").status_code, 200)
        keys = None
        for lang in config.LANGUAGES:
            r = self.c.get(f"/api/i18n/{lang}")
            self.assertEqual(r.status_code, 200)
            k = set(r.json())
            keys = keys or k
            self.assertEqual(k, keys, f"{lang} tem chaves diferentes das outras")
        self.assertEqual(self.c.get("/api/i18n/xx").status_code, 404)

    def test_profile_roundtrip_and_validation(self):
        r = self.c.put("/api/profile", json={"company": "Acme", "language": "es"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.c.get("/api/profile").json()["company"], "Acme")
        self.assertEqual(self.c.put("/api/profile", json={"language": "fr"}).status_code, 422)

    def test_send_settings_validation(self):
        base = self.c.get("/api/send-settings").json()
        self.assertEqual(base["mode"], "manual")
        bad = dict(base, interval_min_s=500, interval_max_s=10)
        self.assertEqual(self.c.put("/api/send-settings", json=bad).status_code, 422)
        self.assertEqual(self.c.put("/api/send-settings", json=dict(base, daily_limit=0)).status_code, 422)
        self.assertEqual(self.c.put("/api/send-settings", json=dict(base, hour_start="19:00", hour_end="09:00")).status_code, 422)
        self.assertEqual(self.c.put("/api/send-settings", json=dict(base, days=[True])).status_code, 422)
        ok = dict(base, daily_limit=15, mode="auto")
        self.assertEqual(self.c.put("/api/send-settings", json=ok).status_code, 200)
        self.assertEqual(self.c.get("/api/send-settings").json()["daily_limit"], 15)

    def test_api_key_never_returned(self):
        self.c.put("/api/api-key", json={"api_key": "segredo123"})
        r = self.c.get("/api/api-key")
        self.assertTrue(r.json()["set"])
        self.assertNotIn("segredo123", r.text)

    def test_blocks_foreign_host_and_origin(self):
        self.assertEqual(self.c.get("/api/profile", headers={"Host": "evil.com"}).status_code, 403)
        r = self.c.put("/api/profile", json={"company": "x"}, headers={"Origin": "http://evil.com"})
        self.assertEqual(r.status_code, 403)
        ok = self.c.put("/api/profile", json={"company": "x"}, headers={"Origin": "http://127.0.0.1:8765"})
        self.assertEqual(ok.status_code, 200)


class FlowTests(Base):
    def test_search_dedupe_and_drafts(self):
        self.c.put("/api/api-key", json={"api_key": "k"})
        self.c.put("/api/profile", json={"owner_name": "Ana", "company": "Acme", "offer": "Vendemos X.", "language": "pt"})
        with mock.patch.object(places, "_post", return_value={"places": [FAKE_PLACE]}) as post:
            r1 = self.c.post("/api/search", json={"niche": "moda", "location": "Campinas"})
            r2 = self.c.post("/api/search", json={"niche": "moda", "location": "Campinas"})
        self.assertEqual(r1.json(), {"new": 1, "total": 1})
        self.assertEqual(r2.json(), {"new": 0, "total": 1})  # não duplica
        self.assertEqual(post.call_args[0][1]["textQuery"], "moda Campinas")
        lead = self.c.get("/api/leads").json()[0]
        self.assertEqual(lead["name"], "Moda Bela")

        gid = self.c.post(f"/api/leads/{lead['id']}/draft", json={"channel": "email"}).json()["id"]
        d = self.c.get("/api/drafts?status=pending").json()[0]
        self.assertEqual(d["id"], gid)
        self.assertIn("Moda Bela", d["subject"])
        self.assertIn("Ana", d["body"])
        self.assertIn("sair", d["body"])

        self.assertEqual(self.c.patch(f"/api/drafts/{gid}", json={"status": "approved", "body": "novo"}).status_code, 200)
        self.assertEqual(self.c.get("/api/drafts?status=approved").json()[0]["body"], "novo")
        self.assertEqual(self.c.patch(f"/api/drafts/{gid}", json={"status": "enviado"}).status_code, 422)

        self.assertEqual(self.c.patch(f"/api/leads/{lead['id']}", json={"status": "approved"}).json()["status"], "approved")
        self.assertEqual(self.c.delete(f"/api/leads/{lead['id']}").status_code, 200)
        self.assertEqual(self.c.get("/api/drafts").json(), [])  # rascunhos saem junto com a empresa
        self.assertEqual(self.c.delete("/api/leads/999").status_code, 404)

    def test_search_without_key_is_clear_error(self):
        r = self.c.post("/api/search", json={"niche": "moda"})
        self.assertEqual(r.status_code, 400)
        self.assertIn("chave", r.json()["detail"].lower())

    def test_post_draft_for_missing_lead(self):
        self.assertEqual(self.c.post("/api/drafts", json={"lead_id": 42, "channel": "email", "body": "x"}).status_code, 404)

    def test_html_in_name_is_stored_verbatim(self):
        db.add_leads([{"place_id": "x", "name": "<img src=x onerror=alert(1)>"}])
        self.assertEqual(self.c.get("/api/leads").json()[0]["name"], "<img src=x onerror=alert(1)>")


class PlacesTests(unittest.TestCase):
    def test_pagination_and_limit(self):
        pages = [
            {"places": [dict(FAKE_PLACE, id=f"a{i}") for i in range(20)], "nextPageToken": "t1"},
            {"places": [dict(FAKE_PLACE, id=f"b{i}") for i in range(20)]},
        ]
        with mock.patch.object(places, "_post", side_effect=pages) as post:
            r = places.search("k", "moda", max_results=25)
        self.assertEqual(len(r), 25)
        self.assertEqual(post.call_args_list[1][0][1]["pageToken"], "t1")
        self.assertEqual(post.call_args_list[1][0][1]["pageSize"], 5)

    def test_missing_key_and_empty_query(self):
        with self.assertRaises(places.PlacesError):
            places.search("", "moda")
        with self.assertRaises(places.PlacesError):
            places.search("k", "  ")

    def test_http_error_message(self):
        err = urllib.error.HTTPError("u", 403, "Forbidden", {}, io.BytesIO(json.dumps({"error": {"message": "API key invalid"}}).encode()))
        with mock.patch("urllib.request.urlopen", side_effect=err):
            with self.assertRaises(places.PlacesError) as cm:
                places.search("k", "moda")
        self.assertIn("API key invalid", str(cm.exception))


class DraftTests(unittest.TestCase):
    def test_all_languages_and_missing_fields(self):
        for lang in config.LANGUAGES:
            s, b = drafts.render({"name": "Loja"}, {"language": lang}, "email")
            self.assertIn("Loja", s)
            self.assertNotIn("{", b)
            s2, b2 = drafts.render({"name": "Loja"}, {"language": lang}, "whatsapp")
            self.assertEqual(s2, "")
            self.assertTrue(b2)


if __name__ == "__main__":
    unittest.main()
