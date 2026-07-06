"""
AI commentary via Anthropic Claude API.
Called only for top-N companies (AI_TOP_N from config).
"""
import logging
from models import CompanyData

logger = logging.getLogger(__name__)

_CLIENT = None


def _get_client():
    global _CLIENT
    if _CLIENT is None:
        from config import ANTHROPIC_API_KEY
        if not ANTHROPIC_API_KEY:
            return None
        import anthropic
        _CLIENT = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _CLIENT


def generate_summary(company: CompanyData) -> str:
    """Return 2-3 sentence AI commentary or fallback string."""
    client = _get_client()
    if client is None:
        logger.warning("ANTHROPIC_API_KEY not set — skipping AI for %s", company.ticker)
        return "AI-анализ недоступен (ключ API не задан)."

    prompt = _build_prompt(company)
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        text = msg.content[0].text.strip()
        logger.info("%s AI summary generated (%d chars)", company.ticker, len(text))
        return text
    except Exception as e:
        logger.warning("AI generation failed for %s: %s", company.ticker, e)
        return "AI временно недоступен."


def _build_prompt(c: CompanyData) -> str:
    return f"""Дай краткий инвестиционный анализ (2-3 предложения, только факты, без воды) для {c.ticker} ({c.name}).

Данные:
- Сектор: {c.sector}
- Рейтинг: {c.rating} (скор: {c.final_score:.0f}/95)
- Выручка: рост {c.rev_growth*100:.1f}% г/г
- EPS: рост {c.eps_growth*100:.1f}% г/г
- Gross margin: {c.gross_margin*100:.1f}%
- FCF margin: {c.fcf_margin*100:.1f}%
- Технический тренд: {c.trend}, RSI: {c.rsi:.0f}, MACD: {c.macd_signal}
- RS vs {c.sector} ETF: {c.rs_vs_etf:+.1f}%
- Инсайдеры: покупок {c.insider_buy}, продаж {c.insider_sell}
- Short interest: {c.short_pct:.1f}%

Ответь на русском языке. Укажи ключевой риск и ключевой драйвер роста."""
