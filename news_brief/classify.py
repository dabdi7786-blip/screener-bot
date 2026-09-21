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

# (category, keyword_substring) -> (impact_level, affected_asset_label). Order matters:
# first match wins within a category, most specific/severe first.
_IMPACT_RULES: dict[str, tuple[tuple[str, str, str], ...]] = {
    "MIDDLE_EAST": (
        ("hormuz", "HIGH", "Oil/Shipping"), ("red sea", "HIGH", "Shipping"),
        ("attack", "HIGH", "Oil/Energy infrastructure"), ("tanker", "HIGH", "Oil/Shipping"),
        ("sanctions", "MEDIUM", "Energy/Trade"),
    ),
    "OIL_GAS": (
        ("hormuz", "HIGH", "Oil"), ("opec", "HIGH", "Oil"), ("refinery", "MEDIUM", "Oil/Refining"),
        ("pipeline", "MEDIUM", "Oil/Gas"), ("inventories", "MEDIUM", "Oil"),
    ),
    "RUSSIA": (
        ("pipeline", "MEDIUM", "Oil/Gas"), ("refinery", "MEDIUM", "Oil"),
        ("sanctions", "MEDIUM", "Energy/Trade"), ("port", "MEDIUM", "Shipping"),
    ),
    "URANIUM_NUCLEAR": (
        ("export restriction", "MEDIUM", "Uranium"), ("supply", "MEDIUM", "Uranium"),
        ("enrichment", "MEDIUM", "Uranium/Nuclear fuel"),
    ),
    "AI_SEMIS": (
        ("export control", "HIGH", "Semiconductors"), ("chip export", "HIGH", "Semiconductors"),
        ("capex", "MEDIUM", "AI/Data centers"), ("data center", "MEDIUM", "AI/Data centers"),
    ),
    "WORLD": (
        ("interest rate", "MEDIUM", "Broad equities"), ("inflation", "MEDIUM", "Broad equities"),
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


def classify_market_impact(cluster: NewsCluster) -> dict[str, str]:
    text = f"{cluster.title} {cluster.summary}".lower()
    category = cluster.category or "WORLD"
    impact: dict[str, str] = {}
    for keyword, level, asset in _IMPACT_RULES.get(category, ()):
        if _kw_in(keyword, text):
            # keep the highest-severity label per asset if multiple keywords hit
            existing = impact.get(asset)
            if existing is None or _severity(level) > _severity(existing):
                impact[asset] = level
    return impact


def _severity(level: str) -> int:
    return {"LOW": 0, "MEDIUM": 1, "HIGH": 2}.get(level, 0)


def classify_all(clusters: list[NewsCluster]) -> None:
    """Mutates clusters in place -- assigns .category and .market_impact."""
    for c in clusters:
        c.category = classify_category(c)
        c.market_impact = classify_market_impact(c)
