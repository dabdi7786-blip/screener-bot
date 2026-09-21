"""
Telegram delivery (spec sections 15, 17-18). Independent implementation
of the same tg_send shape already used by screener_bot.py/bot_server.py
-- duplicated deliberately rather than imported, to avoid coupling this
job to the screener's ~900-line module (see docs/overnight_news_brief_audit.md
section 1). Retries with exponential backoff; a final failure raises so
the workflow fails loudly (spec: "Do NOT silently succeed"). Never logs
the token.
"""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger("news_brief.telegram")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
MAX_RETRIES = 5
BACKOFF_SCHEDULE = (2, 4, 8, 16, 16)  # seconds, capped at 16 per spec section 17


class TelegramSendError(Exception):
    pass


def send_message(text: str, token: str, chat_id: str, session: requests.Session | None = None) -> None:
    if not token or not chat_id:
        raise TelegramSendError("TELEGRAM_TOKEN/TELEGRAM_CHAT_ID not configured")
    session = session or requests.Session()
    url = TELEGRAM_API.format(token=token)

    last_error = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.post(url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                            "disable_web_page_preview": True}, timeout=15)
            if resp.ok:
                return
            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"

        log.warning("Telegram send attempt %d/%d failed: %s", attempt, MAX_RETRIES, last_error)
        if attempt < MAX_RETRIES:
            time.sleep(BACKOFF_SCHEDULE[min(attempt - 1, len(BACKOFF_SCHEDULE) - 1)])

    raise TelegramSendError(f"Telegram send failed after {MAX_RETRIES} attempts: {last_error}")


def send_messages(messages: list[str], token: str, chat_id: str, session: requests.Session | None = None) -> None:
    """Sends each message in order. Raises on the first unrecoverable
    failure -- a partially-sent briefing still fails the workflow
    loudly rather than reporting success."""
    session = session or requests.Session()
    for msg in messages:
        send_message(msg, token, chat_id, session=session)
