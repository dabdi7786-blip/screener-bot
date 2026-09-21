"""
news_brief.format_telegram tests (spec categories: 10 empty category,
15 message length, 16 Telegram splitting).
"""
from datetime import datetime, timedelta, timezone

from news_brief.format_telegram import (
    EMPTY_CATEGORY_TEXT, TELEGRAM_MAX_CHARS, build_messages, format_category_section,
    format_highlights, format_sources_lines,
)
from news_brief.models import BriefingResult, NewsCluster, RawArticle


def _raw(i, source_name="Reuters", tier=1):
    now = datetime.now(timezone.utc)
    return RawArticle(source_name=source_name, source_url="https://x.com", title=f"Real headline number {i}",
                       link=f"https://x.com/article-{i}", published_at=now - timedelta(hours=1), summary="x",
                       retrieved_at=now, feed_url="https://x.com/feed", tier=tier)


def _cluster(i, category="WORLD", n_sources=1):
    now = datetime.now(timezone.utc)
    sources = [_raw(i * 100 + j, source_name=f"Source{j}") for j in range(n_sources)]
    return NewsCluster(title=f"Real headline number {i}", link=f"https://x.com/article-{i}", summary="",
                        published_at=now, sources=sources, category=category)


def _result(categories, highlights=None, watchlist=None, impact_map=None):
    return BriefingResult(
        briefing_id="2026-09-21-AM", generated_at=datetime.now(timezone.utc),
        key_highlights=highlights or [], categories=categories, market_impact_map=impact_map or {},
        watchlist=watchlist or [], all_clusters=[c for items in categories.values() for c in items],
        stats={"feeds_attempted": 5, "feeds_succeeded": 5, "feeds_failed": 0},
    )


def test_empty_category_renders_exact_placeholder_text():
    section = format_category_section("WORLD", [])
    assert EMPTY_CATEGORY_TEXT in section


def test_empty_highlights_renders_no_confirmed_news_fallback():
    text = format_highlights([], datetime.now(timezone.utc))
    assert "Не удалось получить подтверждённые новости" in text


def test_all_messages_within_telegram_limit_normal_case():
    categories = {cat: [_cluster(i, category=cat) for i in range(3)] for cat in
                  ("WORLD", "MIDDLE_EAST", "RUSSIA", "OIL_GAS", "URANIUM_NUCLEAR", "AI_SEMIS")}
    result = _result(categories, highlights=[_cluster(0)])
    messages = build_messages(result)
    assert all(len(m) <= TELEGRAM_MAX_CHARS for m in messages)


def test_all_messages_within_limit_with_large_source_list():
    """Regression: a long SOURCES section (many distinct citations)
    must never exceed Telegram's limit -- it must split across extra
    messages instead."""
    categories = {"WORLD": [_cluster(i, n_sources=4) for i in range(4)],
                  "MIDDLE_EAST": [], "RUSSIA": [], "OIL_GAS": [], "URANIUM_NUCLEAR": [], "AI_SEMIS": []}
    # force many distinct sources by giving each cluster unique source names
    for i, c in enumerate(categories["WORLD"]):
        c.sources = [_raw(i * 10 + j, source_name=f"Outlet-{i}-{j}") for j in range(20)]
    result = _result(categories)
    messages = build_messages(result)
    assert all(len(m) <= TELEGRAM_MAX_CHARS for m in messages)
    assert len(messages) >= 3  # spilled into extra message(s) rather than truncating


def test_splitting_never_breaks_a_single_item_html_link():
    categories = {"WORLD": [_cluster(i) for i in range(4)], "MIDDLE_EAST": [], "RUSSIA": [],
                  "OIL_GAS": [], "URANIUM_NUCLEAR": [], "AI_SEMIS": []}
    result = _result(categories)
    messages = build_messages(result)
    full_text = "\n\n".join(messages)
    # every opened <a> tag must have its matching close tag in the SAME message
    for msg in messages:
        assert msg.count("<a ") == msg.count("</a>")


def test_format_sources_lines_deduplicates_by_link():
    c1 = _cluster(1, n_sources=1)
    c1.sources[0].link = "https://x.com/same-article"
    c2 = _cluster(2, n_sources=1)
    c2.sources[0].link = "https://x.com/same-article"  # same link cited by two clusters
    lines = format_sources_lines([c1, c2])
    numbered = [l for l in lines if l[0].isdigit()]
    assert len(numbered) == 1


def test_build_messages_never_empty_even_with_no_data():
    result = _result({cat: [] for cat in ("WORLD", "MIDDLE_EAST", "RUSSIA", "OIL_GAS", "URANIUM_NUCLEAR", "AI_SEMIS")})
    messages = build_messages(result)
    assert len(messages) >= 1
    assert all(len(m) <= TELEGRAM_MAX_CHARS for m in messages)


def test_build_messages_default_translate_none_leaves_english_headline_untouched():
    categories = {"WORLD": [_cluster(0)], "MIDDLE_EAST": [], "RUSSIA": [],
                  "OIL_GAS": [], "URANIUM_NUCLEAR": [], "AI_SEMIS": []}
    result = _result(categories, highlights=[_cluster(0)])
    messages = build_messages(result)  # translate=None default, used by every other test in this file
    assert any("Real headline number 0" in m for m in messages)


def test_build_messages_applies_translate_to_headlines_and_sources():
    categories = {"WORLD": [_cluster(0)], "MIDDLE_EAST": [], "RUSSIA": [],
                  "OIL_GAS": [], "URANIUM_NUCLEAR": [], "AI_SEMIS": []}
    result = _result(categories, highlights=[_cluster(0)])
    messages = build_messages(result, translate=lambda s: f"RU:{s}")
    combined = "\n".join(messages)
    assert "RU:Real headline number 0" in combined
    # every occurrence (highlights, category item, source line) went through translate --
    # none appear as the bare original text (i.e. not immediately preceded by "RU:")
    assert combined.count("Real headline number 0") == combined.count("RU:Real headline number 0")
