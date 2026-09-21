"""
news_brief.rank tests (spec categories: 7 source priority, 10 empty
category).
"""
from datetime import datetime, timedelta, timezone

from news_brief.models import NewsCluster, RawArticle
from news_brief.rank import CATEGORY_TARGETS, select_key_highlights, select_per_category


def _raw(source_name="Reuters", tier=1, hours_ago=1):
    now = datetime.now(timezone.utc)
    return RawArticle(source_name=source_name, source_url="https://x.com", title="t", link="https://x.com/1",
                       published_at=now - timedelta(hours=hours_ago), summary="", retrieved_at=now,
                       feed_url="https://x.com/feed", tier=tier)


def _cluster(category, n_sources=1, tier=1, hours_ago=1, impact=None):
    now = datetime.now(timezone.utc)
    sources = [_raw(tier=tier, hours_ago=hours_ago) for _ in range(n_sources)]
    return NewsCluster(title=f"item-{id(sources)}", link="https://x.com", summary="",
                        published_at=now - timedelta(hours=hours_ago), sources=sources,
                        category=category, market_impact=impact or {})


def test_empty_category_produces_empty_selection_not_padded():
    selected = select_per_category([])
    assert selected["URANIUM_NUCLEAR"] == []
    assert set(selected.keys()) == set(CATEGORY_TARGETS)


def test_selection_never_exceeds_category_max_target():
    clusters = [_cluster("OIL_GAS") for _ in range(10)]
    selected = select_per_category(clusters)
    _, max_n = CATEGORY_TARGETS["OIL_GAS"]
    assert len(selected["OIL_GAS"]) <= max_n


def test_higher_cross_source_confirmation_ranked_first():
    weak = _cluster("WORLD", n_sources=1)
    strong = _cluster("WORLD", n_sources=3)
    selected = select_per_category([weak, strong])
    assert selected["WORLD"][0] is strong


def test_tier1_source_ranked_above_tier2_when_confirmation_equal():
    tier2 = _cluster("WORLD", n_sources=1, tier=2)
    tier1 = _cluster("WORLD", n_sources=1, tier=1)
    selected = select_per_category([tier2, tier1])
    assert selected["WORLD"][0] is tier1


def test_clusters_with_unknown_category_are_ignored():
    c = _cluster(None)
    selected = select_per_category([c])
    assert all(c not in items for items in selected.values())


def test_key_highlights_pulls_across_categories():
    a = _cluster("OIL_GAS", n_sources=3)
    b = _cluster("AI_SEMIS", n_sources=1)
    selected = select_per_category([a, b])
    highlights = select_key_highlights(selected, max_items=1)
    assert highlights == [a]  # higher cross-source confirmation wins
