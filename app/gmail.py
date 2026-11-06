"""Gmail: login com Google (OAuth, só nesta máquina), envio de e-mails aprovados e leitura das respostas.

Escopos: gmail.send (enviar) e gmail.readonly (ver se houve resposta nas conversas que o app mesmo iniciou).
O cliente OAuth ("App para computador") é criado pelo usuário no Google Cloud; id e segredo ficam em data/ (sem criptografia).
"""
import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

from . import config, db

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
SCOPES = "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly"
REDIRECT = f"http://{config.HOST}:{config.PORT}/api/gmail/callback"
_PENDING: dict[str, str] = {}  # state -> code_verifier (PKCE) enquanto o usuário autoriza


class GmailError(Exception):
    """Erro legível para mostrar ao usuário."""


def _http(method: str, url: str, *, json_body=None, form=None, token: str | None = None) -> dict:
    headers = {}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif json_body is not None:
        data = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            err = json.load(e).get("error")
            msg = err.get("message") if isinstance(err, dict) else (err or "")
        except Exception:
            msg = ""
        raise GmailError(f"Google {e.code}: {msg or e.reason}") from e
    except urllib.error.URLError as e:
        raise GmailError(f"Sem conexão com o Google: {e.reason}") from e


# ---------- configuração e login ----------

def client() -> dict:
    saved = db.get_setting("gmail_client", {}) or {}
    return {
        "client_id": os.environ.get("GMAIL_CLIENT_ID") or saved.get("client_id", ""),
        "client_secret": os.environ.get("GMAIL_CLIENT_SECRET") or saved.get("client_secret", ""),
    }


def status() -> dict:
    tok = db.get_setting("gmail_token", {}) or {}
    return {"configured": bool(client()["client_id"] and client()["client_secret"]),
            "connected": bool(tok.get("refresh_token")), "email": tok.get("email", "")}


def auth_url() -> str:
    c = client()
    if not (c["client_id"] and c["client_secret"]):
        raise GmailError("Informe o ID e o segredo do cliente OAuth do Google primeiro.")
    state = secrets.token_urlsafe(16)
    verifier = secrets.token_urlsafe(48)
    _PENDING[state] = verifier
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": c["client_id"], "redirect_uri": REDIRECT, "response_type": "code", "scope": SCOPES,
        "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": challenge, "code_challenge_method": "S256",
    })


def handle_callback(code: str, state: str) -> str:
    verifier = _PENDING.pop(state, None)
    if not verifier:
        raise GmailError("Pedido de login desconhecido ou expirado. Tente conectar de novo.")
    c = client()
    tok = _http("POST", TOKEN_URL, form={
        "code": code, "client_id": c["client_id"], "client_secret": c["client_secret"],
        "redirect_uri": REDIRECT, "grant_type": "authorization_code", "code_verifier": verifier})
    if not tok.get("refresh_token"):
        raise GmailError("O Google não devolveu permissão offline. Remova o acesso do app na conta Google e tente de novo.")
    saved = {"refresh_token": tok["refresh_token"], "access_token": tok["access_token"],
             "expires_at": time.time() + int(tok.get("expires_in", 3000))}
    db.set_setting("gmail_token", saved)
    saved["email"] = _http("GET", f"{API}/profile", token=saved["access_token"]).get("emailAddress", "")
    db.set_setting("gmail_token", saved)
    return saved["email"]


def disconnect() -> None:
    db.set_setting("gmail_token", {})


def _access_token() -> str:
    tok = db.get_setting("gmail_token", {}) or {}
    if not tok.get("refresh_token"):
        raise GmailError("Gmail não conectado.")
    if tok.get("access_token") and tok.get("expires_at", 0) - 60 > time.time():
        return tok["access_token"]
    c = client()
    new = _http("POST", TOKEN_URL, form={
        "client_id": c["client_id"], "client_secret": c["client_secret"],
        "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
    tok.update(access_token=new["access_token"], expires_at=time.time() + int(new.get("expires_in", 3000)))
    db.set_setting("gmail_token", tok)
    return tok["access_token"]


# ---------- envio e respostas ----------

def _clean_header(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())  # barra injeção de cabeçalho


def build_raw(to: str, subject: str, body: str, sender: str = "") -> str:
    msg = EmailMessage()
    msg["To"] = _clean_header(to)
    msg["Subject"] = _clean_header(subject)
    if sender:
        msg["From"] = _clean_header(sender)
    msg.set_content(body)
    return base64.urlsafe_b64encode(msg.as_bytes()).decode()


def send(to: str, subject: str, body: str) -> str:
    """Envia o e-mail e devolve o id da conversa (threadId)."""
    tok = db.get_setting("gmail_token", {}) or {}
    res = _http("POST", f"{API}/messages/send", token=_access_token(),
                json_body={"raw": build_raw(to, subject, body, tok.get("email", ""))})
    return res.get("threadId", "")


def thread_reply(thread_id: str, my_email: str) -> str | None:
    """Texto da primeira resposta de outra pessoa na conversa, ou None se ninguém respondeu."""
    data = _http("GET", f"{API}/threads/{urllib.parse.quote(thread_id)}?format=metadata&metadataHeaders=From",
                 token=_access_token())
    for m in data.get("messages", []):
        headers = {h["name"].lower(): h["value"] for h in m.get("payload", {}).get("headers", [])}
        remetente = headers.get("from", "").lower()
        if "SENT" in m.get("labelIds", []) or (my_email and my_email.lower() in remetente):
            continue
        return m.get("snippet", "") or "(sem texto)"
    return None


def check_replies() -> dict:
    """Confere, nas conversas iniciadas pelo app, quem respondeu e registra no painel."""
    my_email = (db.get_setting("gmail_token", {}) or {}).get("email", "")
    checked = replies = 0
    for d in db.pending_threads():
        checked += 1
        texto = thread_reply(d["thread_id"], my_email)
        if texto is not None:
            db.mark_replied(d["id"], texto[:2000])
            replies += 1
    return {"checked": checked, "replies": replies}
