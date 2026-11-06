"""Procura e-mails de contato no site da própria empresa (página inicial e páginas de contato).
O Google Places não informa e-mail, então este é o único jeito automático de preencher o campo."""
import ipaddress
import re
import socket
import urllib.request
from urllib.parse import urljoin, urlsplit

CONTACT_PATHS = ("", "/contato", "/contact", "/fale-conosco", "/contacto")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}")
IGNORE_SUFFIX = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".css", ".js")
IGNORE_PARTS = ("sentry", "wixpress", "example.", "seudominio", "email.com", "domain.com", "@2x")
MAX_BYTES = 400_000


def _public_host(host: str) -> bool:
    """Recusa endereços internos (evita usar o painel para sondar a rede local)."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    return all(ipaddress.ip_address(i[4][0]).is_global for i in infos)


def _fetch(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname or not _public_host(parts.hostname):
        return ""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (MeuVendedor)"})
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return r.read(MAX_BYTES).decode("utf-8", "ignore")
    except Exception:
        return ""


def find_email(website: str) -> str:
    """Devolve o melhor e-mail encontrado ou texto vazio."""
    if not website:
        return ""
    base = website if "://" in website else "https://" + website
    domain = (urlsplit(base).hostname or "").removeprefix("www.")
    candidatos: list[str] = []
    for path in CONTACT_PATHS:
        html = _fetch(urljoin(base, path))
        for m in re.findall(r"mailto:([^\"'?>\s]+)", html, flags=re.I) + EMAIL_RE.findall(html):
            e = m.strip().lower().rstrip(".")
            if e.endswith(IGNORE_SUFFIX) or any(x in e for x in IGNORE_PARTS) or not EMAIL_RE.fullmatch(e):
                continue
            if e not in candidatos:
                candidatos.append(e)
        if any(c.endswith("@" + domain) for c in candidatos):
            break
    mesmos = [c for c in candidatos if c.endswith("@" + domain)]
    return (mesmos or candidatos or [""])[0]
