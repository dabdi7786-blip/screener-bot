"""
Orchestration: fetch -> normalize -> dedupe -> classify -> rank -> select
-> build BriefingResult. This module owns the pipeline order; it does
not itself fetch or format -- those stay in sources.py/format_telegram.py.
"""
from __future__ import annotations

from datetime import datetime, timezone

from news_brief import classify, dedupe, normalize, rank, sources
from news_brief.models import BriefingResult, NewsCluster

# company/topic mention -> ticker, used ONLY to build the descriptive
# watchlist (spec section 14) -- never a buy/sell signal. A ticker is
# only included when a SELECTED news item actually mentions the company.
_TICKER_HINTS: tuple[tuple[str, str], ...] = (
    ("nvidia", "NVDA"), ("amd", "AMD"), ("broadcom", "AVGO"), ("tsmc", "TSM"),
    ("microsoft", "MSFT"), ("alphabet", "GOOGL"), ("google", "GOOGL"),
    ("amazon", "AMZN"), ("meta", "META"), ("cameco", "CCJ"),
    ("kazatomprom", "KAP.L"), ("centrus", "LEU"), ("exxon", "XOM"),
    ("chevron", "CVX"), ("occidental", "OXY"),
)


def _build_watchlist(selected: dict[str, list[NewsCluster]]) -> list[tuple[str, str]]:
    seen: dict[str, str] = {}
    for category, items in selected.items():
        for cluster in items:
            text = f"{cluster.title} {cluster.summary}".lower()
            for keyword, ticker in _TICKER_HINTS:
                if keyword in text and ticker not in seen:
                    label = {
                        "AI_SEMIS": "AI capex / semiconductor development",
                        "URANIUM_NUCLEAR": "nuclear fuel development",
                        "OIL_GAS": "oil supply/geopolitical development",
                        "MIDDLE_EAST": "geopolitical/energy development",
                        "RUSSIA": "energy/sanctions development",
                    }.get(category, "market development")
                    seen[ticker] = label
    return list(seen.items())


def _build_market_impact_map(selected: dict[str, list[NewsCluster]]) -> dict[str, str]:
    """Aggregates the per-item market_impact tags (already derived from
    real keyword matches, classify.py) into one label per category --
    never an arbitrary score."""
    labels: dict[str, str] = {}
    severity = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
    for category, items in selected.items():
        if not items:
            continue
        levels = [lvl for c in items for lvl in c.market_impact.values()]
        if not levels:
            labels[category] = "LOW"
            continue
        worst = max(levels, key=lambda l: severity.get(l, 0))
        labels[category] = worst
    return labels


def build_briefing(briefing_id: str, now: datetime | None = None, session=None) -> BriefingResult:
    now = now or datetime.now(timezone.utc)

    raw_articles, fetch_stats = sources.fetch_all(session=session)
    validated, validate_stats = normalize.validate(raw_articles, now=now)
    clusters = dedupe.cluster_articles(validated)
    classify.classify_all(clusters)
    selected = rank.select_per_category(clusters, now=now)
    highlights = rank.select_key_highlights(selected)
    watchlist = _build_watchlist(selected)
    impact_map = _build_market_impact_map(selected)

    stats = {
        **fetch_stats, **validate_stats,
        "clusters_total": len(clusters),
        "duplicates_removed": len(validated) - len(clusters),
        "category_counts": {cat: len(items) for cat, items in selected.items()},
    }

    return BriefingResult(
        briefing_id=briefing_id, generated_at=now, key_highlights=highlights,
        categories=selected, market_impact_map=impact_map, watchlist=watchlist,
        all_clusters=clusters, stats=stats,
    )
