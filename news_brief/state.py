"""
Idempotency (spec section 19). Deterministic briefing_id =
YYYY-MM-DD-window; persisted state prevents a scheduled run from
sending the same day's briefing twice. Manual workflow_dispatch runs
can force a send without corrupting the normal daily dedup record.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

DEFAULT_STATE_PATH = Path(__file__).parent.parent / "news_brief_state.json"
BRIEFING_WINDOW = "AM"  # single daily morning window -- documented, not implicit


def briefing_id(now: datetime) -> str:
    return f"{now.strftime('%Y-%m-%d')}-{BRIEFING_WINDOW}"


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}  # corrupted state must never crash the job -- treat as "nothing sent yet"


def already_sent(state: dict, bid: str) -> bool:
    return state.get("last_sent_briefing_id") == bid


def record_sent(state: dict, bid: str, sent_at: datetime, path: Path = DEFAULT_STATE_PATH) -> dict:
    """Only called for real (non-forced) scheduled sends -- a manual
    test run must not overwrite the real daily dedup record (spec
    section 19: 'without corrupting the normal daily deduplication')."""
    new_state = dict(state)
    new_state["last_sent_briefing_id"] = bid
    new_state["last_sent_at"] = sent_at.isoformat()
    path.write_text(json.dumps(new_state, indent=2))
    return new_state
