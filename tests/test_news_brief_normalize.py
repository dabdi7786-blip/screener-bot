"""
news_brief.normalize tests (spec categories: 3 missing timestamp,
8 stale article rejection, 9 URL validation, 10 empty category via
zero-survivors).
"""
from datetime import datetime, timedelta, timezone

from news_brief.models import RawArticle
from news_brief.normalize import is_stale, is_valid_url, strip_html, validate


def _article(**overrides) -> RawArticle:
    now = datetime.now(timezone.utc)
    defaults = dict(
        source_name="Reuters", source_url="https://www.reuters.com", title="Some headline",
        link="https://www.reuters.com/article", published_at=now - timedelta(hours=2),
        summary="A summary.", retrieved_at=now, feed_url="https://example.com/feed.xml", tier=1,
    )
    defaults.update(overrides)
    return RawArticle(**defaults)


def test_url_validation_accepts_http_https_rejects_others():
    assert is_valid_url("https://www.reuters.com/x") is True
    assert is_valid_url("http://example.com/x") is True
    assert is_valid_url("ftp://example.com/x") is False
    assert is_valid_url("not a url") is False
    assert is_valid_url("") is False


def test_missing_timestamp_article_is_treated_as_stale():
    now = datetime.now(timezone.utc)
    a = _article(published_at=None)
    assert is_stale(a, now) is True  # cannot verify recency -> excluded, never assumed fresh


def test_stale_article_older_than_developing_window_rejected():
    now = datetime.now(timezone.utc)
    a = _article(published_at=now - timedelta(hours=100))
    assert is_stale(a, now) is True


def test_fresh_article_not_stale():
    now = datetime.now(timezone.utc)
    a = _article(published_at=now - timedelta(hours=1))
    assert is_stale(a, now) is False


def test_validate_rejects_bad_url_and_keeps_good_one():
    now = datetime.now(timezone.utc)
    good = _article(link="https://www.reuters.com/good")
    bad = _article(link="javascript:alert(1)")
    kept, stats = validate([good, bad], now=now)
    assert len(kept) == 1
    assert kept[0] is good
    assert stats["rejected_bad_url"] == 1


def test_validate_rejects_off_topic_celebrity_content():
    now = datetime.now(timezone.utc)
    celeb = _article(title="Kardashian box office premiere news")
    kept, stats = validate([celeb], now=now)
    assert kept == []
    assert stats["rejected_off_topic"] == 1


def test_validate_empty_input_yields_empty_output_not_error():
    kept, stats = validate([])
    assert kept == []
    assert stats["kept"] == 0


def test_strip_html_removes_tags_and_entities():
    dirty = '<a href="x">Some &amp; text</a>&nbsp;&nbsp;<font color="#000">WSJ</font>'
    clean = strip_html(dirty)
    assert "<a" not in clean and "<font" not in clean
    assert "Some & text" in clean
    assert "WSJ" in clean
