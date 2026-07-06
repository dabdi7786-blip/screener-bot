"""
Sends the HTML dashboard as a Telegram document.
Uses TELEGRAM_TOKEN and TELEGRAM_CHAT_ID from .env (same as screener_bot).
"""
import logging
import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env")

TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

logger = logging.getLogger(__name__)


def send_dashboard(html_path: str, companies: list) -> bool:
    """
    Send html_path as document with a caption summary.
    Returns True on success.
    """
    if not TOKEN or not CHAT_ID:
        logger.error("TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set in .env")
        return False

    caption = _build_caption(companies)
    url     = f"https://api.telegram.org/bot{TOKEN}/sendDocument"

    try:
        with open(html_path, "rb") as f:
            resp = requests.post(
                url,
                data={"chat_id": CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"document": (Path(html_path).name, f, "text/html")},
                timeout=30,
            )
        resp.raise_for_status()
        logger.info("Telegram: dashboard sent (%s)", Path(html_path).name)
        return True
    except Exception as e:
        logger.error("Telegram send failed: %s", e)
        return False


def _build_caption(companies: list) -> str:
    from datetime import date
    from models import CompanyData

    today = date.today().strftime("%d.%m.%Y")
    valid = [c for c in companies if not c.error]
    valid.sort(key=lambda c: c.final_score, reverse=True)

    lines = [f"📊 <b>Screener v2 — {today}</b>", f"Тикеров проанализировано: {len(valid)}\n"]

    EMOJI = {"Strong Buy": "🟢", "Buy+Watch": "🔵", "Watch": "🟡", "Wait": "🟣", "Skip": "🔴"}

    for c in valid[:10]:
        em = EMOJI.get(c.rating, "⚪")
        lines.append(f"{em} <b>{c.ticker}</b> {c.final_score:.0f}/95 — {c.rating}")

    if len(valid) > 10:
        lines.append(f"  …ещё {len(valid)-10} в файле")

    lines.append("\n⬇️ Открой файл локально двойным кликом")
    return "\n".join(lines)
