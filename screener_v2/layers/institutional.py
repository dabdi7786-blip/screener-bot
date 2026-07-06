"""
Layer 3: Institutional footprint (0–15 pts).
SEC EDGAR Form 4 (insider buy/sell) + short interest.
Neutral fallback (7.5) when EDGAR is unavailable.
"""
import logging
import time
import requests

from config import EDGAR_USER_AGENT, SLEEP_EDGAR
from models import CompanyData

logger = logging.getLogger(__name__)

EDGAR_URL = "https://efts.sec.gov/LATEST/search-index"
NEUTRAL   = 7.5


def _fetch_edgar_insiders(ticker: str) -> tuple[int, int]:
    """Return (buy_count, sell_count) from EDGAR Form 4 last 30 days."""
    try:
        params = {
            "q":         f'"{ticker}"',
            "forms":     "4",
            "dateRange": "custom",
            "startdt":   _days_ago(30),
        }
        headers = {"User-Agent": EDGAR_USER_AGENT}
        resp = requests.get(EDGAR_URL, params=params, headers=headers, timeout=10)
        if resp.status_code == 429:
            logger.warning("EDGAR rate-limited for %s — sleeping 60s", ticker)
            time.sleep(60)
            resp = requests.get(EDGAR_URL, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        hits = resp.json().get("hits", {}).get("hits", [])
        buys = sells = 0
        for hit in hits:
            src = hit.get("_source", {})
            # Form 4 code: P=purchase, S=sale, G=gift, etc.
            code = src.get("transaction_code", "")
            if code == "P":
                buys += 1
            elif code == "S":
                sells += 1
        time.sleep(SLEEP_EDGAR)
        return buys, sells
    except Exception as e:
        logger.warning("EDGAR unavailable for %s: %s", ticker, e)
        return 0, 0


def _days_ago(n: int) -> str:
    from datetime import date, timedelta
    return (date.today() - timedelta(days=n)).isoformat()


def analyze(company: CompanyData) -> tuple[float, dict]:
    data: dict = {}

    # Insider data from EDGAR
    buys, sells = _fetch_edgar_insiders(company.ticker)
    data["insider_buy"]  = buys
    data["insider_sell"] = sells

    if buys == 0 and sells == 0:
        # EDGAR returned nothing — could be unavailable or no activity
        inst_score = NEUTRAL
        data["note"] = "no_edgar_data_neutral"
    else:
        inst_score = _score_insiders(buys, sells)

    # Short interest adjustment
    short = company.short_pct
    data["short_pct"] = short
    if short < 2:
        inst_score += 1
    elif short > 15:
        inst_score -= 6
    elif short > 10:
        inst_score -= 2

    score = round(max(0.0, min(15.0, inst_score)), 1)
    data["score"] = score
    logger.debug("%s inst_score=%.1f (buys=%d sells=%d short=%.1f%%)",
                 company.ticker, score, buys, sells, short)
    return score, data


def _score_insiders(buys: int, sells: int) -> float:
    if buys > sells * 2 and buys >= 2:
        return 14.0   # strong insider buying
    if buys > sells:
        return 10.0   # net buying
    if buys == sells:
        return 7.5    # balanced — neutral
    if sells > buys * 2 and sells >= 2:
        return 3.0    # heavy selling
    return 6.0        # net selling, mild
