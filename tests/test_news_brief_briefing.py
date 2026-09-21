"""
Integration test for news_brief.briefing.build_briefing -- exercises the
full fetch->normalize->dedupe->classify->rank->select pipeline wiring
with a mocked sources.fetch_all (no live network).
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from news_brief.briefing import build_briefing
from news_brief.models import RawArticle


def _raw(title, source_name, tier=1, hours_ago=2, link=None):
    now = datetime.now(timezone.utc)
    return RawArticle(source_name=source_name, source_url=f"https://{source_name.lower()}.com", title=title,
                       link=link or f"https://{source_name.lower()}.com/{abs(hash(title))}",
                       published_at=now - timedelta(hours=hours_ago), summary="", retrieved_at=now,
                       feed_url="https://example.com/feed.xml", tier=tier)


def test_build_briefing_end_to_end_with_mocked_sources():
    fake_articles = [
        _raw("OPEC+ agrees to raise crude oil output", "Reuters"),
        _raw("OPEC+ agrees to raise crude oil output", "AP News"),  # duplicate -> should merge
        _raw("Nvidia unveils new AI chip amid export control concerns", "Bloomberg"),
        _raw("Local bakery wins pastry contest", "RandomBlog", tier=2),  # off-topic, excluded
    ]
    with patch("news_brief.briefing.sources.fetch_all", return_value=(fake_articles, {
        "feeds_attempted": 3, "feeds_succeeded": 3, "feeds_failed": 0, "raw_items": 4,
    })):
        result = build_briefing("2026-09-21-AM", now=datetime.now(timezone.utc))

    assert result.briefing_id == "2026-09-21-AM"
    oil_titles = [c.title for c in result.categories["OIL_GAS"]]
    assert "OPEC+ agrees to raise crude oil output" in oil_titles
    ai_titles = [c.title for c in result.categories["AI_SEMIS"]]
    assert any("Nvidia" in t for t in ai_titles)
    all_titles = [c.title for items in result.categories.values() for c in items]
    assert "Local bakery wins pastry contest" not in all_titles
    assert result.stats["duplicates_removed"] >= 1


def test_build_briefing_zero_sources_yields_empty_result_not_crash():
    with patch("news_brief.briefing.sources.fetch_all", return_value=([], {
        "feeds_attempted": 5, "feeds_succeeded": 0, "feeds_failed": 5, "raw_items": 0,
    })):
        result = build_briefing("2026-09-21-AM", now=datetime.now(timezone.utc))
    assert result.key_highlights == []
    assert all(items == [] for items in result.categories.values())


def test_build_briefing_watchlist_only_includes_selected_companies():
    fake_articles = [_raw("Cameco expands uranium mining operations", "Reuters")]
    with patch("news_brief.briefing.sources.fetch_all", return_value=(fake_articles, {
        "feeds_attempted": 1, "feeds_succeeded": 1, "feeds_failed": 0, "raw_items": 1,
    })):
        result = build_briefing("2026-09-21-AM", now=datetime.now(timezone.utc))
    tickers = [t for t, _ in result.watchlist]
    assert "CCJ" in tickers
    assert "NVDA" not in tickers  # not mentioned anywhere -- must not appear
