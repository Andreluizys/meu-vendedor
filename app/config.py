"""Configuração central. Para renomear o produto, mude só APP_NAME (e o nome da pasta/skill, se quiser)."""
import os
from pathlib import Path

APP_NAME = "Meu Vendedor"
SKILL_ID = "meu-vendedor"

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("MEU_VENDEDOR_DATA", ROOT / "data"))
DB_PATH = DATA_DIR / "meu_vendedor.db"

HOST = "127.0.0.1"  # só a própria máquina acessa o painel
PORT = int(os.environ.get("MEU_VENDEDOR_PORT", "8765"))

LANGUAGES = ("pt", "en", "es")
DEFAULT_LANGUAGE = "pt"
