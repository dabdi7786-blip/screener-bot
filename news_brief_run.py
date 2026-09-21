"""
Overnight / Global News Brief -- entrypoint (spec section 3: FETCH ->
NORMALIZE -> DEDUPLICATE -> CLASSIFY -> RANK -> GENERATE BRIEF ->
VALIDATE -> TELEGRAM -> LOG/ARTIFACT).

Run by .github/workflows/overnight_news.yml. Independent of
screener_bot.py/bot_server.py -- does not import them, does not touch
app/*, does not touch production_gate.py.

Env vars:
  TELEGRAM_TOKEN, TELEGRAM_CHAT_ID  -- required, GitHub Secrets in CI
  FORCE_SEND=1                      -- manual workflow_dispatch override:
                                        sends even if today's briefing_id
                                        was already recorded, WITHOUT
                                        overwriting the real dedup record
                                        (spec section 19)
"""
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from news_brief import briefing as briefing_mod
from news_brief import format_telegram, state, telegram

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("news_brief.run")

RUN_LOG_PATH = Path(__file__).parent / "news_brief_run_log.json"


def main() -> int:
    start = time.monotonic()
    now = datetime.now(timezone.utc)
    bid = state.briefing_id(now)
    force = os.getenv("FORCE_SEND", "").strip().lower() in ("1", "true", "yes")

    token = os.getenv("TELEGRAM_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    run_log = {"briefing_id": bid, "started_at": now.isoformat(), "forced": force}

    st = state.load_state()
    if not force and state.already_sent(st, bid):
        log.info("briefing %s already sent -- skipping (idempotency, no FORCE_SEND)", bid)
        run_log.update({"status": "SKIPPED_ALREADY_SENT", "duration_s": time.monotonic() - start})
        _write_log(run_log)
        return 0

    log.info("building briefing %s%s", bid, " (FORCED)" if force else "")
    try:
        result = briefing_mod.build_briefing(bid, now=now)
    except Exception:
        log.exception("briefing pipeline failed unexpectedly")
        run_log.update({"status": "PIPELINE_ERROR", "duration_s": time.monotonic() - start})
        _write_log(run_log)
        raise  # fail the workflow loudly -- never silently succeed

    stats = result.stats
    log.info(
        "fetch: %d/%d feeds ok, %d raw items | validate: %d kept of %d | clusters: %d (%d dup merged) | categories: %s",
        stats.get("feeds_succeeded", 0), stats.get("feeds_attempted", 0), stats.get("raw_items", 0),
        stats.get("kept", 0), stats.get("input", 0), stats.get("clusters_total", 0),
        stats.get("duplicates_removed", 0), stats.get("category_counts", {}),
    )

    messages = format_telegram.build_messages(result)
    if stats.get("feeds_failed", 0) > 0 and stats.get("feeds_succeeded", 0) > 0:
        messages[0] = "⚠️ Some sources unavailable; briefing based on available verified sources.\n\n" + messages[0]
        log.warning("partial source failure: %d/%d feeds failed", stats["feeds_failed"], stats["feeds_attempted"])

    try:
        telegram.send_messages(messages, token, chat_id)
    except telegram.TelegramSendError:
        log.exception("Telegram delivery failed after retries")
        run_log.update({"status": "TELEGRAM_FAILED", "stats": stats, "duration_s": time.monotonic() - start})
        _write_log(run_log)
        raise  # workflow must fail visibly (spec section 17)

    if not force:
        state.record_sent(st, bid, now)
    else:
        log.info("FORCE_SEND: message delivered, real daily dedup record NOT updated")

    run_log.update({
        "status": "SENT", "n_messages": len(messages), "message_lengths": [len(m) for m in messages],
        "stats": stats, "duration_s": time.monotonic() - start,
    })
    _write_log(run_log)
    log.info("done in %.1fs, %d Telegram message(s) sent", run_log["duration_s"], len(messages))
    return 0


def _write_log(run_log: dict) -> None:
    # No secrets are ever placed in run_log (only counts/status/timing).
    RUN_LOG_PATH.write_text(json.dumps(run_log, indent=2, default=str))


if __name__ == "__main__":
    sys.exit(main())
