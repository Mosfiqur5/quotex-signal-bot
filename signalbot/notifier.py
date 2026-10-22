import logging

import requests

logger = logging.getLogger(__name__)
TELEGRAM_API = "https://api.telegram.org"


class Notifier:
    def __init__(self, cfg):
        self.token = cfg.telegram_bot_token
        self.chat_id = cfg.telegram_chat_id
        self.enabled = bool(self.token and self.chat_id)
        if not self.enabled:
            logger.info("Telegram credentials missing; using console-only mode.")

    def send(self, text: str) -> bool:
        print(text, flush=True)
        if not self.enabled:
            return False
        url = f"{TELEGRAM_API}/bot{self.token}/sendMessage"
        try:
            response = requests.post(
                url,
                json={"chat_id": self.chat_id, "text": text},
                timeout=10,
            )
            response.raise_for_status()
        except Exception:
            logger.warning("Telegram delivery failed; message remains in console.")
            return False
        return True
