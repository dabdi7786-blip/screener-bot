"""
Ranking + selection (spec section 9): materiality, source reliability,
recency, novelty, cross-source confirmation. Targets are targets, not
quotas -- a category with nothing material stays empty rather than
being padded.
"""
from __future__ import annotations

from datetime import datetime, timezone

from news_brief.models import NewsCluster
from news_brief.normalize import is_developing

CATEGORY_TARGETS = {
    "WORLD": (2, 4), "MIDDLE_EAST": (2, 4), "RUSSIA": (2, 4),
    "OIL_GAS": (2, 4), "URANIUM_NUCLEAR": (1, 3), "AI_SEMIS": (2, 4),
}


def _importance_score(cluster: NewsCluster) -> tuple:
    """Sort key, descending: cross-source confirmation, then source
    tier (lower=better), then recency, then market-impact severity."""
    impact_rank = max(({"HIGH": 2, "MEDIUM": 1, "LOW": 0}.get(v, 0) for v in cluster.market_impact.values()), default=0)
    recency = cluster.published_at or datetime.min.replace(tzinfo=timezone.utc)
    return (cluster.source_count, -cluster.best_tier, impact_rank, recency)


def rank_within_category(clusters: list[NewsCluster]) -> list[NewsCluster]:
    return sorted(clusters, key=_importance_score, reverse=True)


def select_per_category(clusters: list[NewsCluster], now: datetime | None = None) -> dict[str, list[NewsCluster]]:
    """Marks .developing on items outside the primary window, then
    selects up to the category's max target -- never padding to hit the
    minimum with irrelevant items."""
    now = now or datetime.now(timezone.utc)
    by_category: dict[str, list[NewsCluster]] = {c: [] for c in CATEGORY_TARGETS}

    for cluster in clusters:
        if cluster.category not in by_category:
            continue
        # a cluster is "developing" only if its earliest (representative) source is aged out of the primary window
        rep_source = min(cluster.sources, key=lambda s: s.published_at or now) if cluster.sources else None
        if rep_source is not None:
            cluster.developing = is_developing(rep_source, now)
        by_category[cluster.category].append(cluster)

    selected: dict[str, list[NewsCluster]] = {}
    for category, items in by_category.items():
        ranked = rank_within_category(items)
        _, max_n = CATEGORY_TARGETS[category]
        selected[category] = ranked[:max_n]
    return selected


def select_key_highlights(selected: dict[str, list[NewsCluster]], max_items: int = 5) -> list[NewsCluster]:
    """Top 3-5 items across ALL categories by importance, for the
    'КЛЮЧЕВОЕ' summary at the top of the briefing."""
    pool = [c for items in selected.values() for c in items]
    ranked = sorted(pool, key=_importance_score, reverse=True)
    return ranked[:max_items]
