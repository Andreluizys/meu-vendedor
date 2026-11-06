# Meu Vendedor
Skill do Claude que funciona como um funcionário/vendedor. Genérica, para qualquer pessoa usar, e vai ser publicada no GitHub.

## Como funciona
- A função do funcionário se adapta ao que o usuário definir, com perguntas e respostas que vão se refinando até entender a finalidade.
- Prospecção B2B: o usuário define o nicho (ex.: moda) e a skill busca empresas no Google e no Google Maps.
- Google Maps: oferecer as duas opções (API Places oficial e raspagem), indicando qual é mais assertiva.
- Escreve e-mails, mensagens e respostas de WhatsApp e mostra tudo num painel.
- O usuário pode aprovar cada mensagem antes do envio ou definir regras para a skill agir sozinha.

## Painel
- Roda localmente, na máquina do usuário.
- Tem área de configurações de envio: limite diário, intervalo aleatório, dias e horários permitidos, modo manual ou automático, e simulação de digitação ("digitando..." por 4 a 5 segundos antes de enviar).

## Integrações
- WhatsApp: conexão por QR Code (gratuita) como padrão, com limite diário; API oficial como opção para escalar.
- E-mail: login com Google (Gmail).

## Preferências do André
- Antes de executar qualquer tarefa técnica, faça perguntas para esclarecer.
- Sempre entregar arquivos completos, nunca implementações parciais.
- PC com Windows, 8 GB de RAM e Python instalado.

## Decisões (06/11/2026)
- 1ª entrega: painel + prospecção (entrevista que define a função, busca de empresas, rascunhos para aprovação). Sem envio ainda.
- Tecnologia: só Python (FastAPI + página HTML simples). WhatsApp por QR Code (exige Node) fica para depois.
- Google Maps: API Places oficial como padrão; raspagem só como opção extra, com aviso de risco.
- Distribuição: skill do Claude Code (SKILL.md + scripts) + painel local aberto no navegador.
