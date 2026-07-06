"""
Layer 1: Sector-specific metrics (0–30 pts).
Rule of 40 applies ONLY to saas and platform sectors.
"""
import logging
from models import CompanyData

logger = logging.getLogger(__name__)


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _saas(c: CompanyData) -> tuple[float, dict]:
    rev_g  = c.rev_growth * 100    # fraction → pct
    fcf_m  = c.fcf_margin * 100
    gm     = c.gross_margin * 100
    r40    = rev_g + fcf_m
    data   = {"rule_of_40": round(r40, 1), "rev_growth_pct": round(rev_g, 1),
              "fcf_margin_pct": round(fcf_m, 1), "gross_margin_pct": round(gm, 1)}
    s = 0.0
    # Rule of 40 (max 10)
    if r40 > 60:    s += 10
    elif r40 > 40:  s += 7
    elif r40 > 20:  s += 3
    # Gross margin (max 8)
    if gm > 75:     s += 8
    elif gm > 65:   s += 5
    elif gm > 50:   s += 2
    # Revenue growth (max 6)
    if rev_g > 25:  s += 6
    elif rev_g > 15: s += 3
    elif rev_g > 8:  s += 1
    # FCF margin (max 4)
    if fcf_m > 20:  s += 4
    elif fcf_m > 10: s += 2
    elif fcf_m < 0:  s -= 2
    return _clamp(s, 0, 30), data


def _semiconductor(c: CompanyData) -> tuple[float, dict]:
    rev_g = c.rev_growth * 100
    gm    = c.gross_margin * 100
    om    = c.op_margin * 100
    eps_g = c.eps_growth * 100
    data  = {"rev_growth_pct": round(rev_g, 1), "gross_margin_pct": round(gm, 1),
             "op_margin_pct": round(om, 1), "eps_growth_pct": round(eps_g, 1)}
    s = 0.0
    # Revenue growth (max 10)
    if rev_g > 20:   s += 10
    elif rev_g > 10: s += 6
    elif rev_g > 0:  s += 3
    elif rev_g < -10: s -= 2
    # Gross margin (max 10)
    if gm > 55:     s += 10
    elif gm > 45:   s += 7
    elif gm > 35:   s += 3
    # Op margin (max 6)
    if om > 30:     s += 6
    elif om > 20:   s += 4
    elif om > 10:   s += 2
    # EPS growth bonus (max 4)
    if eps_g > 20:  s += 4
    elif eps_g > 0: s += 1
    return _clamp(s, 0, 30), data


def _pharma(c: CompanyData) -> tuple[float, dict]:
    rev_g = c.rev_growth * 100
    gm    = c.gross_margin * 100
    fcf_m = c.fcf_margin * 100
    eps_g = c.eps_growth * 100
    data  = {"rev_growth_pct": round(rev_g, 1), "gross_margin_pct": round(gm, 1),
             "fcf_margin_pct": round(fcf_m, 1), "eps_growth_pct": round(eps_g, 1)}
    s = 0.0
    # Revenue growth (max 8)
    if rev_g > 20:   s += 8
    elif rev_g > 10: s += 5
    elif rev_g > 0:  s += 2
    # Gross margin (max 10)
    if gm > 80:     s += 10
    elif gm > 70:   s += 7
    elif gm > 50:   s += 4
    elif gm > 30:   s += 1
    # FCF margin (max 8)
    if fcf_m > 20:  s += 8
    elif fcf_m > 10: s += 5
    elif fcf_m > 0:  s += 2
    elif fcf_m < 0:  s -= 2
    # EPS growth (max 4)
    if eps_g > 20:  s += 4
    elif eps_g > 0: s += 1
    return _clamp(s, 0, 30), data


def _financials(c: CompanyData) -> tuple[float, dict]:
    roe   = c.roe * 100
    rev_g = c.rev_growth * 100
    eps_g = c.eps_growth * 100
    gm    = c.gross_margin * 100
    data  = {"roe_pct": round(roe, 1), "rev_growth_pct": round(rev_g, 1),
             "eps_growth_pct": round(eps_g, 1), "gross_margin_pct": round(gm, 1)}
    s = 0.0
    # ROE (max 10) — primary quality metric for financials
    if roe > 20:    s += 10
    elif roe > 15:  s += 7
    elif roe > 10:  s += 4
    elif roe < 5:   s -= 2
    # Revenue growth (max 8)
    if rev_g > 15:   s += 8
    elif rev_g > 8:  s += 5
    elif rev_g > 0:  s += 2
    # EPS growth (max 8)
    if eps_g > 20:   s += 8
    elif eps_g > 10: s += 5
    elif eps_g > 0:  s += 2
    # Gross / net margin (proxy via gm, max 4)
    if gm > 60:     s += 4
    elif gm > 40:   s += 2
    return _clamp(s, 0, 30), data


def _platform(c: CompanyData) -> tuple[float, dict]:
    """Big tech / platform: Rule of 40 applies here too."""
    rev_g = c.rev_growth * 100
    om    = c.op_margin * 100
    gm    = c.gross_margin * 100
    eps_g = c.eps_growth * 100
    r40   = rev_g + c.fcf_margin * 100
    data  = {"rule_of_40": round(r40, 1), "rev_growth_pct": round(rev_g, 1),
             "op_margin_pct": round(om, 1), "gross_margin_pct": round(gm, 1),
             "eps_growth_pct": round(eps_g, 1)}
    s = 0.0
    # Revenue growth (max 10)
    if rev_g > 20:   s += 10
    elif rev_g > 12: s += 7
    elif rev_g > 5:  s += 3
    # Op margin (max 8) — margin expansion key for mega-caps
    if om > 35:     s += 8
    elif om > 25:   s += 5
    elif om > 15:   s += 2
    elif om < 0:    s -= 3
    # Gross margin (max 6)
    if gm > 70:     s += 6
    elif gm > 55:   s += 3
    # EPS growth (max 6)
    if eps_g > 20:  s += 6
    elif eps_g > 10: s += 3
    # Rule of 40 bonus (max 2) — secondary check
    if r40 > 50:    s += 2
    elif r40 > 30:  s += 1
    return _clamp(s, 0, 30), data


def _generic(c: CompanyData) -> tuple[float, dict]:
    rev_g = c.rev_growth * 100
    eps_g = c.eps_growth * 100
    gm    = c.gross_margin * 100
    fcf_m = c.fcf_margin * 100
    data  = {"rev_growth_pct": round(rev_g, 1), "eps_growth_pct": round(eps_g, 1),
             "gross_margin_pct": round(gm, 1), "fcf_margin_pct": round(fcf_m, 1)}
    s = 0.0
    if rev_g > 20:   s += 8
    elif rev_g > 10: s += 5
    elif rev_g > 0:  s += 2
    if eps_g > 20:   s += 8
    elif eps_g > 10: s += 5
    elif eps_g > 0:  s += 2
    if gm > 60:     s += 7
    elif gm > 40:   s += 4
    if fcf_m > 15:  s += 7
    elif fcf_m > 5: s += 4
    elif fcf_m < 0: s -= 2
    return _clamp(s, 0, 30), data


_HANDLERS = {
    "saas":          _saas,
    "semiconductor": _semiconductor,
    "pharma":        _pharma,
    "financials":    _financials,
    "platform":      _platform,
}


def analyze(company: CompanyData) -> tuple[float, dict]:
    handler = _HANDLERS.get(company.sector, _generic)
    score, data = handler(company)
    data["sector"] = company.sector
    logger.debug("%s sector_score=%.1f", company.ticker, score)
    return score, data
