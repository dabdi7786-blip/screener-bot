"""
news_brief.dedupe tests (spec categories: 4 duplicate articles, 5 same
event from multiple sources).
"""
from datetime import datetime, timedelta, timezone

from news_brief.dedupe import cluster_articles
from news_brief.models import RawArticle


def _article(title, source_name, tier=2, hours_ago=0, link=None):
    now = datetime.now(timezone.utc)
    return RawArticle(
        source_name=source_name, source_url=f"https://{source_name.lower()}.com", title=title,
        link=link or f"https://{source_name.lower()}.com/{hash(title) % 10_000}",
        published_at=now - timedelta(hours=hours_ago), summary="", retrieved_at=now,
        feed_url="https://example.com/feed.xml", tier=tier,
    )


def test_identical_titles_from_different_sources_merge_into_one_cluster():
    a = _article("Fed raises interest rates by 25bps", "Reuters", tier=1, hours_ago=1)
    b = _article("Fed raises interest rates by 25bps", "AP News", tier=1, hours_ago=1)
    c = _article("Fed raises interest rates by 25bps", "BBC", tier=2, hours_ago=2)
    clusters = cluster_articles([a, b, c])
    assert len(clusters) == 1
    assert clusters[0].source_count == 3


def test_cluster_cites_all_sources():
    a = _article("Iran nuclear talks resume in Vienna", "Reuters", tier=1)
    b = _article("Iran nuclear talks resume in Vienna", "AP News", tier=1)
    clusters = cluster_articles([a, b])
    names = {s.source_name for s in clusters[0].sources}
    assert names == {"Reuters", "AP News"}


def test_dissimilar_titles_stay_separate_clusters():
    a = _article("Fed raises interest rates by 25bps", "Reuters")
    b = _article("Cameco signs new uranium supply contract", "World Nuclear News")
    clusters = cluster_articles([a, b])
    assert len(clusters) == 2


def test_similar_titles_far_apart_in_time_stay_separate():
    """Same-looking headline but 10 days apart is very unlikely to be
    the same event -- the time window prevents an accidental false merge."""
    a = _article("OPEC+ agrees to cut oil production", "Reuters", hours_ago=1)
    b = _article("OPEC+ agrees to cut oil production", "Reuters", hours_ago=300)
    clusters = cluster_articles([a, b])
    assert len(clusters) == 2


def test_representative_prefers_higher_tier_source():
    tier2_first = _article("Saudi Arabia oil exports rise", "SomeBlog", tier=2, hours_ago=2)
    tier1_second = _article("Saudi Arabia oil exports rise", "Reuters", tier=1, hours_ago=1)
    clusters = cluster_articles([tier2_first, tier1_second])
    assert len(clusters) == 1
    assert clusters[0].title == "Saudi Arabia oil exports rise"
    # representative link/source should be the tier-1 one
    assert any(s.source_name == "Reuters" for s in clusters[0].sources)
    assert clusters[0].best_tier == 1


def test_empty_input_yields_empty_clusters():
    assert cluster_articles([]) == []
