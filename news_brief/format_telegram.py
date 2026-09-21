"""
Telegram HTML formatting (spec sections 12-16). Builds the exact
template structure -- header/highlights, per-category sections, market
impact map, watchlist, sources -- and splits into <=3 messages, each
under Telegram's 4096-char limit, never splitting a single item across
messages.

Real, verbatim-fetched headlines/source titles are displayed in Russian
via an injected `translate` callable (see news_brief/translate.py) --
`build_messages(result, translate=...)`. `translate=None` (the default,
and what every test uses) leaves text untouched, so tests never depend
on network/translation behavior.
"""
from __future__ import annotations

from html import escape
from typing import Callable

from news_brief.models import CATEGORY_LABELS, NewsCluster

TELEGRAM_MAX_CHARS = 4096
_SAFETY_MARGIN = 200  # leave headroom so HTML-entity expansion never overflows the hard limit

EMPTY_CATEGORY_TEXT = "Нет значимых подтверждённых событий за период."

# Display-only Russian labels for the asset tags classify.py assigns
# internally (English keys there are asserted by tests and used as
# dict keys for dedup/severity logic -- translating only at render time
# keeps that internal contract untouched).
_ASSET_LABELS_RU = {
    "Oil/Shipping": "Нефть/Судоходство", "Shipping": "Судоходство",
    "Oil/Energy infrastructure": "Нефть/Энергоинфраструктура", "Energy/Trade": "Энергетика/Торговля",
    "Oil": "Нефть", "Oil/Refining": "Нефть/Переработка", "Oil/Gas": "Нефть/Газ",
    "Uranium": "Уран", "Uranium/Nuclear fuel": "Уран/Ядерное топливо",
    "Semiconductors": "Полупроводники", "AI/Data centers": "ИИ/Дата-центры",
    "Broad equities": "Широкий рынок акций",
}

_Translate = Callable[[str], str]


def _fmt_link(cluster: NewsCluster, translate: _Translate | None = None) -> str:
    display_title = translate(cluster.title) if translate else cluster.title
    title = escape(display_title)
    return f'<a href="{escape(cluster.link, quote=True)}">{title}</a>'


def _fmt_impact(cluster: NewsCluster) -> str:
    if not cluster.market_impact:
        return ""
    parts = ", ".join(f"{_ASSET_LABELS_RU.get(asset, asset)}: {level}" for asset, level in cluster.market_impact.items())
    return f"\n   <i>Влияние на рынок: {escape(parts)}</i>"


def _fmt_item(cluster: NewsCluster, translate: _Translate | None = None) -> str:
    tag = " [РАЗВИВАЕТСЯ]" if cluster.developing else ""
    line = f"• {_fmt_link(cluster, translate)}{tag}"
    if cluster.source_count > 1:
        names = ", ".join(sorted({s.source_name for s in cluster.sources}))
        line += f"\n   <i>Источники: {escape(names)}</i>"
    line += _fmt_impact(cluster)
    return line


def format_highlights(highlights: list[NewsCluster], generated_at, translate: _Translate | None = None) -> str:
    header = f"🌅 <b>УТРЕННЯЯ СВОДКА РЫНКА</b>\n{generated_at.strftime('%d %b %Y')} | {generated_at.strftime('%H:%M')} UTC"
    if not highlights:
        return header + "\n\n🔥 <b>КЛЮЧЕВОЕ</b>\nНе удалось получить подтверждённые новости за период."
    body = "\n".join(f"• {_fmt_link(c, translate)}" for c in highlights)
    return f"{header}\n\n🔥 <b>КЛЮЧЕВОЕ</b>\n{body}"


def format_category_section(category: str, items: list[NewsCluster], translate: _Translate | None = None) -> str:
    label = CATEGORY_LABELS[category]
    if not items:
        return f"{label}\n{EMPTY_CATEGORY_TEXT}"
    body = "\n\n".join(_fmt_item(c, translate) for c in items)
    return f"{label}\n{body}"


