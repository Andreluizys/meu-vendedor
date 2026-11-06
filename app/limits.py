"""Regras de envio (as mesmas configuradas na aba Configurações). Função pura, fácil de testar."""
from datetime import datetime, timezone


def check(settings: dict, sent_iso: list[str], now: datetime) -> str | None:
    """Devolve o motivo pelo qual NÃO pode enviar agora, ou None se pode. `now` deve ter fuso (hora local)."""
    if not settings["days"][now.weekday()]:
        return "Hoje não é um dia permitido para envio (veja Configurações)."
    hora = now.strftime("%H:%M")
    if not (settings["hour_start"] <= hora < settings["hour_end"]):
        return f"Fora do horário permitido ({settings['hour_start']} às {settings['hour_end']})."
    enviados = [datetime.fromisoformat(s).astimezone(now.tzinfo) for s in sent_iso]
    hoje = sum(1 for e in enviados if e.date() == now.date())
    if hoje >= settings["daily_limit"]:
        return f"Limite diário de {settings['daily_limit']} mensagens atingido."
    if enviados:
        espera = settings["interval_min_s"] - (now - max(enviados)).total_seconds()
        if espera > 0:
            return f"Aguarde {int(espera) + 1} segundos desde o último envio."
    return None


def now_local() -> datetime:
    return datetime.now(timezone.utc).astimezone()
