"""
Technical analysis layer (0–20 pts).
RSI, MACD, EMA crossover, RS vs sector ETF, volume ratio.
"""
import logging
import numpy as np
import pandas as pd
import yfinance as yf

from config import SECTOR_ETF_MAP, MIN_BARS_TECHNICAL
from models import CompanyData

logger = logging.getLogger(__name__)

NEUTRAL_SCORE = 10.0


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _compute_rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    rsi   = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else 50.0


def _compute_macd(close: pd.Series) -> str:
    exp12 = _ema(close, 12)
    exp26 = _ema(close, 26)
    macd  = exp12 - exp26
    signal = _ema(macd, 9)
    hist   = macd - signal
    if hist.iloc[-1] > 0 and hist.iloc[-2] > 0:
        return "bullish"
    if hist.iloc[-1] < 0 and hist.iloc[-2] < 0:
        return "bearish"
    return "neutral"


def _compute_emas(close: pd.Series) -> tuple[float, float, float]:
    return (
        float(_ema(close, 9).iloc[-1]),
        float(_ema(close, 21).iloc[-1]),
        float(_ema(close, 50).iloc[-1]),
    )


def _compute_trend(price: float, ema9: float, ema21: float, ema50: float) -> str:
    if price > ema9 > ema21 > ema50:
        return "up"
    if price < ema9 < ema21 < ema50:
        return "down"
    return "neutral"


def _compute_rs_vs_etf(ticker: str, etf: str, period: str) -> float:
    """% outperformance of ticker vs ETF over the period."""
    try:
        data = yf.download([ticker, etf], period=period, progress=False, auto_adjust=True)
        closes = data["Close"]
        if closes.empty or ticker not in closes or etf not in closes:
            return 0.0
        stock_ret = (closes[ticker].iloc[-1] / closes[ticker].dropna().iloc[0] - 1) * 100
        etf_ret   = (closes[etf].iloc[-1]   / closes[etf].dropna().iloc[0]   - 1) * 100
        return round(float(stock_ret - etf_ret), 1)
    except Exception:
        return 0.0


def analyze(company: CompanyData, hist: pd.DataFrame, period: str = "6mo") -> tuple[float, dict]:
    """
    Returns (tech_score 0-20, data_dict).
    hist: price history DataFrame from yfinance with 'Close', 'Volume' columns.
    """
    data: dict = {}

    if hist is None or len(hist) < MIN_BARS_TECHNICAL:
        logger.warning("%s: insufficient price history (%d bars) — using neutral tech score",
                       company.ticker, len(hist) if hist is not None else 0)
        return NEUTRAL_SCORE, {"note": "insufficient_history"}

    close  = hist["Close"].dropna()
    volume = hist["Volume"].dropna()

    rsi    = _compute_rsi(close)
    macd   = _compute_macd(close)
    ema9, ema21, ema50 = _compute_emas(close)
    price  = float(close.iloc[-1])
    trend  = _compute_trend(price, ema9, ema21, ema50)

    vol_ratio = 1.0
    if len(volume) >= 20:
        vol_ratio = float(volume.iloc[-1] / volume.iloc[-20:].mean())

    etf = SECTOR_ETF_MAP.get(company.sector, "SPY")
    rs_vs_etf = _compute_rs_vs_etf(company.ticker, etf, period)

    data.update({
        "rsi":       round(rsi, 1),
        "macd":      macd,
        "trend":     trend,
        "ema9":      round(ema9, 2),
        "ema21":     round(ema21, 2),
        "ema50":     round(ema50, 2),
        "rs_vs_etf": rs_vs_etf,
        "etf":       etf,
        "vol_ratio": round(vol_ratio, 2),
    })

    # ── Scoring ───────────────────────────────────────────────────────────────
    score = 0.0

    # RSI (max 3 pts)
    if 40 <= rsi <= 70:
        score += 3
    elif rsi < 30 and trend != "down":
        score += 1    # oversold + non-downtrend = contrarian opportunity
    elif rsi > 75:
        score -= 2

    # EMA crossover (max 5 pts)
    if trend == "up":
        score += 5
    elif trend == "neutral":
        score += 2

    # MACD (max 4 pts, penalty -4)
    if macd == "bullish":
        score += 4
    elif macd == "bearish":
        score -= 4

    # RS vs sector ETF (max 3 pts, penalty -3)
    if rs_vs_etf > 10:
        score += 3
    elif rs_vs_etf > 3:
        score += 1
    elif rs_vs_etf < -10:
        score -= 3
    elif rs_vs_etf < -3:
        score -= 1

    # Volume (max 2 pts)
    if vol_ratio > 1.5 and trend == "up":
        score += 2
    elif vol_ratio > 1.2 and trend == "up":
        score += 1

    # Penalty: downtrend overrides strong fundamentals
    if trend == "down" and macd == "bearish":
        score = min(score, 5)   # hard cap at 5 when in confirmed downtrend

    score = round(max(0.0, min(20.0, score)), 1)
    data["score"] = score

    # Update company object fields
    company.rsi         = rsi
    company.trend       = trend
    company.macd_signal = macd
    company.rs_vs_etf   = rs_vs_etf
    company.volume_ratio = vol_ratio
    company.ema9        = ema9
    company.ema21       = ema21
    company.ema50       = ema50

    return score, data
