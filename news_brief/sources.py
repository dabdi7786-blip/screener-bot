"""
Feed definitions and fetching. Every URL below was fetched and verified
live (HTTP 200, real RSS content) during the production audit --
docs/overnight_news_brief_audit.md section 4 -- before being hardcoded
here. None are invented.

Reuters/AP/OPEC no longer expose public RSS (verified 401/403/403 live)
-- their coverage is obtained instead through Google News' public RSS
search, scoped with `site:` filters to reputable domains. That feed's
<source> element gives the real publisher name/URL and the <link> is a
real (non-fabricated) Google News redirect that resolves to the actual
article -- documented explicitly since it's the one non-publisher-domain
link in this pipeline.
"""
from __future__ import annotations

import logging
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests

from news_brief.models import RawArticle

log = logging.getLogger("news_brief.sources")

USER_AGENT = "Mozilla/5.0 (compatible; OvernightNewsBrief/1.0; +https://github.com/dabdi7786-blip/screener-bot)"
REQUEST_TIMEOUT = 15
MAX_RETRIES = 5
BACKOFF_BASE = 2
BACKOFF_CAP = 32


@dataclass(frozen=True)
class Feed:
    url: str
    source_name: str
    source_url: str | None
    tier: int
    category_hint: str | None = None  # advisory only -- classify.py re-classifies independently


DIRECT_FEEDS: tuple[Feed, ...] = (
    Feed("https://www.federalreserve.gov/feeds/press_all.xml", "Federal Reserve", "https://www.federalreserve.gov", 1, "WORLD"),
    Feed("https://www.sec.gov/news/pressreleases.rss", "SEC", "https://www.sec.gov", 1, "WORLD"),
    Feed("https://www.iaea.org/feeds/topnews", "IAEA", "https://www.iaea.org", 1, "URANIUM_NUCLEAR"),
    Feed("https://www.eia.gov/rss/todayinenergy.xml", "EIA", "https://www.eia.gov", 1, "OIL_GAS"),
    Feed("http://feeds.bbci.co.uk/news/world/rss.xml", "BBC", "https://www.bbc.com", 2, "WORLD"),
    Feed("http://feeds.bbci.co.uk/news/business/rss.xml", "BBC Business", "https://www.bbc.com", 2, "WORLD"),
    Feed("https://world-nuclear-news.org/rss", "World Nuclear News", "https://world-nuclear-news.org", 2, "URANIUM_NUCLEAR"),
)

# Google News RSS search, scoped to reputable domains via `site:` OR-filters.
# Each entry: (category_hint, query). category_hint is advisory only.
_REPUTABLE_DOMAINS = "site:reuters.com OR site:apnews.com OR site:wsj.com OR site:ft.com OR site:bloomberg.com OR site:cnbc.com OR site:bbc.com"

GOOGLE_NEWS_QUERIES: tuple[tuple[str, str], ...] = (
    ("WORLD", f"world economy central bank ({_REPUTABLE_DOMAINS})"),
    ("MIDDLE_EAST", f"Israel Iran Gaza Houthi Hormuz ({_REPUTABLE_DOMAINS})"),
    ("RUSSIA", f"Russia Ukraine sanctions ({_REPUTABLE_DOMAINS})"),
    ("OIL_GAS", f"OPEC Brent WTI oil ({_REPUTABLE_DOMAINS})"),
    ("URANIUM_NUCLEAR", f"uranium Cameco Kazatomprom nuclear fuel ({_REPUTABLE_DOMAINS})"),
    ("AI_SEMIS", f"Nvidia AMD TSMC AI chips semiconductor ({_REPUTABLE_DOMAINS})"),
)


def google_news_feed(query: str) -> Feed:
    url = f"https://news.google.com/rss/search?q={quote(query)}%20when:2d&hl=en-US&gl=US&ceid=US:en"
    return Feed(url, "Google News (site-scoped)", "https://news.google.com", 2, None)


def _parse_pubdate(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text.strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None  # never guess a date


def _fetch_with_retry(url: str, session: requests.Session) -> bytes | None:
    """Never raises -- returns None on total failure so one dead feed
    can't abort the whole run (spec section 17, partial source failure).
    Returns raw bytes (not requests' guessed-encoding .text) so
    ET.fromstring can use the XML prolog's own encoding declaration and
    handle a leading UTF-8 BOM correctly -- observed live on the
    Federal Reserve feed, which requests' .text mis-decoded into a
    literal BOM character that made ET.fromstring reject the whole
    document as malformed."""
    delay = BACKOFF_BASE
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            log.warning("fetch attempt %d/%d failed for %s: %s", attempt, MAX_RETRIES, url, type(e).__name__)
            if attempt == MAX_RETRIES:
                return None
            time.sleep(min(delay, BACKOFF_CAP))
            delay *= 2
    return None


def parse_rss(xml_content: bytes | str, feed: Feed, retrieved_at: datetime) -> list[RawArticle]:
    """Parses RSS 2.0 <item> elements. Accepts raw bytes (preferred --
    lets ET honor the XML prolog's own encoding + strip a BOM) or str.
    Returns [] on malformed XML (never raises, never fabricates a
    partial item)."""
    try:
        root = ET.fromstring(xml_content)
    except Exception as e:
        log.warning("malformed XML from %s: %s: %s", feed.url, type(e).__name__, e)
        return []

    articles = []
    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue  # spec section 6: no headline/URL, no item
        summary = (item.findtext("description") or "").strip()
        pub_dt = _parse_pubdate(item.findtext("pubDate"))

        source_el = item.find("source")
        source_name = feed.source_name
        source_url = feed.source_url
        if source_el is not None and source_el.text:
            source_name = source_el.text.strip()
            source_url = source_el.get("url") or source_url

        articles.append(RawArticle(
            source_name=source_name, source_url=source_url, title=title, link=link,
            published_at=pub_dt, summary=summary, retrieved_at=retrieved_at,
            feed_url=feed.url, tier=feed.tier,
        ))
    return articles


def fetch_all(session: requests.Session | None = None) -> tuple[list[RawArticle], dict]:
    """Fetches every configured feed. Returns (articles, stats). A dead
    feed is logged and skipped -- never aborts the batch."""
    session = session or requests.Session()
    feeds = list(DIRECT_FEEDS) + [google_news_feed(q) for _, q in GOOGLE_NEWS_QUERIES]

    all_articles: list[RawArticle] = []
    stats = {"feeds_attempted": len(feeds), "feeds_succeeded": 0, "feeds_failed": 0, "raw_items": 0}

    for feed in feeds:
        retrieved_at = datetime.now(timezone.utc)
        content = _fetch_with_retry(feed.url, session)
        if content is None:
            stats["feeds_failed"] += 1
            continue
        items = parse_rss(content, feed, retrieved_at)
        stats["feeds_succeeded"] += 1
        stats["raw_items"] += len(items)
        all_articles.extend(items)

    return all_articles, stats
