"""
Layer 4: Catalyst tracker (0–10 pts).
Earnings proximity, EPS beat rate, analyst upgrades.
"""
import logging
from datetime import date
from typing import Optional

import yfinance as yf

from models import CompanyData

logger = logging.getLogger(__name__)


def _days_to_next_earnings(ticker_obj) -> Optional[int]:
    try:
        cal = ticker_obj.calendar
        if cal is None:
            return None
        # calendar can be dict or DataFrame depending on yfinance version
        if hasattr(cal, "get"):
            earn = cal.get("Earnings Date")
        else:
            earn = None
        if earn is None:
            return None
        if hasattr(earn, "__iter__") and not isinstance(earn, str):
            earn = list(earn)[0]
        earn_date = getattr(earn, "date", lambda: earn)()
        delta = (earn_date - date.today()).days
        return int(delta)
    except Exception:
        return None


def _eps_beat_stats(ticker_obj) -> tuple[int, float]:
    """Return (beats_in_4q, avg_surprise_pct)."""
    try:
        hist = ticker_obj.earnings_history
        if hist is None or hist.empty:
            return 0, 0.0
        recent = hist.head(4)
        beats  = int((recent.get("surprisePercent", recent.get("surprise", 0)) > 0).sum())
        avg_s  = float(recent.get("surprisePercent", recent.get("surprise", 0)).mean())
        return beats, round(avg_s * 100 if abs(avg_s) < 1 else avg_s, 1)
    except Exception:
        return 0, 0.0


def _recent_upgrades(ticker_obj, days: int = 14) -> tuple[int, int]:
    """Return (upgrades, downgrades) in last N days."""
    try:
        ud = ticker_obj.upgrades_downgrades
        if ud is None or ud.empty:
            return 0, 0
        cutoff = date.today().strftime("%Y-%m-%d")
        from datetime import timedelta
        from datetime import date as _d
        cutoff_dt = (_d.today() - timedelta(days=days)).isoformat()
        # index is DatetimeIndex
        recent = ud[ud.index >= cutoff_dt]
        if recent.empty:
            return 0, 0
        grades = recent.get("ToGrade", recent.get("Action", []))
        ups   = int(sum(1 for g in grades if str(g).lower() in
                        ("buy", "outperform", "overweight", "strong buy", "upgrade")))
        downs = int(sum(1 for g in grades if str(g).lower() in
                        ("sell", "underperform", "underweight", "downgrade")))
        return ups, downs
    except Exception:
        return 0, 0


def analyze(company: CompanyData) -> tuple[float, dict]:
    data: dict = {}
    s = 0.0

    try:
        tk = yf.Ticker(company.ticker)
    except Exception as e:
        logger.warning("%s: yfinance Ticker init failed: %s", company.ticker, e)
        return 0.0, {"error": str(e)}

    # Earnings proximity
    dte = _days_to_next_earnings(tk)
    data["days_to_earnings"] = dte
    company.days_to_earnings = dte
    if dte is not None and 5 <= dte <= 14:
        s += 3   # imminent earnings = catalyst

    # EPS beat rate
    beats, avg_surprise = _eps_beat_stats(tk)
    data["eps_beat_quarters"] = beats
    data["eps_surprise_avg"]  = avg_surprise
    company.eps_beat_quarters = beats
    company.eps_surprise_avg  = avg_surprise
    if beats >= 4:
        s += 4
    elif beats >= 3:
        s += 2

    # EPS surprise magnitude
    if avg_surprise > 10:
        s += 3
    elif avg_surprise > 5:
        s += 1

    # Analyst upgrades
    ups, downs = _recent_upgrades(tk)
    data["recent_upgrades"]   = ups
    data["recent_downgrades"] = downs
    company.recent_upgrades   = ups
    company.recent_downgrades = downs
    if ups > downs * 2 and ups >= 2:
        s += 2

    score = round(max(0.0, min(10.0, s)), 1)
    data["score"] = score
    logger.debug("%s catalyst_score=%.1f (dte=%s beats=%d surprise=%.1f ups=%d downs=%d)",
                 company.ticker, score, dte, beats, avg_surprise, ups, downs)
    return score, data
