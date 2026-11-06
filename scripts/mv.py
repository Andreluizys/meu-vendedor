"""Linha de comando usada pela skill (e por você). Fala direto com o banco local, sem precisar do painel aberto.

Exemplos (da raiz do projeto):
  python scripts/mv.py profile-set --json "{\"company\": \"Minha Loja\", \"language\": \"pt\"}"
  python scripts/mv.py profile-get
  python scripts/mv.py search --niche "loja de moda" --location "Campinas, SP" --max 20
  python scripts/mv.py leads --status new
  python scripts/mv.py draft-add --lead-id 3 --channel email --subject "Oi" --body-file msg.txt
  python scripts/mv.py drafts --status pending
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from app import cnpj, db, places, roles  # noqa: E402
from app.main import Profile, api_key  # noqa: E402


def out(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_profile_get(a):
    out(Profile(**db.get_setting("profile", {})).model_dump())


def cmd_profile_set(a):
    atual = db.get_setting("profile", {})
    atual.update(json.loads(a.json))
    out(_save_profile(atual))


def _save_profile(data: dict) -> dict:
    p = Profile(**data).model_dump()  # valida tamanhos e idioma
    db.set_setting("profile", p)
    return p


def cmd_search(a):
    profile = Profile(**db.get_setting("profile", {}))
    query = f"{a.niche} {a.location}".strip()
    found = places.search(api_key(), query, a.max, profile.language)
    new, total = db.add_leads(found, a.niche)
    out({"new": new, "total": total})


def cmd_roles(a):
    out({"active": roles.get_active(), "roles": roles.list_roles(a.lang)})


def cmd_role_get(a):
    print(roles.get_active())


def cmd_role_set(a):
    if not roles.set_active(a.id):
        sys.exit(f"role not found. Options: {', '.join(roles.role_ids())}")
    print(a.id)


def cmd_role_show(a):
    texto = roles.playbook(a.id or roles.get_active())
    if texto is None:
        sys.exit(f"role not found. Options: {', '.join(roles.role_ids())}")
    print(texto)


def cmd_cnpj_import(a):
    found = cnpj.import_from_files(a.niche, a.uf or "", a.limit)
    new, total = db.add_leads(found, a.niche)
    out({"new": new, "total": total})


def cmd_leads(a):
    out(db.list_leads(a.status))


def cmd_draft_add(a):
    if a.channel not in db.CHANNELS:
        sys.exit("channel must be email or whatsapp")
    body = Path(a.body_file).read_text(encoding="utf-8") if a.body_file else a.body
    if not body:
        sys.exit("provide --body or --body-file")
    new_id = db.add_draft(a.lead_id, a.channel, body, a.subject or "")
    if new_id is None:
        sys.exit(f"lead {a.lead_id} not found")
    out({"id": new_id})


def cmd_drafts(a):
    out(db.list_drafts(a.status))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("profile-get").set_defaults(fn=cmd_profile_get)
    s = sub.add_parser("profile-set"); s.add_argument("--json", required=True); s.set_defaults(fn=cmd_profile_set)
    s = sub.add_parser("search")
    s.add_argument("--niche", required=True); s.add_argument("--location", default="")
    s.add_argument("--max", type=int, default=20); s.set_defaults(fn=cmd_search)
    s = sub.add_parser("roles"); s.add_argument("--lang", default="pt"); s.set_defaults(fn=cmd_roles)
    sub.add_parser("role-get").set_defaults(fn=cmd_role_get)
    s = sub.add_parser("role-set"); s.add_argument("--id", required=True); s.set_defaults(fn=cmd_role_set)
    s = sub.add_parser("role-show"); s.add_argument("--id"); s.set_defaults(fn=cmd_role_show)
    s = sub.add_parser("cnpj-import")
    s.add_argument("--niche", required=True); s.add_argument("--uf"); s.add_argument("--limit", type=int, default=500)
    s.set_defaults(fn=cmd_cnpj_import)
    s = sub.add_parser("leads"); s.add_argument("--status"); s.set_defaults(fn=cmd_leads)
    s = sub.add_parser("draft-add")
    s.add_argument("--lead-id", type=int, required=True); s.add_argument("--channel", required=True)
    s.add_argument("--subject"); s.add_argument("--body"); s.add_argument("--body-file")
    s.set_defaults(fn=cmd_draft_add)
    s = sub.add_parser("drafts"); s.add_argument("--status"); s.set_defaults(fn=cmd_drafts)
    a = ap.parse_args()
    try:
        a.fn(a)
    except (places.PlacesError, cnpj.CnpjError) as e:
        sys.exit(str(e))


if __name__ == "__main__":
    main()
