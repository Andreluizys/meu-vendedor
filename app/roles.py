"""Funções pré-definidas (marqueteiro, vendedor, designer...). Cada uma tem um guia em roles/<id>.md
que a skill carrega para passar a agir naquela função."""
import json

from . import config, db

ROLES_DIR = config.ROOT / "roles"
DEFAULT_ROLE = "vendedor"


def _index() -> list[dict]:
    return json.loads((ROLES_DIR / "index.json").read_text(encoding="utf-8"))


def role_ids() -> list[str]:
    return [r["id"] for r in _index()]


def list_roles(lang: str = config.DEFAULT_LANGUAGE) -> list[dict]:
    lang = lang if lang in config.LANGUAGES else config.DEFAULT_LANGUAGE
    return [{"id": r["id"], "icon": r.get("icon", ""), "name": r["name"][lang], "description": r["description"][lang]}
            for r in _index()]


def playbook(role_id: str) -> str | None:
    if role_id not in role_ids():  # só ids conhecidos: nunca monta caminho a partir de texto livre
        return None
    return (ROLES_DIR / f"{role_id}.md").read_text(encoding="utf-8")


def get_active() -> str:
    atual = db.get_setting("active_role", DEFAULT_ROLE)
    return atual if atual in role_ids() else DEFAULT_ROLE


def set_active(role_id: str) -> bool:
    if role_id not in role_ids():
        return False
    db.set_setting("active_role", role_id)
    return True
