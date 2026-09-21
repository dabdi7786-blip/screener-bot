# Overnight / Global News Brief

Independent, information-only Telegram briefing summarizing the last
12-24h (with clearly labeled `[DEVELOPING]` items up to 72h) across six
market-relevant categories. Not a trading signal. Does not touch
`production_gate.py`, `allow_production`, IBKR, or `app/*`.

## Architecture

```
FETCH (news_brief/sources.py)
  -> NORMALIZE (news_brief/normalize.py)
  -> DEDUPLICATE (news_brief/dedupe.py)
  -> CLASSIFY (news_brief/classify.py)
  -> RANK (news_brief/rank.py)
  -> GENERATE BRIEF (news_brief/briefing.py)
  -> VALIDATE / FORMAT (news_brief/format_telegram.py)
  -> TELEGRAM (news_brief/telegram.py)
  -> LOG / ARTIFACT (news_brief_run.py + workflow artifact upload)
```

Entry point: `news_brief_run.py` (repo root), invoked by
`.github/workflows/overnight_news.yml`. Fully independent of
`screener_bot.py`/`bot_server.py` -- separate workflow file, separate
`concurrency` group, no shared imports. A failure in either pipeline
cannot affect the other (see `docs/overnight_news_brief_audit.md` for
the reasoning).

## Sources (real, live-verified -- no LLM, no fabrication)

No LLM is used anywhere. Category assignment, deduplication, ranking,
and market-impact tagging are deterministic, keyword/rule-based
functions over real fetched title+summary text.

**Direct feeds** (fetched as-is): Federal Reserve press releases, SEC
press releases, IAEA top news, EIA "Today in Energy", BBC World, BBC
Business, World Nuclear News.

**Google News RSS, site-scoped** (Reuters/AP no longer expose public
RSS -- confirmed live, 401/403): per-category keyword queries restricted
to `site:reuters.com OR site:apnews.com OR site:wsj.com OR site:ft.com
OR site:bloomberg.com OR site:cnbc.com OR site:bbc.com`. Each item's
real publisher is taken from the feed's own `<source>` element; the
`<link>` is a real (non-fabricated) Google News redirect that resolves
to the actual article.

Every published URL, headline, and timestamp is taken verbatim from the
source feed. An item with no title/link is dropped. An item with no
parseable timestamp is dropped (treated as unverifiable, never assumed
recent).

## Schedule / timezone

Cron `30 4 * * *` = **07:30 daily, fixed UTC+3** -- matches the
repository's existing convention (`scan.yml`'s own comment: `0 5 * * 1-5
# 08:00 (UTC+3)`). Runs every day (not weekdays-only like the screener)
since geopolitical/oil/nuclear developments aren't confined to trading
days, and Monday's brief should cover the full weekend window via the
`[DEVELOPING]` allowance. `workflow_dispatch` supports a `force_send`
boolean input for manual testing.

## Categories

🌍 WORLD, 🔥 MIDDLE EAST, 🇷🇺 RUSSIA, 🛢 OIL & GAS, ☢️ URANIUM/NUCLEAR,
🤖 AI/SEMICONDUCTORS. Target 1-4 items each (targets, not quotas --
`news_brief/rank.py::CATEGORY_TARGETS`); an empty category renders
"Нет значимых подтверждённых событий за период." rather than being
padded. Keyword lists are taken directly from the task's own tracking
lists per category (`news_brief/classify.py`).

**Classification requires a TITLE match** for the five specific
categories (not summary-only) -- Google News RSS descriptions were
found live to sometimes bundle unrelated "full coverage" text, which
mis-routed off-topic items via summary-only matching. An item matching
nothing (including WORLD's own keywords) is **excluded**, not defaulted
into WORLD -- this is the mechanism that keeps celebrity/sports/
entertainment content out.

All keyword matching is **word-boundary-aware**
(`news_brief/textutil.py::kw_in`), not naive substring containment --
found live that plain substring matching classified an unrelated
private-equity story as RUSSIA because "computing" contains "putin".

## Deduplication

Greedy title-similarity clustering (`difflib.SequenceMatcher`, threshold
0.62) within a 48h window, so Reuters+AP+BBC coverage of the same event
becomes one Telegram bullet citing all sources, not three separate
bullets. The representative headline/link is the highest-tier, earliest
source.

## Market impact / watchlist

Both derived deterministically from the real keyword matches already
found during classification -- never an invented score.
`👀 WATCH TODAY` only lists a ticker when a selected, real news item
actually mentions that company (`news_brief/briefing.py::_TICKER_HINTS`).
Neither ever emits a buy/sell recommendation.

## Failure semantics

| Case | Behavior |
|---|---|
| No sources fetched | Sends `Не удалось получить подтверждённые новости за период.` -- never fabricates |
| Some feeds fail | Continues with available sources; prepends `⚠️ Some sources unavailable...` to message 1 |
| Feed fetch fails | Retried up to 5x, exponential backoff (2/4/8/16/32s capped), then that one feed is skipped -- never aborts the whole run |
| Telegram send fails | Retried up to 5x, same backoff; final failure **raises**, so the workflow fails loudly (never silently succeeds) |
| No LLM is used | N/A by design -- eliminates that whole failure class |

## Telegram format

Up to 3 messages in the common case (spec-recommended structure:
highlights+world+mideast / russia+oil+uranium+ai / impact-map+watchlist+
sources), each ≤4096 chars. A single item/source line is never split
across messages; if the SOURCES list alone is too long to fit, it spills
into additional messages at line boundaries rather than truncating
citations (observed live: a 231-cluster run needed 6 total messages).

## Idempotency

`news_brief/state.py`: `briefing_id = YYYY-MM-DD-AM`, persisted in
`news_brief_state.json` (committed by the workflow, same pattern as
`last_scan.json`/`last_rates.json`). A scheduled run skips sending if
today's `briefing_id` was already recorded. `FORCE_SEND=1` (set by the
workflow's `force_send` dispatch input) sends anyway **without**
updating the persisted record, so manual tests never corrupt the real
daily dedup -- verified live (2026-09-21 smoke test: `FORCE_SEND` sent
successfully and the state-commit step correctly found nothing new to
commit).

## Secrets

`TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID` only -- same GitHub Secrets already
used by `scan.yml`/`bot_poll.yml`. No new secret required (no news-API
key -- the source strategy is entirely free/keyless RSS). Never logged;
`news_brief_run_log.json` (the CI artifact) contains only counts/status/
timing.

## Tests

72 tests across `tests/test_news_brief_*.py`, all fixture/mock-based
(no live network in CI test runs): source parsing, malformed XML
(including a real BOM regression), missing timestamp, duplicate
articles, multi-source event merging, category classification
(including the word-boundary regression), source-tier ranking, stale
rejection, URL validation, empty category, partial source failure,
retry/backoff, Telegram failure, idempotency, message length, Telegram
splitting (including the long-sources-list regression), secret
redaction, deterministic briefing ID, plus end-to-end pipeline and
entrypoint-orchestration integration tests.

## Manual dispatch (operator runbook)

```
gh workflow run "Overnight News Brief" --ref main -f force_send=true
gh run list --workflow=overnight_news.yml --limit 5
gh run view <run-id> --job=<job-id> --log
```

## Rollback

Same pattern as the screener workflows
(`docs/production_deployment_audit.md` section 5): `git revert` the
commit and push, or disable the workflow from the Actions tab
("Disable workflow") to stop the cron without touching code. No
database, no migration, nothing beyond `news_brief_state.json` (a small
JSON file, safe to delete/revert) is affected.
