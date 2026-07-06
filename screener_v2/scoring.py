"""
Aggregate layer scores into final_score and assign rating.
Formula: (sector + eps_quality + technical + institutional + catalyst) × macro_multiplier
Penalty: trend==down AND sector_score>20 → ×0.85
"""
from config import THRESHOLDS
from models import CompanyData


def compute(company: CompanyData) -> None:
    """Mutates company.final_score and company.rating in-place."""
    raw = (
        company.sector_score
        + company.eps_quality_score
        + company.tech_score
        + company.inst_score
        + company.catalyst_score
    )
    # Penalty: strong fundamentals + downtrend = premature entry
    if company.trend == "down" and company.sector_score > 20:
        raw *= 0.85

    final = raw * company.macro_multiplier
    company.final_score = round(max(0.0, min(95.0, final)), 1)
    company.rating = _rating(company.final_score)


def _rating(score: float) -> str:
    if score >= THRESHOLDS["strong_buy"]:
        return "Strong Buy"
    if score >= THRESHOLDS["buy_watch"]:
        return "Buy+Watch"
    if score >= THRESHOLDS["watch"]:
        return "Watch"
    if score >= THRESHOLDS["wait"]:
        return "Wait"
    return "Skip"
