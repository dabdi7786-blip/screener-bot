"""
news_brief.state tests (spec categories: 14 idempotency, 18
deterministic briefing ID).
"""
import json
from datetime import datetime, timezone

from news_brief.state import already_sent, briefing_id, load_state, record_sent


def test_briefing_id_is_deterministic_for_same_day():
    d1 = datetime(2026, 9, 21, 4, 30, tzinfo=timezone.utc)
    d2 = datetime(2026, 9, 21, 4, 45, tzinfo=timezone.utc)
    assert briefing_id(d1) == briefing_id(d2)


def test_briefing_id_differs_across_days():
    d1 = datetime(2026, 9, 21, 4, 30, tzinfo=timezone.utc)
    d2 = datetime(2026, 9, 22, 4, 30, tzinfo=timezone.utc)
    assert briefing_id(d1) != briefing_id(d2)


def test_briefing_id_format_includes_window():
    bid = briefing_id(datetime(2026, 9, 21, 4, 30, tzinfo=timezone.utc))
    assert bid == "2026-09-21-AM"


def test_already_sent_detects_recorded_id():
    state = {"last_sent_briefing_id": "2026-09-21-AM"}
    assert already_sent(state, "2026-09-21-AM") is True
    assert already_sent(state, "2026-09-22-AM") is False


def test_already_sent_false_on_empty_state():
    assert already_sent({}, "2026-09-21-AM") is False


def test_load_state_missing_file_returns_empty_dict(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    assert load_state(missing) == {}


def test_load_state_corrupted_file_returns_empty_dict_not_crash(tmp_path):
    bad = tmp_path / "state.json"
    bad.write_text("{not valid json")
    assert load_state(bad) == {}


def test_record_sent_persists_and_is_idempotent_across_reload(tmp_path):
    path = tmp_path / "state.json"
    now = datetime(2026, 9, 21, 4, 30, tzinfo=timezone.utc)
    bid = briefing_id(now)
    new_state = record_sent({}, bid, now, path=path)
    assert new_state["last_sent_briefing_id"] == bid

    reloaded = load_state(path)
    assert already_sent(reloaded, bid) is True


def test_record_sent_writes_valid_json(tmp_path):
    path = tmp_path / "state.json"
    now = datetime(2026, 9, 21, 4, 30, tzinfo=timezone.utc)
    record_sent({}, briefing_id(now), now, path=path)
    data = json.loads(path.read_text())
    assert "last_sent_at" in data
