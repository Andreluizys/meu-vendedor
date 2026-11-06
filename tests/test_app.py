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

from app import cnpj, config, db, drafts, emailfinder, places, roles  # noqa: E402
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


class StatsTests(Base):
    def _lead_and_draft(self, channel="email", email="", phone=""):
        db.add_leads([{"place_id": "z1", "name": "Loja Z", "phone": phone, "website": "https://z.example"}])
        lid = db.list_leads()[0]["id"]
        if email:
            self.c.patch(f"/api/leads/{lid}", json={"email": email})
        return lid, self.c.post("/api/drafts", json={"lead_id": lid, "channel": channel, "body": "oi"}).json()["id"]

    def test_counters_follow_the_flow(self):
        lid, did = self._lead_and_draft(email="a@z.example", phone="(19) 9 0000-0000")
        self.assertEqual(self.c.get("/api/stats").json(), {
            "email": {"prospected": 1, "sent": 0, "replied": 0},
            "whatsapp": {"prospected": 1, "sent": 0, "replied": 0}})
        self.assertEqual(self.c.post(f"/api/drafts/{did}/sent").status_code, 409)       # precisa aprovar antes
        self.c.patch(f"/api/drafts/{did}", json={"status": "approved"})
        self.assertEqual(self.c.post(f"/api/drafts/{did}/replied", json={"text": "x"}).status_code, 409)  # precisa enviar antes
        self.assertEqual(self.c.post(f"/api/drafts/{did}/sent").status_code, 200)
        self.assertEqual(self.c.post(f"/api/drafts/{did}/replied", json={"text": "Tenho interesse"}).status_code, 200)
        st = self.c.get("/api/stats").json()
        self.assertEqual(st["email"], {"prospected": 1, "sent": 1, "replied": 1})
        self.assertEqual(st["whatsapp"]["sent"], 0)                                      # não mistura canais
        self.assertEqual(self.c.get("/api/leads").json()[0]["status"], "contacted")
        self.assertEqual(self.c.get("/api/drafts").json()[0]["reply_text"], "Tenho interesse")

    def test_invalid_email_rejected_and_missing_draft(self):
        lid, _ = self._lead_and_draft()
        self.assertEqual(self.c.patch(f"/api/leads/{lid}", json={"email": "sem-arroba"}).status_code, 422)
        self.assertEqual(self.c.post("/api/drafts/999/sent").status_code, 404)

    def test_migrates_old_database(self):
        import sqlite3
        config.DB_PATH.unlink(missing_ok=True)
        con = sqlite3.connect(config.DB_PATH)
        con.executescript("CREATE TABLE leads (id INTEGER PRIMARY KEY, place_id TEXT UNIQUE, name TEXT NOT NULL, phone TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'new', created_at TEXT NOT NULL);"
                          "CREATE TABLE drafts (id INTEGER PRIMARY KEY, lead_id INTEGER, channel TEXT, subject TEXT, body TEXT, status TEXT, created_at TEXT, updated_at TEXT);")
        con.commit(); con.close()
        self.assertEqual(db.stats()["email"]["prospected"], 0)   # abre sem erro e cria as colunas novas


class EmailFinderTests(unittest.TestCase):
    def test_prefers_same_domain_and_skips_junk(self):
        page = '<a href="mailto:contato@loja.com.br">x</a> foto@2x.png suporte@wixpress.com outro@gmail.com'
        with mock.patch.object(emailfinder, "_fetch", return_value=page):
            self.assertEqual(emailfinder.find_email("https://www.loja.com.br"), "contato@loja.com.br")

    def test_no_site_or_no_email(self):
        self.assertEqual(emailfinder.find_email(""), "")
        with mock.patch.object(emailfinder, "_fetch", return_value="sem nada"):
            self.assertEqual(emailfinder.find_email("loja.com"), "")

    def test_refuses_internal_addresses(self):
        self.assertEqual(emailfinder._fetch("http://127.0.0.1:8765/"), "")
        self.assertEqual(emailfinder._fetch("file:///etc/passwd"), "")


