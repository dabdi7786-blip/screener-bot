"""
Validation/normalization layer (spec sections 6-7): URL validation,
staleness rejection, missing-timestamp handling. Nothing here invents
or repairs data -- an article that fails validation is dropped, never
patched with a guess.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from news_brief.models import RawArticle
from news_brief.textutil import kw_in as _kw_in
from news_brief.textutil import strip_html

PRIMARY_WINDOW_HOURS = 24
DEVELOPING_WINDOW_HOURS = 72  # older items allowed only if still materially relevant (rank.py decides "still relevant")

_EXCLUDE_KEYWORDS = (
    "celebrity", "kardashian", "royal wedding", "box office", "premiere",
    "football score", "basketball score", "world cup final score",
)


def is_valid_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https") and bool(parsed.netloc)
    except Exception:
        return False


def is_stale(article: RawArticle, now: datetime, max_hours: int = DEVELOPING_WINDOW_HOURS) -> bool:
    """True if the article has no usable timestamp, or is older than
    max_hours. An article with published_at=None cannot have its
    recency verified, so it is treated as stale (excluded) rather than
    assumed recent -- spec section 6's 'if a source cannot be verified,
    exclude the item' extended to timing."""
    if article.published_at is None:
        return True
    age = now - article.published_at
    return age > timedelta(hours=max_hours) or age < timedelta(minutes=-10)  # small clock-skew tolerance only


def is_developing(article: RawArticle, now: datetime) -> bool:
    """True if outside the primary 24h window but inside the developing
    window -- must be labeled DEVELOPING, never silently included as fresh."""
    if article.published_at is None:
        return False
    age = now - article.published_at
    return timedelta(hours=PRIMARY_WINDOW_HOURS) < age <= timedelta(hours=DEVELOPING_WINDOW_HOURS)


def is_excluded_topic(title: str, summary: str) -> bool:
    text = f"{title} {summary}".lower()
    return any(_kw_in(kw, text) for kw in _EXCLUDE_KEYWORDS)


def validate(articles: list[RawArticle], now: datetime | None = None) -> tuple[list[RawArticle], dict]:
    """Filters raw articles down to the verifiable, in-window,
    on-topic set. Returns (kept, stats)."""
    now = now or datetime.now(timezone.utc)
    stats = {"input": len(articles), "rejected_no_title_or_link": 0, "rejected_bad_url": 0,
              "rejected_stale_or_no_timestamp": 0, "rejected_off_topic": 0, "kept": 0}

    kept = []
    for a in articles:
        if not a.title or not a.link:
            stats["rejected_no_title_or_link"] += 1
            continue
        if not is_valid_url(a.link):
            stats["rejected_bad_url"] += 1
            continue
        a.summary = strip_html(a.summary)  # Google News descriptions carry raw HTML -- clean before use downstream
        if is_excluded_topic(a.title, a.summary):
            stats["rejected_off_topic"] += 1
            continue
        if is_stale(a, now):
            stats["rejected_stale_or_no_timestamp"] += 1
            continue
        kept.append(a)

    stats["kept"] = len(kept)
    return kept, stats
