"""Inicia o painel local:  python -m app"""
import threading
import webbrowser

import uvicorn

from . import config
from .sender import sender


def main() -> None:
    url = f"http://{config.HOST}:{config.PORT}/"
    print(f"{config.APP_NAME}: painel em {url}  (Ctrl+C para parar)")
    sender.start()  # envio em segundo plano (modo manual em lote ou automático)
    threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run("app.main:app", host=config.HOST, port=config.PORT, log_level="warning")


if __name__ == "__main__":
    main()
