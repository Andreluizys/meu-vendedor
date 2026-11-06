"""Rascunhos por modelo (sem IA). A skill do Claude escreve versões personalizadas via scripts/mv.py;
estes modelos são o plano B do painel (botão "Gerar rascunho")."""

TEMPLATES = {
    "pt": {
        "email_subject": "{company}: uma ideia para a {name}",
        "email_body": (
            "Olá, equipe da {name}!\n\n"
            "Aqui é {owner} da {company}. {offer}\n\n"
            "{cta}\n\n"
            "Um abraço,\n{owner}\n\n"
            "Se preferir não receber mais mensagens, é só responder \"sair\"."
        ),
        "whatsapp_body": "Olá! Aqui é {owner} da {company}. {offer} {cta}",
        "cta_default": "Posso te mandar mais detalhes?",
    },
    "en": {
        "email_subject": "{company}: an idea for {name}",
        "email_body": (
            "Hi, {name} team!\n\n"
            "This is {owner} from {company}. {offer}\n\n"
            "{cta}\n\n"
            "Best,\n{owner}\n\n"
            "If you'd rather not hear from us again, just reply \"stop\"."
        ),
        "whatsapp_body": "Hi! This is {owner} from {company}. {offer} {cta}",
        "cta_default": "Can I send you more details?",
    },
    "es": {
        "email_subject": "{company}: una idea para {name}",
        "email_body": (
            "¡Hola, equipo de {name}!\n\n"
            "Soy {owner} de {company}. {offer}\n\n"
            "{cta}\n\n"
            "Un saludo,\n{owner}\n\n"
            "Si prefieres no recibir más mensajes, responde \"salir\"."
        ),
        "whatsapp_body": "¡Hola! Soy {owner} de {company}. {offer} {cta}",
        "cta_default": "¿Puedo enviarte más detalles?",
    },
}


class _Seguro(dict):
    """Campo faltante vira texto vazio em vez de quebrar a formatação."""
    def __missing__(self, key):
        return ""


def render(lead: dict, profile: dict, channel: str) -> tuple[str, str]:
    """Devolve (assunto, corpo). Assunto é vazio no WhatsApp."""
    lang = profile.get("language") if profile.get("language") in TEMPLATES else "pt"
    t = TEMPLATES[lang]
    dados = _Seguro(
        name=lead.get("name", ""),
        owner=profile.get("owner_name", ""),
        company=profile.get("company", ""),
        offer=profile.get("offer", ""),
        cta=profile.get("cta") or t["cta_default"],
    )
    if channel == "email":
        return t["email_subject"].format_map(dados), t["email_body"].format_map(dados)
    return "", t["whatsapp_body"].format_map(dados)
