# Production Deployment Audit — 2026-09-18

Scope: harden the **already-running** production screener pipeline
(`screener_bot.py`, `bot_server.py`, `.github/workflows/scan.yml`,
`.github/workflows/bot_poll.yml`) for reliability. Explicitly out of
scope, per direct instruction: `app/signals/production_gate.py`
(`allow_production` stays `False`), any M4/Phase 7-10 research signal
promotion, and live order execution via IBKR.

## 1. What was already in production before this audit

- **Scheduled Scan** (`scan.yml`): cron `0 5 * * 1-5` (08:00 UTC+3,
  weekdays) + `workflow_dispatch`. Runs `screener_bot.py` — fetches
  ~500 S&P 500 tickers, scores 3 screeners, fetches rates + IBKR
  snapshot, generates the dashboard, sends Telegram digest, deploys to
  GitHub Pages, commits updated CSV/dashboard state.
- **Bot Poll** (`bot_poll.yml`): cron `*/10 * * * *`. Runs
  `bot_server.py` — one-shot pass over Telegram updates (commands
  `/scan`, `/status`, `/ticker`, `/rate`, admin `/allow`/`/block`, etc.).
- Both already deliver to Telegram and publish to GitHub Pages. This
  was true before today — "turning on prod" was not the actual gap.

## 2. Architectural finding: the research codebase (`app/`) is fully isolated from production

Confirmed by direct import search: **none** of `screener_bot.py`,
`bot_server.py`, `dashboard_generator.py`, `rates_fetcher.py`,
`ibkr_fetcher.py`, or `screener1.py` import anything from `app.*`. The
entire Phase 1–10 research program (`app/signals`, `app/pit`,
`app/backtest`, `app/research`, the SQLite file at
`data/screener.db`, Alembic migrations under `app/data/migrations/`)
is **architecturally disconnected** from the live pipeline — it isn't
gated out by convention only, there is no code path connecting them.
Consequences:

- **DB migrations are not applicable to this deployment.** `alembic
  upgrade head` has no effect on anything the scheduled workflows do.
  No migration step was added to either workflow.
- `data/screener.db` (11.9MB, holds this session's Phase 5–10 PIT
  data) is untracked by git and irrelevant to production — left
  as-is, not committed.
- `app/signals/production_gate.py` cannot accidentally affect the live
  bot even if a future change forgot to check it — there's no import
  path from production code into `app.signals` today. Still, per
  instruction, it was not modified.

## 3. Real reliability gap found and fixed

`gh run list` showed one failure in the last 10 scheduled runs:
run `34954550665` (2026-09-15). Root cause (from
`gh run view 34954550665 --log-failed`): the scan itself completed
successfully — all 3 screeners ran, the dashboard was generated, and
(by the time of the failing step) the digest had already gone out.
The **final `git push` step hit a transient GitHub "Internal Server
Error"** with no retry, and the job was marked `failure` on that basis
alone.

**Fix applied**: both `scan.yml` and `bot_poll.yml`'s "Commit updated
state" step now retries `git pull --rebase && git push` up to 5 times
with linear backoff (10s, 20s, 30s, 40s) before failing the job.

## 4. Silent-failure gap found and fixed

In `screener_bot.py`, `main()` called `run_scan()` (the ~500-ticker
fetch + scoring loop — the single most network-exposed, longest-running
part of the whole job) with no error handling. An unhandled exception
there aborted the process before any Telegram message was sent — the
only way to notice was a missing digest or GitHub's own workflow-failure
email (if enabled on the account, not verified here). **Fix applied**:
`run_scan()` is now wrapped in `try/except`; on failure it sends
`⚠️ Скан упал с ошибкой ...` to Telegram (best-effort, itself wrapped
so a Telegram outage can't mask the original error) and then
re-raises, so the workflow still fails loudly in the Actions log/exit
code as before.

A second, workflow-level notification was added to `scan.yml` only
(`if: failure()`, posts a Telegram alert with a link to the failed
run) — **not** added to `bot_poll.yml`, deliberately: that workflow
runs every 10 minutes, and a persistent failure there would spam the
chat with a message every 10 minutes. Its failures remain visible via
the Actions tab and the daily scan's own alert.

`bot_server.py` was audited and needed no change: its `main()` already
wraps each per-update `handle()` call in its own `try/except`, so one
bad command doesn't crash the poll loop or block update-offset
acknowledgement for the rest of the batch.

## 5. Rollback procedure

State (CSVs, `docs/`, `last_scan.json`, `users.json`) is committed
directly to `main` by the bot itself (`[skip ci]` commits). To roll
back a bad deploy:

1. **Bad workflow-file change** (e.g., this audit's edits break
   something): `git revert <commit>` on `main`, or `git checkout
   <last-good-sha> -- .github/workflows/scan.yml .github/workflows/bot_poll.yml`
   and push. The next scheduled run (or a manual
   `workflow_dispatch`) picks up the reverted file immediately — no
   separate "deploy" step exists beyond pushing to `main`.
2. **Bad bot-state commit** (corrupted `users.json`, broken CSV, etc.):
   `git revert <bad-commit-sha>` and push. GitHub Pages redeploys
   automatically from `docs/` on the next successful workflow run (or
   trigger `workflow_dispatch` manually to redeploy immediately without
   waiting for the next cron tick).
3. **Live incident during market hours**: `workflow_dispatch` can be
   disabled from the Actions tab ("Disable workflow") to stop the cron
   entirely without touching any code, then re-enabled once fixed.
4. Nothing in this pipeline writes to a database or external service
   that isn't git/Telegram/GitHub Pages — there is no data-migration
   rollback concern (section 2).

## 6. Explicitly NOT done (per instruction)

- `app/signals/production_gate.py` — untouched. `allow_production`
  remains `False` everywhere it's referenced.
- No M4 / Phase 7 / Phase 8 / Phase 9 / Phase 10 signal was wired into
  `screener_bot.py` or any production path.
- No live order execution added. `ibkr_fetcher.py` still only reads a
  locally-committed `ibkr_snapshot.json`; no order-placement code exists
  or was added.
- `data/screener.db` was not committed, migrated, or otherwise touched.

## 7. Verification performed

- `python3 -m py_compile screener_bot.py bot_server.py` — clean.
- `.github/workflows/scan.yml` / `bot_poll.yml` — validated with
  `yaml.safe_load`.
- Full existing test suite unaffected (these files have no pytest
  coverage of their own; `app/` test suite — 753/753 — untouched by
  this change, confirmed unrelated).

## 8. Not yet done / recommended next steps (not executed without separate sign-off)

- Verify GitHub's own "notify on workflow failure" account setting is
  actually enabled (Settings → Notifications) — this audit only adds a
  Telegram-side signal, it doesn't control GitHub's native one.
- Consider adding a lightweight heartbeat/dead-man's-switch (e.g., a
  daily check that `last_scan.json`'s timestamp isn't stale) in case a
  future failure mode skips both the try/except and the `if: failure()`
  step (e.g., the runner itself dies before either can execute).
- `tg_send` in `screener_bot.py` still doesn't catch network-level
  exceptions (timeouts/connection errors) from `requests.post`, only
  non-2xx HTTP responses — low risk (would just surface as an
  unhandled exception, now at least caught one level up by the new
  `run_scan` wrapper for that specific call site, but `tg_send` calls
  elsewhere in `main()` after `run_scan` succeeds are still unguarded).
