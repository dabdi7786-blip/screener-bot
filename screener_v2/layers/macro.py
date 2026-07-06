"""
Layer 5: Macro overlay multiplier (0.70–1.30).
Loaded once per run and shared across all tickers.
"""
import logging
import yfinance as yf

logger = logging.getLogger(__name__)


def get_macro_multiplier() -> tuple[float, dict]:
    """Return (multiplier, data_dict). Falls back to 1.0 on any error."""
    data: dict = {}
    multiplier = 1.0

    try:
        vix_hist = yf.Ticker("^VIX").history(period="5d")
        vix = float(vix_hist["Close"].iloc[-1]) if not vix_hist.empty else None
        data["vix"] = round(vix, 1) if vix else None

        dxy_hist = yf.Ticker("DX-Y.NYB").history(period="30d")
        if not dxy_hist.empty and len(dxy_hist) >= 20:
            dxy_now  = float(dxy_hist["Close"].iloc[-1])
            dxy_20d  = float(dxy_hist["Close"].iloc[-20])
            dxy_chg  = (dxy_now - dxy_20d) / dxy_20d * 100
        else:
            dxy_chg = 0.0
        data["dxy_chg_pct"] = round(dxy_chg, 2)

        tnx_hist = yf.Ticker("^TNX").history(period="5d")
        tnx = float(tnx_hist["Close"].iloc[-1]) if not tnx_hist.empty else None
        data["yield_10y"] = round(tnx, 2) if tnx else None

        # VIX contribution
        if vix is not None:
            if vix < 15:
                multiplier += 0.15
            elif vix < 20:
                multiplier += 0.05
            elif vix < 25:
                pass              # neutral
            elif vix < 30:
                multiplier -= 0.10
            else:
                multiplier -= 0.25

        # DXY contribution (rising dollar = headwind for equities)
        if dxy_chg > 2:
            multiplier -= 0.05

        # 10Y yield contribution
        if tnx is not None and tnx > 5.0:
            multiplier -= 0.05

        multiplier = round(max(0.70, min(1.30, multiplier)), 3)
        logger.info("Macro: VIX=%.1f DXY_chg=%.2f%% 10Y=%.2f multiplier=%.3f",
                    vix or 0, dxy_chg, tnx or 0, multiplier)

    except Exception as e:
        logger.warning("Macro data unavailable (%s) — using multiplier=1.0", e)
        multiplier = 1.0

    data["multiplier"] = multiplier
    return multiplier, data
