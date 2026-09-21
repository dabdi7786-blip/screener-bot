# Overnight News Brief — Production Audit

Written before implementation, per task instruction. Documents the
existing production architecture, the integration point chosen, and
why — so the new job can be judged against real constraints, not
assumptions.

## 1. Existing architecture (as found)

- **Two live GitHub Actions workflows**: `.github/workflows/scan.yml`
  (cron `0 5 * * 1-5`, comment states this is **08:00 UTC+3**,
  weekdays) runs `screener_bot.py`; `.github/workflows/bot_poll.yml`
  (cron `*/10 * * * *`) runs `bot_server.py`. Both already commit
  updated state back to `main` (`[skip ci]` commits) and deploy
  `docs/` to GitHub Pages. Both were hardened for push-retry +
  failure-alert reliability in the immediately preceding session (see
  `docs/production_deployment_audit.md`).
- **Telegram send pattern**: both `screener_bot.py::tg_send()` and
  `bot_server.py::tg_send()` independently implement the same shape —
  `requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
  json={"chat_id":..., "text":..., "parse_mode":"HTML"}, timeout=10)`,
  chunked at 4096 chars (Telegram's hard limit), with the token/chat-id
  read from `TELEGRAM_TOKEN`/`TELEGRAM_CHAT_ID` env vars
  (`os.getenv`, loaded via `python-dotenv`'s `load_dotenv()` for local
  runs; GitHub Actions injects them from `secrets.TELEGRAM_TOKEN`/
  `secrets.TELEGRAM_CHAT_ID` directly as step `env:`). No shared
  Telegram utility module exists — each script duplicates `tg_send`
  independently. This new job adds a **third**, independent
  implementation rather than importing from either script (importing
  from `screener_bot.py` would pull in its entire ~900-line module,
  including the stock-scoring logic this task must not touch; the
  duplication cost of one ~15-line HTTP POST helper is lower than that
  coupling cost).
- **Secrets**: only `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID` today,
  sourced from GitHub Secrets in CI and `.env` locally. No news-API key
  exists or is assumed — the source strategy (section 4 below) is
  deliberately built entirely on free, keyless public RSS feeds so no
  new secret is required for the news brief itself.
- **Timezone**: no `zoneinfo`/`pytz` usage anywhere in production
  code; the only explicit convention is `scan.yml`'s own comment,
  `cron: "0 5 * * 1-5" # 08:00 (UTC+3) пн-пт` — i.e. the repository's
  established convention is a **fixed UTC+3 offset**, not a DST-aware
  named zone. This job follows the same convention rather than
  introducing a new one.
- **State/dedup pattern**: `rates_fetcher.py` (`HISTORY_FILE =
  last_rates.json`, `load_previous()`/`save_current()`) and
  `bot_server.py` (`last_scan.json`) both persist small JSON state
  files at the repo root, committed by the workflow's existing "commit
  updated state" step. This job reuses the exact same pattern
  (`news_brief_state.json`) rather than inventing a new persistence
  mechanism (e.g. no database — consistent with `screener_bot.py`/
  `bot_server.py` not touching `app.data` at all, confirmed in the
  prior audit).
- **Existing news functionality**: none in production. The only
  "news"-named code in the repository is `app/signals/catalyst.py`
  (Phase 3 research signal engine, `app/` package) — a per-ticker
  yfinance headline fetcher for the research signal score. It is
  architecturally and semantically unrelated (ticker-specific catalyst
  scoring, not macro/geopolitical briefing) and, per this task's
  explicit constraint, is **not reused or connected to**.
- **Dependencies already available**: `requests`, `lxml`,
  `beautifulsoup4` (RSS/XML parsing needs nothing beyond these —
  confirmed by hand-parsing real feeds during this audit, see section
  4). **No new dependency is added to `requirements.txt`.**

## 2. Proposed integration point

A new, fully independent top-level package `news_brief/` (sibling to
`app/`, `screener_v2/`, not nested under either) plus a single
entrypoint script `news_brief_run.py` at the repo root, invoked by a
**new, separate workflow** `.github/workflows/overnight_news.yml`.

Rejected alternative: adding a step to the existing `scan.yml`. Rejected
because the task requires the brief to be "independent from the stock
screener" and explicitly states a screener failure must not block the
brief and vice versa — a shared job/workflow would couple their failure
domains (one `timeout-minutes` budget, one `concurrency` group, one
process). A separate workflow with its own `concurrency` group gives
true isolation at the infrastructure level, not just a try/except.

## 3. Files touched by this task

**New files only** — nothing existing is modified except as noted:

- `news_brief/__init__.py`, `sources.py`, `models.py`, `normalize.py`,
  `dedupe.py`, `classify.py`, `rank.py`, `briefing.py`,
  `format_telegram.py`, `telegram.py`, `state.py`
- `news_brief_run.py` (root entrypoint)
- `.github/workflows/overnight_news.yml` (new workflow)
- `tests/test_news_brief_*.py`
- `docs/overnight_news_brief_audit.md` (this file),
  `docs/overnight_news_brief.md`
- `news_brief_state.json` will be **created at runtime** by the first
  execution (like `last_rates.json`/`last_scan.json` were) — not
  created by this commit, to avoid committing a placeholder that could
  be confused with real state.

**Explicitly not modified**: `scan.yml`, `bot_poll.yml`,
`screener_bot.py`, `bot_server.py`, `rates_fetcher.py`,
`dashboard_generator.py`, `requirements.txt`, anything under `app/`,
`app/signals/production_gate.py`, `data/screener.db`.

## 4. Source strategy (verified live before being hardcoded)

Every candidate feed URL below was fetched live during this audit
(`curl`, HTTP status + content inspection) before being written into
code — none are assumed or invented. Reuters and AP no longer expose
public RSS (`reuters.com/world/rss` → 401, `apnews.com/rss` → 403,
confirmed live); OPEC's feed likewise 403s. Rather than inventing
workarounds for those, real Reuters/AP-bylined coverage is obtained
through Google News' public RSS search, scoped with `site:` filters to
reputable domains — confirmed live to return genuine
`<source>Reuters https://www.reuters.com</source>` attribution, real
headlines, and real `pubDate`s; the `<link>` is a Google News redirect
URL (not fabricated, resolves to the real article) — documented here
explicitly since it's the one place the "real URL" isn't the
publisher's own domain.

| Category | Direct feeds (Tier 1/2, verified live) | Google News site-scoped queries |
|---|---|---|
| WORLD | Federal Reserve press releases (`federalreserve.gov/feeds/press_all.xml`), SEC press releases (`sec.gov/news/pressreleases.rss`), BBC World (`feeds.bbci.co.uk/news/world/rss.xml`) | general world/economy, `site:reuters.com OR site:apnews.com` |
| MIDDLE EAST | — (no reliable direct official feed found) | Israel/Iran/Gaza/Houthi/Hormuz keywords, scoped to reuters.com/apnews.com/bbc.com |
| RUSSIA | — | Russia/Ukraine/sanctions keywords, scoped to reuters.com/apnews.com/bbc.com |
| OIL & GAS | EIA Today in Energy (`eia.gov/rss/todayinenergy.xml`), BBC Business (`feeds.bbci.co.uk/news/business/rss.xml`) | OPEC/Brent/WTI/Hormuz keywords, scoped to reuters.com/apnews.com |
| URANIUM/NUCLEAR | IAEA top news (`iaea.org/feeds/topnews`), World Nuclear News (`world-nuclear-news.org/rss`) | uranium/Cameco/Kazatomprom keywords, scoped to reuters.com/apnews.com |
| AI/SEMIS | BBC Business | Nvidia/AMD/TSMC/AI chip keywords, scoped to reuters.com/apnews.com/wsj.com/ft.com/bloomberg.com |

No LLM is used anywhere in this pipeline. Category classification,
ranking, deduplication, and market-impact tagging are all deterministic
keyword/rule-based functions over the real fetched title+summary text
— this is a deliberate architecture decision, not a limitation: an LLM
summarizer would reintroduce exactly the fabrication risk (invented
headlines, invented urls, invented dates) the task spends nine sections
warning against, and no LLM API key exists in this repo's secrets today
regardless.

## 5. Failure behavior (design, detailed in `docs/overnight_news_brief.md`)

Independent `concurrency` group from the screener workflows. Per-feed
fetch failures are caught individually (one dead feed never aborts the
run — same "never raises outward" discipline as `rates_fetcher.py`).
Zero verified items across all sources → send the explicit
"не удалось получить" fallback message, never fabricate. Telegram send
failure → retried, then the workflow fails loudly (no silent success).
Full detail in the final documentation (section 25 of the task spec).
