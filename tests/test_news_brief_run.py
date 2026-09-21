"""
news_brief_run.py entrypoint orchestration tests: idempotency skip,
FORCE_SEND override (without corrupting the real dedup record),
Telegram-failure exit behavior.
"""
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

import news_brief_run
from news_brief.models import BriefingResult
from news_brief.telegram import TelegramSendError


def _empty_result(bid):
    now = datetime.now(timezone.utc)
    categories = {c: [] for c in ("WORLD", "MIDDLE_EAST", "RUSSIA", "OIL_GAS", "URANIUM_NUCLEAR", "AI_SEMIS")}
    return BriefingResult(briefing_id=bid, generated_at=now, key_highlights=[], categories=categories,
                           market_impact_map={}, watchlist=[], all_clusters=[],
                           stats={"feeds_attempted": 1, "feeds_succeeded": 1, "feeds_failed": 0, "raw_items": 0,
                                  "kept": 0, "input": 0, "clusters_total": 0, "duplicates_removed": 0,
                                  "category_counts": {}})


def test_skips_send_when_already_sent_today(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.delenv("FORCE_SEND", raising=False)
    monkeypatch.setattr(news_brief_run, "RUN_LOG_PATH", tmp_path / "log.json")

    bid = news_brief_run.state.briefing_id(datetime.now(timezone.utc))
    with patch("news_brief_run.state.load_state", return_value={"last_sent_briefing_id": bid}):
        with patch("news_brief_run.telegram.send_messages") as mock_send:
            rc = news_brief_run.main()
    assert rc == 0
    mock_send.assert_not_called()


def test_force_send_bypasses_already_sent_and_does_not_update_state(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.setenv("FORCE_SEND", "1")
    monkeypatch.setattr(news_brief_run, "RUN_LOG_PATH", tmp_path / "log.json")

    bid = news_brief_run.state.briefing_id(datetime.now(timezone.utc))
    with patch("news_brief_run.state.load_state", return_value={"last_sent_briefing_id": bid}):
        with patch("news_brief_run.briefing_mod.build_briefing", return_value=_empty_result(bid)):
            with patch("news_brief_run.telegram.send_messages") as mock_send:
                with patch("news_brief_run.state.record_sent") as mock_record:
                    rc = news_brief_run.main()
    assert rc == 0
    mock_send.assert_called_once()
    mock_record.assert_not_called()  # forced test run must not corrupt the real dedup record


def test_telegram_failure_reraises_for_visible_workflow_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.delenv("FORCE_SEND", raising=False)
    monkeypatch.setattr(news_brief_run, "RUN_LOG_PATH", tmp_path / "log.json")

    bid = news_brief_run.state.briefing_id(datetime.now(timezone.utc))
    with patch("news_brief_run.state.load_state", return_value={}):
        with patch("news_brief_run.briefing_mod.build_briefing", return_value=_empty_result(bid)):
            with patch("news_brief_run.telegram.send_messages", side_effect=TelegramSendError("boom")):
                with pytest.raises(TelegramSendError):
                    news_brief_run.main()


def test_pipeline_error_reraises_not_silently_succeeds(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.delenv("FORCE_SEND", raising=False)
    monkeypatch.setattr(news_brief_run, "RUN_LOG_PATH", tmp_path / "log.json")

    with patch("news_brief_run.state.load_state", return_value={}):
        with patch("news_brief_run.briefing_mod.build_briefing", side_effect=RuntimeError("fetch exploded")):
            with pytest.raises(RuntimeError):
                news_brief_run.main()


def test_run_log_never_contains_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("TELEGRAM_TOKEN", "super-secret-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "c")
    monkeypatch.delenv("FORCE_SEND", raising=False)
    log_path = tmp_path / "log.json"
    monkeypatch.setattr(news_brief_run, "RUN_LOG_PATH", log_path)

    bid = news_brief_run.state.briefing_id(datetime.now(timezone.utc))
    with patch("news_brief_run.state.load_state", return_value={}):
        with patch("news_brief_run.briefing_mod.build_briefing", return_value=_empty_result(bid)):
            with patch("news_brief_run.telegram.send_messages"):
                with patch("news_brief_run.state.record_sent"):
                    news_brief_run.main()

    assert "super-secret-token" not in log_path.read_text()
