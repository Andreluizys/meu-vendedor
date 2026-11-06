"""Banco SQLite local (um arquivo em data/). Sem servidor, sem instalação."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leads (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    place_id   TEXT UNIQUE,
    name       TEXT NOT NULL,
    address    TEXT DEFAULT '',
    phone      TEXT DEFAULT '',
    website    TEXT DEFAULT '',
    maps_url   TEXT DEFAULT '',
    rating     REAL,
    reviews    INTEGER,
    niche      TEXT DEFAULT '',
    status     TEXT NOT NULL DEFAULT 'new',
    notes      TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    lead_id    INTEGER NOT NULL REFERENCES leads(id) ON DELETE CASCADE,
    channel    TEXT NOT NULL,
    subject    TEXT DEFAULT '',
    body       TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(status);
"""

LEAD_STATUSES = ("new", "approved", "rejected", "contacted")
DRAFT_STATUSES = ("pending", "approved", "rejected")
CHANNELS = ("email", "whatsapp")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def db():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


# ---------- configurações (JSON por chave) ----------

def get_setting(key: str, default=None):
    with db() as con:
        row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(key: str, value) -> None:
    with db() as con:
        con.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value, ensure_ascii=False)),
        )


# ---------- leads ----------

def add_leads(places: list[dict], niche: str = "") -> tuple[int, int]:
    """Grava empresas ignorando as já existentes. Devolve (novas, total recebidas)."""
    novas = 0
    with db() as con:
        for p in places:
            cur = con.execute(
                "INSERT OR IGNORE INTO leads (place_id, name, address, phone, website, maps_url, rating, reviews, niche, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (p.get("place_id"), p.get("name") or "?", p.get("address", ""), p.get("phone", ""),
                 p.get("website", ""), p.get("maps_url", ""), p.get("rating"), p.get("reviews"), niche, now()),
            )
            novas += cur.rowcount
    return novas, len(places)


def list_leads(status: str | None = None) -> list[dict]:
    with db() as con:
        if status:
            rows = con.execute("SELECT * FROM leads WHERE status = ? ORDER BY id DESC", (status,)).fetchall()
        else:
            rows = con.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
    return [dict(r) for r in rows]


def get_lead(lead_id: int) -> dict | None:
    with db() as con:
        row = con.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return dict(row) if row else None


def update_lead(lead_id: int, status: str | None = None, notes: str | None = None) -> bool:
    sets, vals = [], []
    if status is not None:
        sets.append("status = ?"); vals.append(status)
    if notes is not None:
        sets.append("notes = ?"); vals.append(notes)
    if not sets:
        return get_lead(lead_id) is not None
    with db() as con:
        cur = con.execute(f"UPDATE leads SET {', '.join(sets)} WHERE id = ?", (*vals, lead_id))
        return cur.rowcount > 0


def delete_lead(lead_id: int) -> bool:
    with db() as con:
        return con.execute("DELETE FROM leads WHERE id = ?", (lead_id,)).rowcount > 0


# ---------- rascunhos ----------

def add_draft(lead_id: int, channel: str, body: str, subject: str = "") -> int | None:
    if get_lead(lead_id) is None:
        return None
    ts = now()
    with db() as con:
        cur = con.execute(
            "INSERT INTO drafts (lead_id, channel, subject, body, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (lead_id, channel, subject, body, ts, ts),
        )
        return cur.lastrowid


def list_drafts(status: str | None = None) -> list[dict]:
    sql = ("SELECT d.*, l.name AS lead_name, l.phone AS lead_phone, l.website AS lead_website "
           "FROM drafts d JOIN leads l ON l.id = d.lead_id")
    with db() as con:
        if status:
            rows = con.execute(sql + " WHERE d.status = ? ORDER BY d.id DESC", (status,)).fetchall()
        else:
            rows = con.execute(sql + " ORDER BY d.id DESC").fetchall()
    return [dict(r) for r in rows]


def update_draft(draft_id: int, subject: str | None = None, body: str | None = None, status: str | None = None) -> bool:
    sets, vals = ["updated_at = ?"], [now()]
    for col, val in (("subject", subject), ("body", body), ("status", status)):
        if val is not None:
            sets.append(f"{col} = ?"); vals.append(val)
    with db() as con:
        cur = con.execute(f"UPDATE drafts SET {', '.join(sets)} WHERE id = ?", (*vals, draft_id))
        return cur.rowcount > 0


def delete_draft(draft_id: int) -> bool:
    with db() as con:
        return con.execute("DELETE FROM drafts WHERE id = ?", (draft_id,)).rowcount > 0