def format_market_impact_map(impact_map: dict[str, str]) -> str:
    icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
    lines = ["━━━━━━━━━━━━━━━━", "📊 <b>КАРТА ВЛИЯНИЯ НА РЫНОК</b>", ""]
    if not impact_map:
        lines.append("Недостаточно данных для карты влияния за период.")
    else:
        for category in CATEGORY_LABELS:
            if category in impact_map:
                level = impact_map[category]
                lines.append(f"{CATEGORY_LABELS[category]}  {icon.get(level, '⚪')} {level}")
    lines.append("━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


def format_watchlist(watchlist: list[tuple[str, str]]) -> str:
    if not watchlist:
        return "👀 <b>НАБЛЮДАТЬ СЕГОДНЯ</b>\nНет тикеров с материально значимыми новостями за период."
    lines = ["👀 <b>НАБЛЮДАТЬ СЕГОДНЯ</b>"]
    for ticker, reason in watchlist:
        lines.append(f"{escape(ticker)} — {escape(reason)}")
    return "\n".join(lines)


def format_sources_lines(all_selected: list[NewsCluster], translate: _Translate | None = None) -> list[str]:
    """Returns [header, entry1, entry2, ...] -- one atomic line per
    source, so the caller can distribute them across as many messages
    as genuinely needed without ever truncating the citation list
    (spec: every item must be traceable to a real source)."""
    seen: dict[str, str] = {}
    for cluster in all_selected:
        for s in cluster.sources:
            key = s.link
            if key not in seen:
                display_title = translate(s.title) if translate else s.title
                seen[key] = f"{escape(s.source_name)} — {escape(display_title)}"
    if not seen:
        return ["🔗 <b>ИСТОЧНИКИ</b>", "(нет)"]
    lines = ["🔗 <b>ИСТОЧНИКИ</b>"]
    for i, (link, label) in enumerate(seen.items(), 1):
        lines.append(f'{i}. <a href="{escape(link, quote=True)}">{label}</a>')
    return lines


def _pack_atoms(atoms: list[str], joiner: str = "\n\n") -> list[str]:
    """Greedily packs atomic chunks (sections OR individual lines) into
    as many <=4096-char messages as needed. Never splits a single atom
    -- unbounded message count on purpose: dropping real content
    (a source citation, a news item) is worse than sending a 4th or 5th
    message."""
    messages: list[str] = []
    current = ""
    for atom in atoms:
        candidate = f"{current}{joiner}{atom}" if current else atom
        if len(candidate) > TELEGRAM_MAX_CHARS - _SAFETY_MARGIN and current:
            messages.append(current)
            current = atom
        else:
            current = candidate
    if current:
        messages.append(current)
    return messages


def build_messages(result, translate: _Translate | None = None) -> list[str]:
    """result: BriefingResult. Returns Telegram-ready HTML message
    strings -- 3 in the common case (spec section 15's recommended
    structure), more only if a section (most likely SOURCES) is too
    long to fit even on its own.

    `translate`: optional callable(str) -> str applied to real headline/
    source-title text for Russian display (news_brief.translate). Left
    as None by default and by every test -- template chrome (category
    labels, section headers) is already Russian regardless."""
    highlights_section = format_highlights(result.key_highlights, result.generated_at, translate)
    world = format_category_section("WORLD", result.categories.get("WORLD", []), translate)
    mideast = format_category_section("MIDDLE_EAST", result.categories.get("MIDDLE_EAST", []), translate)
    russia = format_category_section("RUSSIA", result.categories.get("RUSSIA", []), translate)
    oil = format_category_section("OIL_GAS", result.categories.get("OIL_GAS", []), translate)
    uranium = format_category_section("URANIUM_NUCLEAR", result.categories.get("URANIUM_NUCLEAR", []), translate)
    ai = format_category_section("AI_SEMIS", result.categories.get("AI_SEMIS", []), translate)
    impact_map = format_market_impact_map(result.market_impact_map)
    watchlist = format_watchlist(result.watchlist)
    all_selected = [c for items in result.categories.values() for c in items]
    source_lines = format_sources_lines(all_selected, translate)

    # Recommended structure per spec section 15: msg1 = highlights+world+mideast,
    # msg2 = russia+oil+uranium+ai, msg3+ = impact map + watchlist + sources.
    # Sources are packed as individual lines (not one giant block) so a
    # long citation list can spill into extra messages without ever
    # truncating a real source (see _pack_atoms' docstring).
    third_group_atoms = [impact_map, watchlist, "\n".join(source_lines)]

    result_messages: list[str] = []
    result_messages.extend(_pack_atoms([highlights_section, world, mideast]))
    result_messages.extend(_pack_atoms([russia, oil, uranium, ai]))
    if len(third_group_atoms[-1]) > TELEGRAM_MAX_CHARS - _SAFETY_MARGIN:
        # sources alone don't fit in one message -- split at line boundaries
        result_messages.extend(_pack_atoms([impact_map, watchlist]))
        result_messages.extend(_pack_atoms(source_lines, joiner="\n"))
    else:
        result_messages.extend(_pack_atoms(third_group_atoms))

    return result_messages
