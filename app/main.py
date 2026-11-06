"""API e painel local (FastAPI). Só responde na própria máquina."""
import json
import os
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import config, db, drafts as drafts_mod, places

STATIC = Path(__file__).parent / "static"
LOCALES = Path(__file__).parent / "locales"
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}

app = FastAPI(title=config.APP_NAME, docs_url=None, redoc_url=None)


# ---------- proteção: só a própria máquina, e só o próprio painel ----------

@app.middleware("http")
async def only_local(request: Request, call_next):
    host = urlsplit("//" + (request.headers.get("host") or "")).hostname
    if host not in LOCAL_HOSTS:  # barra DNS rebinding
        return JSONResponse({"detail": "forbidden host"}, status_code=403)
    origin = request.headers.get("origin")
    if origin and request.method not in ("GET", "HEAD", "OPTIONS"):
        if urlsplit(origin).netloc != request.headers.get("host"):  # barra outras páginas do navegador
            return JSONResponse({"detail": "forbidden origin"}, status_code=403)
    return await call_next(request)


# ---------- modelos ----------

class Profile(BaseModel):
    owner_name: str = Field("", max_length=120)
    company: str = Field("", max_length=160)
    offer: str = Field("", max_length=1000)
    audience: str = Field("", max_length=500)
    tone: str = Field("", max_length=200)
    cta: str = Field("", max_length=300)
    extra: str = Field("", max_length=2000)
    language: Literal["pt", "en", "es"] = "pt"


class SendSettings(BaseModel):
    """Guardado agora; passa a valer quando o envio for ligado (próxima fase)."""
    mode: Literal["manual", "auto"] = "manual"
    daily_limit: int = Field(30, ge=1, le=1000)
    interval_min_s: int = Field(60, ge=0, le=86400)
    interval_max_s: int = Field(180, ge=0, le=86400)
    days: list[bool] = Field(default_factory=lambda: [True] * 5 + [False] * 2, min_length=7, max_length=7)  # seg..dom
    hour_start: str = Field("09:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    hour_end: str = Field("18:00", pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    typing_simulation: bool = True
    typing_min_s: int = Field(4, ge=0, le=30)
    typing_max_s: int = Field(5, ge=0, le=30)


class SearchIn(BaseModel):
    niche: str = Field(..., min_length=1, max_length=200)
    location: str = Field("", max_length=200)
    max_results: int = Field(20, ge=1, le=60)


class ApiKeyIn(BaseModel):
    api_key: str = Field("", max_length=300)


class LeadPatch(BaseModel):
    status: Literal["new", "approved", "rejected", "contacted"] | None = None
    notes: str | None = Field(None, max_length=2000)


class DraftIn(BaseModel):
    lead_id: int
    channel: Literal["email", "whatsapp"]
    subject: str = Field("", max_length=300)
    body: str = Field(..., min_length=1, max_length=5000)


class DraftPatch(BaseModel):
    subject: str | None = Field(None, max_length=300)
    body: str | None = Field(None, min_length=1, max_length=5000)
    status: Literal["pending", "approved", "rejected"] | None = None


class GenerateIn(BaseModel):
    channel: Literal["email", "whatsapp"]


def _validate_send(s: SendSettings) -> None:
    if s.interval_min_s > s.interval_max_s:
        raise HTTPException(422, "interval_min_s must be <= interval_max_s")
    if s.typing_min_s > s.typing_max_s:
        raise HTTPException(422, "typing_min_s must be <= typing_max_s")
    if s.hour_start >= s.hour_end:
        raise HTTPException(422, "hour_start must be earlier than hour_end")


def api_key() -> str:
    return os.environ.get("GOOGLE_PLACES_API_KEY") or db.get_setting("places_api_key", "") or ""


# ---------- páginas e textos ----------

@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/i18n/{lang}")
def i18n(lang: str):
    if lang not in config.LANGUAGES:
        raise HTTPException(404, "language not found")
    return json.loads((LOCALES / f"{lang}.json").read_text(encoding="utf-8"))


@app.get("/api/info")
def info():
    return {"name": config.APP_NAME, "languages": config.LANGUAGES}


# ---------- perfil (resultado da entrevista) ----------

@app.get("/api/profile")
def get_profile():
    return Profile(**db.get_setting("profile", {})).model_dump()


@app.put("/api/profile")
def put_profile(p: Profile):
    db.set_setting("profile", p.model_dump())
    return p.model_dump()


# ---------- configurações de envio e chave ----------

@app.get("/api/send-settings")
def get_send_settings():
    return SendSettings(**db.get_setting("send_settings", {})).model_dump()


@app.put("/api/send-settings")
def put_send_settings(s: SendSettings):
    _validate_send(s)
    db.set_setting("send_settings", s.model_dump())
    return s.model_dump()


@app.get("/api/api-key")
def get_api_key():
    return {"set": bool(api_key()), "from_env": bool(os.environ.get("GOOGLE_PLACES_API_KEY"))}


@app.put("/api/api-key")
def put_api_key(k: ApiKeyIn):
    db.set_setting("places_api_key", k.api_key.strip())
    return {"set": bool(api_key())}


# ---------- busca e leads ----------

@app.post("/api/search")
def search(s: SearchIn):
    profile = Profile(**db.get_setting("profile", {}))
    query = f"{s.niche} {s.location}".strip()
    try:
        found = places.search(api_key(), query, s.max_results, profile.language)
    except places.PlacesError as e:
        raise HTTPException(400, str(e))
    new, total = db.add_leads(found, s.niche)
    return {"new": new, "total": total}


@app.get("/api/leads")
def leads(status: Literal["new", "approved", "rejected", "contacted"] | None = None):
    return db.list_leads(status)


@app.patch("/api/leads/{lead_id}")
def patch_lead(lead_id: int, p: LeadPatch):
    if not db.update_lead(lead_id, p.status, p.notes):
        raise HTTPException(404, "lead not found")
    return db.get_lead(lead_id)


@app.delete("/api/leads/{lead_id}")
def del_lead(lead_id: int):
    if not db.delete_lead(lead_id):
        raise HTTPException(404, "lead not found")
    return {"ok": True}


@app.post("/api/leads/{lead_id}/draft")
def generate_draft(lead_id: int, g: GenerateIn):
    lead = db.get_lead(lead_id)
    if not lead:
        raise HTTPException(404, "lead not found")
    profile = Profile(**db.get_setting("profile", {}))
    subject, body = drafts_mod.render(lead, profile.model_dump(), g.channel)
    return {"id": db.add_draft(lead_id, g.channel, body, subject)}


# ---------- rascunhos ----------

@app.get("/api/drafts")
def drafts(status: Literal["pending", "approved", "rejected"] | None = None):
    return db.list_drafts(status)


@app.post("/api/drafts")
def create_draft(d: DraftIn):
    new_id = db.add_draft(d.lead_id, d.channel, d.body, d.subject)
    if new_id is None:
        raise HTTPException(404, "lead not found")
    return {"id": new_id}


@app.patch("/api/drafts/{draft_id}")
def patch_draft(draft_id: int, p: DraftPatch):
    if not db.update_draft(draft_id, p.subject, p.body, p.status):
        raise HTTPException(404, "draft not found")
    return {"ok": True}


@app.delete("/api/drafts/{draft_id}")
def del_draft(draft_id: int):
    if not db.delete_draft(draft_id):
        raise HTTPException(404, "draft not found")
    return {"ok": True}
