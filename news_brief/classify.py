"""
Deterministic category + market-impact classification (spec sections 8,
11, 13). Keyword lists below are taken directly from the task's own
per-category tracking lists -- not invented. No LLM, no randomness: the
same input text always classifies the same way.
"""
from __future__ import annotations

from news_brief.models import NewsCluster
from news_brief.textutil import kw_in as _kw_in

# More specific categories are checked before the generic WORLD bucket,
# so e.g. an "Iran" item scores into MIDDLE_EAST rather than WORLD.
_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "MIDDLE_EAST": (
        "israel", "iran", "gaza", "lebanon", "syria", "yemen", "houthi",
        "red sea", "strait of hormuz", "hormuz", "hezbollah", "idf",
        "tehran", "tel aviv", "netanyahu", "gulf",
    ),
    "RUSSIA": (
        "russia", "russian", "ukraine", "ukrainian", "kremlin", "putin",
        "moscow", "zelensky", "sanctions on russia", "ruble", "rosneft",
        "gazprom", "novorossiysk",
    ),
    "OIL_GAS": (
        "brent", "wti", "opec", "crude oil", "crude", "oil", "oil price",
        "oil market", "natural gas", "lng", "pipeline", "refinery",
        "refiner", "tanker", "eia", "barrel", "petroleum",
    ),
    "URANIUM_NUCLEAR": (
        "uranium", "cameco", "kazatomprom", "centrus", "enrichment",
        "nuclear fuel", "nuclear reactor", "nuclear power", "smr",
        "small modular reactor", "iaea", "nuclear plant", "atomic energy",
    ),
    "AI_SEMIS": (
        "nvidia", "amd", "broadcom", "tsmc", "openai", "anthropic",
        "semiconductor", "chip export", "gpu", "ai chip", "data center",
        "hyperscaler", "artificial intelligence", "ai model", "ai regulation",
        "microsoft ai", "google ai", "meta ai",
    ),
    "WORLD": (
        "federal reserve", "central bank", "interest rate", "inflation",
        "gdp", "china", "european union", "eurozone", "white house",
        "united nations", "treasury", "election", "diplomatic",
    ),
}

_CATEGORY_ORDER = ("MIDDLE_EAST", "RUSSIA", "OIL_GAS", "URANIUM_NUCLEAR", "AI_SEMIS", "WORLD")

# (category, keyword_substring) -> (impact_level, affected_asset_label, short RU cause->effect reason).
# Order matters: first match wins within a category, most specific/severe first.
# The reason is a short, deterministic phrase tied to the matched keyword's own
# well-known mechanism (e.g. "Ormuz strait" -> "oil shipping risk") -- never a
# generated/inferred explanation, so it carries no fabrication risk.
_IMPACT_RULES: dict[str, tuple[tuple[str, str, str, str], ...]] = {
    "MIDDLE_EAST": (
        ("hormuz", "HIGH", "Oil/Shipping", "риск перекрытия Ормузского пролива → поставки нефти"),
        ("red sea", "HIGH", "Shipping", "риск для судоходства через Красное море"),
        ("attack", "HIGH", "Oil/Energy infrastructure", "риск для энергетической инфраструктуры региона"),
        ("tanker", "HIGH", "Oil/Shipping", "риск для танкерных поставок нефти"),
        ("sanctions", "MEDIUM", "Energy/Trade", "санкции → торговые и энергетические потоки"),
    ),
    "OIL_GAS": (
        ("hormuz", "HIGH", "Oil", "узкое место мировых поставок нефти"),
        ("opec", "HIGH", "Oil", "решение ОПЕК+ по добыче → цены на нефть"),
        ("refinery", "MEDIUM", "Oil/Refining", "перебои переработки → цены на топливо"),
        ("pipeline", "MEDIUM", "Oil/Gas", "перебои трубопроводных поставок"),
        ("inventories", "MEDIUM", "Oil", "запасы нефти → краткосрочная динамика цен"),
    ),
    "RUSSIA": (
        ("pipeline", "MEDIUM", "Oil/Gas", "поставки нефти/газа по трубопроводам"),
        ("refinery", "MEDIUM", "Oil", "удары по НПЗ → переработка и экспорт нефтепродуктов"),
        ("sanctions", "MEDIUM", "Energy/Trade", "санкции → энергетический экспорт РФ"),
        ("port", "MEDIUM", "Shipping", "экспорт через морские порты"),
    ),
    "URANIUM_NUCLEAR": (
        ("export restriction", "MEDIUM", "Uranium", "ограничение экспорта урана → предложение на рынке"),
        ("supply", "MEDIUM", "Uranium", "поставки урана → цены на топливо для АЭС"),
        ("enrichment", "MEDIUM", "Uranium/Nuclear fuel", "обогащение урана → предложение ядерного топлива"),
    ),
    "AI_SEMIS": (
        ("export control", "HIGH", "Semiconductors", "экспортные ограничения на чипы → доступ к рынкам"),
        ("chip export", "HIGH", "Semiconductors", "поставки чипов на ключевые рынки"),
        ("capex", "MEDIUM", "AI/Data centers", "капзатраты на ИИ-инфраструктуру"),
        ("data center", "MEDIUM", "AI/Data centers", "спрос на дата-центры → чипы/энергию"),
    ),
    "WORLD": (
        ("interest rate", "MEDIUM", "Broad equities", "решение по ключевой ставке → стоимость капитала"),
        ("inflation", "MEDIUM", "Broad equities", "инфляция в США → на решение ФРС по ставке"),
    ),
}


