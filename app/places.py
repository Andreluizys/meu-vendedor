"""Busca de empresas pela API oficial Google Places (New) - Text Search.

Docs: https://developers.google.com/maps/documentation/places/web-service/text-search
Observação de custo: telefone e site fazem a chamada entrar na faixa "Enterprise" (mais cara).
"""
import json
import urllib.error
import urllib.request

URL = "https://places.googleapis.com/v1/places:searchText"
FIELD_MASK = ",".join([
    "places.id", "places.displayName", "places.formattedAddress",
    "places.nationalPhoneNumber", "places.websiteUri", "places.googleMapsUri",
    "places.rating", "places.userRatingCount", "nextPageToken",
])
PAGE_SIZE = 20          # máximo por página da API
HARD_LIMIT = 60         # a API entrega no máximo 60 resultados por busca (3 páginas)


class PlacesError(Exception):
    """Erro legível para mostrar ao usuário."""


def _normalize(p: dict) -> dict:
    return {
        "place_id": p.get("id"),
        "name": (p.get("displayName") or {}).get("text") or "?",
        "address": p.get("formattedAddress", ""),
        "phone": p.get("nationalPhoneNumber", ""),
        "website": p.get("websiteUri", ""),
        "maps_url": p.get("googleMapsUri", ""),
        "rating": p.get("rating"),
        "reviews": p.get("userRatingCount"),
    }


def _post(api_key: str, body: dict) -> dict:
    req = urllib.request.Request(
        URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": FIELD_MASK,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        try:
            msg = json.load(e).get("error", {}).get("message", "")
        except Exception:
            msg = ""
        raise PlacesError(f"Google Places {e.code}: {msg or e.reason}") from e
    except urllib.error.URLError as e:
        raise PlacesError(f"Sem conexão com o Google Places: {e.reason}") from e


def search(api_key: str, query: str, max_results: int = 20, language: str = "pt") -> list[dict]:
    if not api_key:
        raise PlacesError("Chave da API do Google Places não configurada.")
    if not query.strip():
        raise PlacesError("Informe o que buscar.")
    max_results = max(1, min(max_results, HARD_LIMIT))
    found: list[dict] = []
    token = None
    while len(found) < max_results:
        body = {
            "textQuery": query,
            "pageSize": min(PAGE_SIZE, max_results - len(found)),
            "languageCode": language,
        }
        if token:
            body["pageToken"] = token
        data = _post(api_key, body)
        found.extend(_normalize(p) for p in data.get("places", []))
        token = data.get("nextPageToken")
        if not token:
            break
    return found[:max_results]
