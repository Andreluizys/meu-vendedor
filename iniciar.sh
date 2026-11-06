#!/usr/bin/env sh
# Meu Vendedor: prepara o ambiente na primeira vez e abre o painel.
set -e
cd "$(dirname "$0")"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install -q -r requirements.txt
exec .venv/bin/python -m app