_SPECIFIC_CATEGORIES = ("MIDDLE_EAST", "RUSSIA", "OIL_GAS", "URANIUM_NUCLEAR", "AI_SEMIS")


def classify_category(cluster: NewsCluster) -> str | None:
    """Returns None (excluded -- spec section 8's "avoid celebrity/
    sports/entertainment") rather than defaulting everything unmatched
    into WORLD. A specific category requires a TITLE hit (not just
    summary) -- Google News RSS descriptions sometimes bundle unrelated
    "full coverage" text, which was observed live to mis-route
    off-topic items via summary-only matching; requiring the title
    itself to be on-topic is a direct, deterministic fix for that."""
    title = cluster.title.lower()
    full_text = f"{cluster.title} {cluster.summary}".lower()

    title_scores = {c: sum(1 for kw in _CATEGORY_KEYWORDS[c] if _kw_in(kw, title)) for c in _SPECIFIC_CATEGORIES}
    title_scores = {c: n for c, n in title_scores.items() if n > 0}
    if title_scores:
        # tie-broken by full-text hit count (more context, still requires the title hit), then _CATEGORY_ORDER
        full_scores = {c: sum(1 for kw in _CATEGORY_KEYWORDS[c] if _kw_in(kw, full_text)) for c in title_scores}
        best = max(full_scores.values())
        for category in _CATEGORY_ORDER:
            if full_scores.get(category) == best:
                return category

    world_hits = sum(1 for kw in _CATEGORY_KEYWORDS["WORLD"] if _kw_in(kw, full_text))
    if world_hits > 0:
        return "WORLD"

    return None  # no specific-category title match and no WORLD match -- excluded, not force-defaulted


def _classify_impact_and_reasons(cluster: NewsCluster) -> tuple[dict[str, str], dict[str, str]]:
    text = f"{cluster.title} {cluster.summary}".lower()
    category = cluster.category or "WORLD"
    impact: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for keyword, level, asset, reason in _IMPACT_RULES.get(category, ()):
        if _kw_in(keyword, text):
            # keep the highest-severity label (and its matching reason) per asset if multiple keywords hit
            existing = impact.get(asset)
            if existing is None or _severity(level) > _severity(existing):
                impact[asset] = level
                reasons[asset] = reason
    return impact, reasons


def classify_market_impact(cluster: NewsCluster) -> dict[str, str]:
    impact, _reasons = _classify_impact_and_reasons(cluster)
    return impact


def classify_impact_reasons(cluster: NewsCluster) -> dict[str, str]:
    _impact, reasons = _classify_impact_and_reasons(cluster)
    return reasons


def _severity(level: str) -> int:
    return {"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(level, 0)


def classify_all(clusters: list[NewsCluster]) -> None:
    """Mutates clusters in place -- assigns .category, .market_impact,
    and .impact_reasons (short deterministic cause->effect phrases,
    never a generated explanation)."""
    for c in clusters:
        c.category = classify_category(c)
        c.market_impact, c.impact_reasons = _classify_impact_and_reasons(c)