class RolesTests(Base):
    def test_all_roles_have_playbook_and_three_languages(self):
        for lang in config.LANGUAGES:
            lista = self.c.get(f"/api/roles?lang={lang}").json()["roles"]
            self.assertGreaterEqual(len(lista), 7)
            for r in lista:
                self.assertTrue(r["name"] and r["description"])
        for rid in roles.role_ids():
            self.assertIn("nível sênior", roles.playbook(rid).lower())

    def test_switch_role_and_reject_unknown(self):
        self.assertEqual(self.c.get("/api/roles").json()["active"], "vendedor")
        self.assertEqual(self.c.put("/api/role", json={"id": "social"}).status_code, 200)
        self.assertEqual(self.c.get("/api/roles").json()["active"], "social")
        self.assertEqual(self.c.put("/api/role", json={"id": "../../etc/passwd"}).status_code, 404)
        self.assertIsNone(roles.playbook("../index"))


class CnpjTests(Base):
    def _row(self, cnae="9602501", situacao="02", uf="SP", fantasia="SALAO DA ANA", email="ana@salao.com", ddd="19", tel="991234567"):
        r = [""] * 30
        r[0], r[1], r[2] = "12345678", "0001", "95"
        r[4], r[5], r[11], r[19] = fantasia, situacao, cnae, uf
        r[13], r[14], r[15], r[17], r[18] = "RUA", "DAS FLORES", "10", "CENTRO", "13000000"
        r[21], r[22], r[27] = ddd, tel, email
        return r

    def _write(self, folder, rows):
        import csv
        with open(folder / "Estabelecimentos0.csv", "w", encoding="latin-1", newline="") as f:
            csv.writer(f, delimiter=";", quotechar='"', quoting=csv.QUOTE_ALL).writerows(rows)

    def test_niche_to_cnae(self):
        self.assertIn("9602501", cnpj.cnaes_for("Manicure"))
        self.assertIn("9602501", cnpj.cnaes_for("cabeleireiro"))
        self.assertEqual(cnpj.cnaes_for("9602-5/01"), ["9602501"])
        self.assertEqual(cnpj.cnaes_for("xyz desconhecido"), [])

    def test_import_filters_active_cnae_and_uf(self):
        pasta = Path(tempfile.mkdtemp(prefix="cnpj-"))
        self._write(pasta, [self._row(), self._row(situacao="08"), self._row(cnae="4781400"), self._row(uf="RJ")])
        achadas = cnpj.import_from_files("manicure", "sp", folder=pasta)
        self.assertEqual(len(achadas), 1)
        self.assertEqual(achadas[0]["name"], "Salao Da Ana")
        self.assertEqual(achadas[0]["email"], "ana@salao.com")
        self.assertEqual(achadas[0]["phone"], "(19) 991234567")
        self.assertEqual(len(cnpj.import_from_files("manicure", "", folder=pasta)), 2)  # sem UF traz SP e RJ

    def test_import_errors_are_clear(self):
        vazia = Path(tempfile.mkdtemp(prefix="cnpj-"))
        with self.assertRaises(cnpj.CnpjError):
            cnpj.import_from_files("manicure", folder=vazia)
        with self.assertRaises(cnpj.CnpjError):
            cnpj.import_from_files("ramo inexistente", folder=vazia)

    def test_lead_saved_with_email_and_counted(self):
        db.add_leads([dict(self._lead_dict())], "manicure")
        st = self.c.get("/api/stats").json()
        self.assertEqual(st["email"]["prospected"], 1)
        self.assertEqual(st["whatsapp"]["prospected"], 1)

    def _lead_dict(self):
        return {"place_id": "cnpj:1", "name": "Salão", "phone": "(19) 99123-4567", "email": "a@b.com"}

    def test_only_mobile_counts_for_whatsapp(self):
        self.assertTrue(db.is_mobile("(19) 99123-4567"))
        self.assertTrue(db.is_mobile("+55 19 99123-4567"))
        self.assertFalse(db.is_mobile("(19) 3123-4567"))
        self.assertFalse(db.is_mobile(""))


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
