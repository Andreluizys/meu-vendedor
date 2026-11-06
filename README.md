# Meu Vendedor

Skill do Claude que funciona como um funcionário/vendedor virtual para prospecção B2B. Você conversa, ela descobre a função do funcionário, busca empresas do seu nicho no Google Maps e escreve as mensagens. **Você aprova tudo num painel local antes de qualquer envio.**

Painel e skill em **português, inglês e espanhol**.

## Status (v0.1)
Pronto: painel local, entrevista pela skill, busca no Google Maps (API Places oficial), rascunhos de e-mail e WhatsApp para aprovar, configurações de envio (guardadas).
**Ainda não existe:** envio de e-mail (Gmail), WhatsApp por QR Code, modo automático, raspagem do Maps. Nada é enviado nesta versão.

## Instalação (Windows)
1. Tenha o Python 3.10+ instalado.
2. Dê dois cliques em `iniciar.bat`. Na primeira vez ele cria o ambiente e instala o necessário. O painel abre em `http://127.0.0.1:8765/`.

Linux/Mac: `./iniciar.sh`.

## Usar com o Claude Code
Copie esta pasta para `~/.claude/skills/meu-vendedor` (ou abra o Claude Code dentro dela) e peça, por exemplo: "quero prospectar lojas de moda em Campinas". A skill (`SKILL.md`) conduz a entrevista, busca as empresas, escreve as mensagens e as deixa no painel.

## Chave do Google Places
Na aba **Configurações** do painel (ou na variável `GOOGLE_PLACES_API_KEY`). Crie a chave no Google Cloud ativando **Places API (New)**. Há cota gratuita mensal e depois cobrança por uso; telefone e site entram na faixa mais cara. A chave fica só no seu computador, sem criptografia, em `data/meu_vendedor.db`.

## Comandos
```
python scripts/mv.py profile-get
python scripts/mv.py search --niche "loja de moda" --location "Campinas, SP" --max 20
python scripts/mv.py leads --status new
python scripts/mv.py draft-add --lead-id 3 --channel email --subject "Oi" --body-file msg.txt
python scripts/mv.py drafts --status pending
```

## Segurança e privacidade
- O painel só responde em `127.0.0.1` e recusa requisições de outros sites abertos no navegador.
- Os dados ficam em `data/` (SQLite), fora do Git.
- Prospectar por e-mail e WhatsApp tem regras (LGPD/GDPR, anti-spam, termos do WhatsApp). Use com poucos contatos bem escolhidos e respeite pedidos de descadastro.

## Testes
```
.venv/Scripts/python -m pip install -r requirements-dev.txt
.venv/Scripts/python -m unittest discover -s tests
```

## Trocar o nome do produto
Mude `APP_NAME` e `SKILL_ID` em `app/config.py`, o campo `name` do `SKILL.md` e o nome da pasta.

## Licença
A definir antes da publicação.
