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


def _migrate(con) -> None:
    """Acrescenta colunas novas em bancos criados por versões anteriores."""
    novas = {
        "leads": {"email": "TEXT DEFAULT ''"},
        "drafts": {"sent_at": "TEXT", "replied_at": "TEXT", "reply_text": "TEXT DEFAULT ''", "thread_id": "TEXT DEFAULT ''"},
    }
    for tabela, colunas in novas.items():
        existentes = {r["name"] for r in con.execute(f"PRAGMA table_info({tabela})")}
        for nome, tipo in colunas.items():
            if nome not in existentes:
                con.execute(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}")


@contextmanager
def db():
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA)
    _migrate(con)
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
                "INSERT OR IGNORE INTO leads (place_id, name, address, phone, email, website, maps_url, rating, reviews, niche, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (p.get("place_id"), p.get("name") or "?", p.get("address", ""), p.get("phone", ""), p.get("email", ""),
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


def update_lead(lead_id: int, status: str | None = None, notes: str | None = None, email: str | None = None) -> bool:
    sets, vals = [], []
    if email is not None:
        sets.append("email = ?"); vals.append(email)
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
    sql = ("SELECT d.*, l.name AS lead_name, l.phone AS lead_phone, l.website AS lead_website, l.email AS lead_email "
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


# ---------- envio, respostas e números ----------

def mark_sent(draft_id: int) -> str:
    """Registra que a mensagem foi enviada. Devolve "ok", "missing" ou "not_approved"."""
    with db() as con:
        row = con.execute("SELECT status, lead_id FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        if not row:
            return "missing"
        if row["status"] != "approved":
            return "not_approved"
        ts = now()
        con.execute("UPDATE drafts SET sent_at = COALESCE(sent_at, ?), updated_at = ? WHERE id = ?", (ts, ts, draft_id))
        con.execute("UPDATE leads SET status = 'contacted' WHERE id = ? AND status IN ('new', 'approved')", (row["lead_id"],))
    return "ok"


def mark_replied(draft_id: int, text: str = "") -> str:
    """Registra a resposta recebida. Devolve "ok", "missing" ou "not_sent"."""
    with db() as con:
        row = con.execute("SELECT sent_at FROM drafts WHERE id = ?", (draft_id,)).fetchone()
        if not row:
            return "missing"
        if not row["sent_at"]:
            return "not_sent"
        ts = now()
        con.execute("UPDATE drafts SET replied_at = COALESCE(replied_at, ?), reply_text = ?, updated_at = ? WHERE id = ?",
                    (ts, text, ts, draft_id))
    return "ok"


def is_mobile(phone: str) -> bool:
    """Celular brasileiro: DDD + 9 dígitos começando em 9 (fixo não recebe WhatsApp)."""
    d = "".join(c for c in (phone or "") if c.isdigit())
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]
    return len(d) == 11 and d[2] == "9"


def stats() -> dict:
    """Números por canal: prospectados (contatos coletados), enviadas e respondidas."""
    with db() as con:
        def n(sql, *args):
            return con.execute(sql, args).fetchone()[0]
        out = {}
        celulares = sum(is_mobile(r[0]) for r in con.execute("SELECT phone FROM leads"))
        for canal in ("email", "whatsapp"):
            out[canal] = {
                "prospected": celulares if canal == "whatsapp" else n("SELECT COUNT(*) FROM leads WHERE TRIM(COALESCE(email, '')) != ''"),
                "sent": n("SELECT COUNT(*) FROM drafts WHERE channel = ? AND sent_at IS NOT NULL", canal),
                "replied": n("SELECT COUNT(*) FROM drafts WHERE channel = ? AND replied_at IS NOT NULL", canal),
            }
    return out


# ---------- Gmail: apoio ao envio e à leitura de respostas ----------

def get_draft(draft_id: int) -> dict | None:
    with db() as con:
        row = con.execute("SELECT d.*, l.email AS lead_email FROM drafts d JOIN leads l ON l.id = d.lead_id WHERE d.id = ?",
                          (draft_id,)).fetchone()
    return dict(row) if row else None


def set_thread(draft_id: int, thread_id: str) -> None:
    with db() as con:
        con.execute("UPDATE drafts SET thread_id = ? WHERE id = ?", (thread_id, draft_id))


def sent_times(channel: str) -> list[str]:
    with db() as con:
        return [r[0] for r in con.execute("SELECT sent_at FROM drafts WHERE channel = ? AND sent_at IS NOT NULL", (channel,))]


def pending_threads() -> list[dict]:
    """E-mails enviados pelo app, com conversa conhecida, ainda sem resposta registrada."""
    with db() as con:
        rows = con.execute("SELECT id, thread_id FROM drafts WHERE channel = 'email' AND sent_at IS NOT NULL "
                           "AND replied_at IS NULL AND COALESCE(thread_id, '') != ''").fetchall()
    return [dict(r) for r in rows]


# ---------- aprovar em lote e fila de envio ----------

def approve_all(channel: str | None = None) -> int:
    """Aprova de uma vez todos os rascunhos pendentes (de um canal, ou de todos). Devolve quantos."""
    sql, args = "UPDATE drafts SET status = 'approved', updated_at = ? WHERE status = 'pending'", [now()]
    if channel:
        sql += " AND channel = ?"
        args.append(channel)
    with db() as con:
        return con.execute(sql, args).rowcount


_QUEUE_SQL = ("FROM drafts d JOIN leads l ON l.id = d.lead_id WHERE d.channel = 'email' AND d.sent_at IS NULL "
              "AND TRIM(COALESCE(l.email, '')) != '' AND d.status IN ({})")


def _queue_status(include_pending: bool) -> str:
    return "'approved', 'pending'" if include_pending else "'approved'"


def next_email_to_send(include_pending: bool = False) -> dict | None:
    """Próximo e-mail da fila: aprovado (e, no modo automático, também os pendentes). Rejeitados nunca."""
    with db() as con:
        row = con.execute("SELECT d.*, l.email AS lead_email, l.name AS lead_name " +
                          _QUEUE_SQL.format(_queue_status(include_pending)) + " ORDER BY d.id ASC LIMIT 1").fetchone()
    return dict(row) if row else None


def count_email_to_send(include_pending: bool = False) -> int:
    with db() as con:
        return con.execute("SELECT COUNT(*) " + _QUEUE_SQL.format(_queue_status(include_pending))).fetchone()[0]
