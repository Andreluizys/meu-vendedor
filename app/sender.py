"""Fila de envio pelo Gmail.

Dois modos, escolhidos pelo usuário em Configurações:
- manual: o usuário revisa, aprova tudo de uma vez e clica em "Enviar aprovadas". O programa só envia
  as aprovadas, respeitando limite diário, dias, horário e intervalo aleatório.
- auto: o programa envia sozinho os e-mails que estiverem prontos, aprovados ou não, com as mesmas regras.

O envio roda numa thread de fundo enquanto o painel estiver aberto (python -m app).
"""
import random
import threading
from datetime import timedelta

from . import db, gmail, limits

TICK_S = 3


class Sender:
    def __init__(self, settings_fn=None, send_fn=None, now_fn=None, rand=random.uniform):
        self.settings_fn = settings_fn           # devolve o dict das configurações de envio
        self.send_fn = send_fn or gmail.send
        self.now_fn = now_fn or limits.now_local
        self.rand = rand
        self.queue_on = False                    # modo manual: usuário mandou enviar as aprovadas
        self.error = ""
        self.reason = ""
        self.next_at = None
        self._lock = threading.Lock()
        self._thread = None

    # ---------- controle ----------

    def start_queue(self) -> None:
        if not gmail.status()["connected"]:
            raise gmail.GmailError("Conecte o Gmail em Configurações antes de enviar.")
        with self._lock:
            self.error = ""
            self.queue_on = True

    def stop_queue(self) -> None:
        with self._lock:
            self.queue_on = False

    def resume(self) -> None:
        with self._lock:
            self.error = ""

    # ---------- um passo ----------

    def step(self) -> str:
        """Tenta enviar UM e-mail. Devolve: off, idle, waiting, error ou sent."""
        with self._lock:
            s = self.settings_fn()
            auto = s["mode"] == "auto"
            if not (auto or self.queue_on):
                return "off"
            if self.error:
                return "error"
            d = db.next_email_to_send(include_pending=auto)
            if not d:
                if not auto:
                    self.queue_on = False        # acabou a fila do envio manual
                self.reason, self.next_at = "", None
                return "idle"
            now = self.now_fn()
            if self.next_at and now < self.next_at:
                self.reason = "Aguardando o intervalo entre envios."
                return "waiting"
            motivo = limits.check(s, db.sent_times("email"), now)
            if motivo:
                self.reason = motivo
                return "waiting"
            if not gmail.status()["connected"]:
                self.reason = "Conecte o Gmail em Configurações."
                return "waiting"
            try:
                if d["status"] != "approved":    # no modo automático, o envio vale como aprovação
                    db.update_draft(d["id"], status="approved")
                thread = self.send_fn(d["lead_email"].strip(), d["subject"] or "", d["body"])
            except Exception as e:  # noqa: BLE001 - qualquer falha pausa o envio e aparece no painel
                self.error = f"{d['lead_name']}: {e}"
                self.queue_on = False
                return "error"
            db.set_thread(d["id"], thread)
            db.mark_sent(d["id"])
            self.next_at = now + timedelta(seconds=self.rand(s["interval_min_s"], s["interval_max_s"]))
            self.reason = ""
            return "sent"

    def status(self) -> dict:
        s = self.settings_fn()
        auto = s["mode"] == "auto"
        now = self.now_fn()
        hoje = sum(1 for t in db.sent_times("email") if _same_day(t, now))
        return {
            "mode": s["mode"],
            "active": auto or self.queue_on,
            "queue_on": self.queue_on,
            "remaining": db.count_email_to_send(include_pending=auto),
            "sent_today": hoje,
            "daily_limit": s["daily_limit"],
            "reason": self.reason,
            "error": self.error,
        }

    # ---------- thread de fundo ----------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        stop = threading.Event()

        def loop():
            while not stop.wait(TICK_S):
                try:
                    self.step()
                except Exception:  # noqa: BLE001 - a thread nunca pode morrer
                    pass

        self._thread = threading.Thread(target=loop, name="meu-vendedor-envio", daemon=True)
        self._thread.start()


def _same_day(iso: str, now) -> bool:
    from datetime import datetime
    return datetime.fromisoformat(iso).astimezone(now.tzinfo).date() == now.date()


sender = Sender()
