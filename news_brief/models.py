"""Data shapes for the news brief pipeline. Plain dataclasses -- no ORM,
no app.data, fully independent of the research/production DB."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

CATEGORIES = ("WORLD", "MIDDLE_EAST", "RUSSIA", "OIL_GAS", "URANIUM_NUCLEAR", "AI_SEMIS")

CATEGORY_LABELS = {
    "WORLD": "🌍 МИР",
    "MIDDLE_EAST": "🔥 БЛИЖНИЙ ВОСТОК",
    "RUSSIA": "🇷🇺 РОССИЯ",
    "OIL_GAS": "🛢 НЕФТЬ И ГАЗ",
    "URANIUM_NUCLEAR": "☢️ УРАН / АЭС",
    "AI_SEMIS": "🤖 ИИ / ПОЛУПРОВОДНИКИ",
}


@dataclass
class RawArticle:
    """One real, fetched feed item. Every field is either taken directly
    from the source feed or computed deterministically (retrieved_at) --
    nothing here is ever generated/invented."""
    source_name: str
    source_url: str | None
    title: str
    link: str
    published_at: datetime | None   # None if the source omitted/malformed it -- never guessed
    summary: str
    retrieved_at: datetime
    feed_url: str
    tier: int  # 1 or 2, assigned by the feed's own configured tier (sources.py)


@dataclass
class NewsCluster:
    """One or more RawArticles describing the same real-world event,
    merged by dedupe.py. `title`/`link`/`summary` are taken verbatim
    from the representative (highest-tier, earliest) source -- never
    rewritten or summarized by any generative process."""
    title: str
    link: str
    summary: str
    published_at: datetime | None
    sources: list[RawArticle] = field(default_factory=list)
    category: str | None = None
    market_impact: dict[str, str] = field(default_factory=dict)  # {"Oil": "HIGH", ...}
    developing: bool = False  # older than the primary window but still materially relevant

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def best_tier(self) -> int:
        return min((s.tier for s in self.sources), default=2)


@dataclass
class BriefingResult:
    briefing_id: str
    generated_at: datetime
    key_highlights: list[NewsCluster]
    categories: dict[str, list[NewsCluster]]
    market_impact_map: dict[str, str]
    watchlist: list[tuple[str, str]]  # (ticker, reason)
    all_clusters: list[NewsCluster]
    stats: dict  # fetch/accept/reject counters for logging
