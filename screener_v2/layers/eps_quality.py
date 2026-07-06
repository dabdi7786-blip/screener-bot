"""
Layer 2: EPS quality (0–20 pts).
Penalises accounting artifacts: EPS/Rev divergence, low FCF conversion,
deteriorating margins, excessive leverage.
"""
import logging
from models import CompanyData

logger = logging.getLogger(__name__)

_BASE = 14.0   # start here; bonuses push to 20, penalties pull to 0


def analyze(company: CompanyData) -> tuple[float, dict]:
    s = _BASE
    data: dict = {}

    rev_g = company.rev_growth * 100
    eps_g = company.eps_growth * 100

    # EPS / Revenue divergence: EPS growing >3× faster than revenue → accounting risk
    divergence = False
    if abs(rev_g) > 0.1 and eps_g > rev_g * 3 and eps_g > 15:
        s -= 6
        divergence = True
    data["eps_rev_divergence"] = divergence

    # FCF conversion (FCF / Net Income)
    conv = company.fcf_conversion
    data["fcf_conversion"] = round(conv, 2)
    if conv > 1.4:
        s += 3      # FCF > earnings → high quality
    elif conv > 0.8:
        s += 1
    elif conv < 0.6 and conv > -0.5:
        s -= 5      # earnings not backed by cash
    elif conv < -0.5:
        s -= 3      # heavily negative FCF (may be by design — invest-heavy phase)

    # Gross margin trend (QoQ): if we don't have QoQ data, use absolute level as proxy
    # yfinance doesn't expose QoQ directly; use gross_margin absolute level as quality proxy
    gm = company.gross_margin * 100
    data["gross_margin_pct"] = round(gm, 1)
    if gm > 70:
        s += 2      # high GM = pricing power / moat
    elif gm < 20:
        s -= 2      # low GM = cost structure pressure

    # Debt / EBITDA
    de = company.debt_ebitda
    data["debt_ebitda"] = round(de, 2)
    if de < 0:
        # negative EBITDA or negative debt (net cash) — treat as net cash positive
        de_adj = 0.0 if de < 0 else de
    else:
        de_adj = de
    if de_adj < 1:
        s += 1
    elif de_adj > 5:
        s -= 4
    elif de_adj > 3:
        s -= 2

    score = round(max(0.0, min(20.0, s)), 1)
    data["score"] = score
    logger.debug("%s eps_quality_score=%.1f (base=%.0f)", company.ticker, score, _BASE)
    return score, data
