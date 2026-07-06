"""
Fetches raw financial data from yfinance and populates a CompanyData object.
All external calls wrapped in try/except — screener never crashes on bad data.
"""
import logging
import math

import pandas as pd
import yfinance as yf

from config import HISTORY_PERIOD, SECTOR_MAP
from models import CompanyData

logger = logging.getLogger(__name__)


def _safe(val, default=0.0):
    if val is None:
        return default
    try:
        f = float(val)
        return default if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return default


def fetch(ticker: str) -> tuple[CompanyData | None, pd.DataFrame | None]:
    """
    Return (CompanyData, history_df) or (None, None) on failure.
    history_df has columns Close, Volume indexed by Date.
    """
    try:
        tk   = yf.Ticker(ticker)
        info = tk.info or {}
        if not info or info.get("regularMarketPrice") is None:
            # try fast_info as fallback
            try:
                price = tk.fast_info.last_price
            except Exception:
                price = None
            if price is None:
                logger.warning("%s: yfinance returned empty info — skipping", ticker)
                return None, None
        else:
            price = _safe(info.get("currentPrice") or info.get("regularMarketPrice"))

        hist = tk.history(period=HISTORY_PERIOD, auto_adjust=True)
        if hist.empty:
            logger.warning("%s: empty price history — skipping", ticker)
            return None, None

        revenue      = _safe(info.get("totalRevenue"))
        net_income   = _safe(info.get("netIncomeToCommon"))
        free_cashflow = _safe(info.get("freeCashflow"))
        total_debt   = _safe(info.get("totalDebt"))
        ebitda       = _safe(info.get("ebitda"))

        gross_margin = _safe(info.get("grossMargins"))
        op_margin    = _safe(info.get("operatingMargins"))
        rev_growth   = _safe(info.get("revenueGrowth"))
        eps_growth   = _safe(info.get("earningsGrowth"))

        fcf_margin   = free_cashflow / revenue if revenue > 0 else 0.0
        fcf_conv     = free_cashflow / net_income if net_income and abs(net_income) > 1e4 else 0.0
        debt_ebitda  = total_debt / ebitda if ebitda and ebitda > 0 else 0.0

        shares = _safe(info.get("sharesOutstanding"))
        mktcap = price * shares if price and shares else _safe(info.get("marketCap"))

        short_pct = _safe(info.get("shortPercentOfFloat")) * 100

        c = CompanyData(
            ticker       = ticker,
            name         = info.get("shortName") or info.get("longName") or ticker,
            sector       = SECTOR_MAP.get(ticker, _map_sector(info.get("sector", ""))),
            price        = round(price, 2),
            market_cap   = round(mktcap / 1e9, 2) if mktcap else 0.0,
            revenue      = revenue,
            net_income   = net_income,
            free_cashflow = free_cashflow,
            rev_growth   = rev_growth,
            eps_growth   = eps_growth,
            gross_margin = gross_margin,
            op_margin    = op_margin,
            fcf_margin   = fcf_margin,
            fcf_conversion = fcf_conv,
            debt_ebitda  = round(debt_ebitda, 2),
            roe          = _safe(info.get("returnOnEquity")),
            forward_pe   = info.get("forwardPE"),
            peg          = info.get("pegRatio"),
            trailing_pe  = info.get("trailingPE"),
            short_pct    = round(short_pct, 2),
        )
        c.rule_of_40 = round(rev_growth * 100 + fcf_margin * 100, 1)

        logger.debug("%s fetched: price=%.2f rev_g=%.1f%% eps_g=%.1f%% gm=%.1f%%",
                     ticker, price, rev_growth*100, eps_growth*100, gross_margin*100)
        return c, hist

    except Exception as e:
        logger.error("%s fetch failed: %s", ticker, e)
        c = CompanyData(ticker=ticker, error=str(e))
        return c, None


def _map_sector(yf_sector: str) -> str:
    """Map yfinance sector strings to our internal sector names."""
    s = (yf_sector or "").lower()
    if "software" in s or "internet" in s:
        return "saas"
    if "semiconductor" in s:
        return "semiconductor"
    if "drug" in s or "biotech" in s or "health" in s or "pharma" in s:
        return "pharma"
    if "financial" in s or "bank" in s or "insurance" in s or "credit" in s:
        return "financials"
    if "communication" in s or "media" in s:
        return "platform"
    return "unknown"
