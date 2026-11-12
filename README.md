# Meu Vendedor

Skill do Claude que funciona como um funcionário/vendedor virtual para prospecção B2B. Você conversa, ela descobre a função do funcionário, busca empresas do seu nicho no Google Maps e escreve as mensagens. **Você aprova tudo num painel local antes de qualquer envio.**

Painel e skill em **português, inglês e espanhol**.

## Status (v1.0)
Pronto: painel local, entrevista pela skill, **7 funções pré-definidas de nível sênior** (aba Função), busca no Google Maps (API Places oficial), importação dos Dados Abertos do CNPJ, busca de e-mail no site da empresa, rascunhos de e-mail e WhatsApp para aprovar, **envio pelo Gmail com leitura das respostas**, contadores de prospectados/enviados/respondidos e configurações de envio (limite diário, intervalo, dias e horários).

**Dois modos de envio (você escolhe em Configurações):**
- **Manual:** o vendedor prepara os e-mails, você revisa, clica em "Aprovar todas as pendentes" e depois em "Enviar aprovadas". Só as aprovadas saem.
- **Automático:** se você confia no vendedor, ele envia sozinho os e-mails prontos, com ou sem a sua aprovação.

Nos dois modos valem o limite diário, o intervalo aleatório entre envios, os dias e os horários permitidos. O envio roda enquanto o painel estiver aberto. No modo automático você é responsável pelo que for enviado (LGPD, regras anti-spam).

**Fica para depois:** WhatsApp por QR Code (aparece no painel como "em breve", com o aviso de risco de banimento do número). Não há raspagem do Google Maps, de propósito: vai contra os termos do Google.

## Instalação (Windows)
1. Tenha o Python 3.10+ instalado.
2. Dê dois cliques em `iniciar.bat`. Na primeira vez ele cria o ambiente e instala o necessário. O painel abre em `http://127.0.0.1:8765/`.

Linux/Mac: `./iniciar.sh`.

## Usar com o Claude Code
Copie esta pasta para `~/.claude/skills/meu-vendedor` (ou abra o Claude Code dentro dela) e peça, por exemplo: "quero prospectar lojas de moda em Campinas". A skill (`SKILL.md`) conduz a entrevista, busca as empresas, escreve as mensagens e as deixa no painel.

## Funções
Na aba **Função** você escolhe em qual papel o funcionário trabalha hoje: Arquiteto de Marketing, Vendedor, Prospecção por E-mail, WhatsApp, Copywriter, Designer ou Social Media. A skill lê o guia em `roles/<id>.md` e passa a agir naquela função. Para criar outra, adicione um `.md` em `roles/` e uma entrada em `roles/index.json`.

## Empresas pela Receita Federal (CNPJ)
Baixe os arquivos **Estabelecimentos** do portal de dados abertos do CNPJ, coloque em `data/cnpj/` e use a aba Buscar empresas (ou `python scripts/mv.py cnpj-import --niche manicure --uf SP`). O ramo vira código CNAE (a tabela é aproximada; aceita também o CNAE de 7 dígitos). O e-mail do cadastro costuma ser do contador. Respeite a LGPD e os pedidos de descadastro.

## Gmail (enviar e ler respostas)
1. No Google Cloud, ative a **Gmail API**, configure a tela de permissão e crie um **ID do cliente OAuth do tipo App para computador**. Adicione como URI de redirecionamento `http://127.0.0.1:8765/api/gmail/callback`. Em modo de teste, adicione seu e-mail como usuário de teste.
2. No painel, aba **Configurações > Gmail**: cole o ID e o segredo, salve e clique em **Conectar ao Gmail**.
3. Em **Mensagens**, aprove um rascunho de e-mail e clique em **Enviar pelo Gmail**. O envio respeita dias, horário, limite diário e intervalo mínimo das configurações.
4. **Verificar respostas** lê, nas conversas que o app iniciou, quem respondeu e marca no painel.
Permissões pedidas: enviar e ler e-mails (`gmail.send`, `gmail.readonly`). O app só olha as conversas que ele mesmo começou. As credenciais ficam em `data/`, sem criptografia.

## Contadores
"Prospectados" conta e-mails encontrados e, no WhatsApp, só números de celular (telefone fixo não recebe WhatsApp). "Enviadas" e "respondidas" dos e-mails pelo Gmail são registradas sozinhas. As de WhatsApp você marca nas Mensagens.

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
MIT. Veja o arquivo `LICENSE`. Cada pessoa usa com as próprias chaves e é responsável pelo que envia.
