"""
Deduplication (spec section 10): multiple articles about the same real
event become ONE NewsCluster citing all sources, instead of repeated
Telegram bullets. Greedy title-similarity clustering -- deterministic,
no LLM, same seed-free behavior every run for the same input.
"""
from __future__ import annotations

import re
from datetime import timedelta
from difflib import SequenceMatcher

from news_brief.models import NewsCluster, RawArticle

SIMILARITY_THRESHOLD = 0.62
SAME_EVENT_WINDOW_HOURS = 48


def _normalize_title(title: str) -> str:
    t = title.lower()
    t = re.sub(r"\s*[-–—|]\s*(reuters|ap|bbc|cnbc|bloomberg|wsj|ft)\s*$", "", t)  # strip trailing " - Reuters" etc.
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def _within_window(a: RawArticle, b_published_at, window_hours: int) -> bool:
    if a.published_at is None or b_published_at is None:
        return True  # can't compare timing -- don't let missing dates block an otherwise-valid title match
    return abs((a.published_at - b_published_at).total_seconds()) <= window_hours * 3600


def cluster_articles(articles: list[RawArticle]) -> list[NewsCluster]:
    """Sorted by published_at (earliest first) so each cluster's
    representative source is genuinely the earliest real report."""
    sortable = sorted(articles, key=lambda a: a.published_at or a.retrieved_at)
    clusters: list[NewsCluster] = []

    for article in sortable:
        norm_title = _normalize_title(article.title)
        matched = None
        for cluster in clusters:
            if not _within_window(article, cluster.published_at, SAME_EVENT_WINDOW_HOURS):
                continue
            if _similar(norm_title, _normalize_title(cluster.title)) >= SIMILARITY_THRESHOLD:
                matched = cluster
                break

        if matched is None:
            clusters.append(NewsCluster(
                title=article.title, link=article.link, summary=article.summary,
                published_at=article.published_at, sources=[article],
            ))
        else:
            matched.sources.append(article)
            # Prefer the highest-tier source as the representative headline/link/summary;
            # ties broken by earliest publish time (already true by sort order).
            if article.tier < matched.best_tier:
                matched.title, matched.link, matched.summary = article.title, article.link, article.summary

    return clusters
