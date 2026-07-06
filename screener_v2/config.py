import os
from dotenv import load_dotenv

load_dotenv()

# ── API keys ─────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
FRED_API_KEY: str      = os.getenv("FRED_API_KEY", "")
EDGAR_USER_AGENT: str  = os.getenv("EDGAR_USER_AGENT", "ScreenerV2 user@example.com")

# ── Watchlist & sector mapping ────────────────────────────────────────────────
WATCHLIST: list[str] = [
    "NVDA", "AVGO", "MSFT", "GOOGL", "META",
    "AAPL", "AMZN", "V", "MA", "ADSK",
    "PLTR", "NOW", "CRWD", "DDOG", "SNOW",
    "INCY", "LLY", "ABBV", "UNH",
    "JPM", "GS", "BLK",
]

SECTOR_MAP: dict[str, str] = {
    # SaaS
    "MSFT": "saas", "ADSK": "saas", "NOW": "saas", "CRWD": "saas",
    "DDOG": "saas", "SNOW": "saas", "PLTR": "saas",
    # Semiconductor
    "NVDA": "semiconductor", "AVGO": "semiconductor",
    # Platform / Big Tech
    "GOOGL": "platform", "META": "platform", "AAPL": "platform",
    "AMZN": "platform",
    # Financials
    "V": "financials", "MA": "financials", "JPM": "financials",
    "GS": "financials", "BLK": "financials",
    # Pharma / Biotech
    "LLY": "pharma", "ABBV": "pharma", "INCY": "pharma", "UNH": "pharma",
}

SECTOR_ETF_MAP: dict[str, str] = {
    "saas":          "IGV",
    "semiconductor": "SOXX",
    "pharma":        "XBI",
    "financials":    "XLF",
    "platform":      "QQQ",
    "unknown":       "SPY",
}

# ── Scoring thresholds ────────────────────────────────────────────────────────
THRESHOLDS: dict[str, int] = {
    "strong_buy": 65,
    "buy_watch":  50,
    "watch":      38,
    "wait":       25,
}

# ── Misc config ───────────────────────────────────────────────────────────────
AI_TOP_N: int             = 10    # AI commentary for top-N stocks only
SLEEP_BETWEEN_TICKERS: float = 0.5
SLEEP_EDGAR: float        = 1.0
HISTORY_PERIOD: str       = "6mo"   # yfinance history for technicals
MIN_BARS_TECHNICAL: int   = 50      # min bars before computing TA (else neutral 10.0)
