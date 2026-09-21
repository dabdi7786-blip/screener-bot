"""
news_brief.sources tests (spec categories: 1 source parsing, 2 malformed
source, 11 partial source failure, 12 retry behavior). No live network
calls -- requests.Session is mocked throughout.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from news_brief.sources import Feed, _fetch_with_retry, fetch_all, parse_rss

_SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>Fed raises interest rates by 25bps</title>
  <link>https://example.com/fed-rate-hike</link>
  <pubDate>Mon, 21 Sep 2026 08:00:00 GMT</pubDate>
  <description>The Federal Reserve raised rates.</description>
</item>
</channel></rss>"""

_GOOGLE_NEWS_STYLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
<item>
  <title>Oil slips on demand worries - Reuters</title>
  <link>https://news.google.com/rss/articles/abc123</link>
  <pubDate>Mon, 21 Sep 2026 09:00:00 GMT</pubDate>
  <description>Some description</description>
  <source url="https://www.reuters.com">Reuters</source>
</item>
</channel></rss>"""

_TEST_FEED = Feed("https://example.com/feed.xml", "Example Wire", "https://example.com", 1)


def test_parse_rss_basic_item_fields():
    articles = parse_rss(_SAMPLE_RSS, _TEST_FEED, datetime.now(timezone.utc))
    assert len(articles) == 1
    a = articles[0]
    assert a.title == "Fed raises interest rates by 25bps"
    assert a.link == "https://example.com/fed-rate-hike"
    assert a.published_at is not None
    assert a.published_at.year == 2026
    assert a.source_name == "Example Wire"
    assert a.tier == 1


def test_parse_rss_uses_google_news_source_element():
    articles = parse_rss(_GOOGLE_NEWS_STYLE_RSS, _TEST_FEED, datetime.now(timezone.utc))
    assert articles[0].source_name == "Reuters"
    assert articles[0].source_url == "https://www.reuters.com"


def test_parse_rss_bom_prefixed_xml_does_not_crash():
    """Regression: Federal Reserve's real feed has a UTF-8 BOM before
    <?xml -- observed live to raise ET.ParseError when fed as decoded
    str; bytes input handles it correctly."""
    bom_xml = "﻿".encode("utf-8") + _SAMPLE_RSS.replace(b'encoding="UTF-8"', b'encoding="utf-8"')
    articles = parse_rss(bom_xml, _TEST_FEED, datetime.now(timezone.utc))
    assert len(articles) == 1


def test_parse_rss_malformed_xml_returns_empty_not_raises():
    malformed = b"<rss><channel><item><title>Broken"  # truncated, invalid XML
    articles = parse_rss(malformed, _TEST_FEED, datetime.now(timezone.utc))
    assert articles == []


def test_parse_rss_skips_items_missing_title_or_link():
    xml = b"""<?xml version="1.0"?><rss version="2.0"><channel>
    <item><title>Has both</title><link>https://example.com/a</link></item>
    <item><title>No link</title></item>
    <item><link>https://example.com/b</link></item>
    </channel></rss>"""
    articles = parse_rss(xml, _TEST_FEED, datetime.now(timezone.utc))
    assert len(articles) == 1
    assert articles[0].title == "Has both"


def test_parse_rss_missing_pubdate_yields_none_not_guessed():
    xml = b"""<?xml version="1.0"?><rss version="2.0"><channel>
    <item><title>No date</title><link>https://example.com/a</link></item>
    </channel></rss>"""
    articles = parse_rss(xml, _TEST_FEED, datetime.now(timezone.utc))
    assert articles[0].published_at is None


def test_fetch_with_retry_succeeds_after_transient_failures():
    session = MagicMock()
    ok_response = MagicMock(content=_SAMPLE_RSS)
    ok_response.raise_for_status.return_value = None
    session.get.side_effect = [ConnectionError("boom"), ConnectionError("boom"), ok_response]
    with patch("news_brief.sources.time.sleep"):
        result = _fetch_with_retry(_TEST_FEED.url, session)
    assert result == _SAMPLE_RSS
    assert session.get.call_count == 3


def test_fetch_with_retry_gives_up_after_max_attempts_returns_none():
    session = MagicMock()
    session.get.side_effect = ConnectionError("persistent failure")
    with patch("news_brief.sources.time.sleep"):
        result = _fetch_with_retry(_TEST_FEED.url, session)
    assert result is None
    assert session.get.call_count == 5  # MAX_RETRIES


def test_fetch_all_partial_failure_continues_with_available_feeds():
    """One dead feed must not abort the batch (spec section 17)."""
    session = MagicMock()
    ok_response = MagicMock(content=_SAMPLE_RSS)
    ok_response.raise_for_status.return_value = None

    def fake_get(url, headers=None, timeout=None):
        if "google.com" in url:
            raise ConnectionError("dead feed")
        return ok_response

    session.get.side_effect = fake_get
    with patch("news_brief.sources.time.sleep"):
        articles, stats = fetch_all(session=session)

    assert stats["feeds_failed"] > 0
    assert stats["feeds_succeeded"] > 0
    assert len(articles) > 0  # still produced usable output from the feeds that worked
