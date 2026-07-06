from dataclasses import dataclass, field
from typing import Optional, Dict, Any


@dataclass
class CompanyData:
    ticker: str
    name: str = ""
    sector: str = "unknown"

    price: float = 0.0
    market_cap: float = 0.0

    # Growth / margin metrics (raw yfinance)
    rev_growth: float = 0.0        # fraction (0.25 = 25%)
    eps_growth: float = 0.0
    gross_margin: float = 0.0
    op_margin: float = 0.0
    fcf_margin: float = 0.0
    net_income: float = 0.0
    free_cashflow: float = 0.0
    revenue: float = 0.0

    # Quality metrics
    fcf_conversion: float = 0.0    # FCF / Net Income
    debt_ebitda: float = 0.0
    roe: float = 0.0               # for financials
    rule_of_40: float = 0.0        # rev_growth_pct + fcf_margin_pct

    # Valuation
    forward_pe: Optional[float] = None
    peg: Optional[float] = None
    trailing_pe: Optional[float] = None

    # Technical (populated by technical.py)
    rsi: float = 50.0
    trend: str = "neutral"         # "up", "down", "neutral"
    macd_signal: str = "neutral"   # "bullish", "bearish", "neutral"
    rs_vs_etf: float = 0.0         # % outperformance vs sector ETF
    volume_ratio: float = 1.0      # current vol / 20d avg vol
    ema9: float = 0.0
    ema21: float = 0.0
    ema50: float = 0.0

    # Institutional (populated by institutional.py)
    insider_buy: int = 0
    insider_sell: int = 0
    short_pct: float = 0.0

    # Catalyst (populated by catalyst.py)
    days_to_earnings: Optional[int] = None
    eps_beat_quarters: int = 0     # quarters beat out of last 4
    eps_surprise_avg: float = 0.0  # average % surprise
    recent_upgrades: int = 0
    recent_downgrades: int = 0

    # Macro multiplier (populated by macro.py — shared across all tickers)
    macro_multiplier: float = 1.0

    # Layer scores
    sector_score: float = 0.0
    sector_data: Dict[str, Any] = field(default_factory=dict)

    eps_quality_score: float = 0.0
    eps_quality_data: Dict[str, Any] = field(default_factory=dict)

    tech_score: float = 0.0
    tech_data: Dict[str, Any] = field(default_factory=dict)

    inst_score: float = 7.5        # neutral default (EDGAR may be unavailable)
    inst_data: Dict[str, Any] = field(default_factory=dict)

    catalyst_score: float = 0.0
    catalyst_data: Dict[str, Any] = field(default_factory=dict)

    final_score: float = 0.0
    rating: str = "Skip"
    ai_summary: str = ""
    error: str = ""
