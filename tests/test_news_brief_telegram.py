"""
news_brief.telegram tests (spec categories: 12 retry behavior,
13 Telegram failure, 17 secret redaction).
"""
import logging
from unittest.mock import MagicMock, patch

import pytest

from news_brief.telegram import TelegramSendError, send_message, send_messages

FAKE_TOKEN = "123456:AAFAKE_TOKEN_VALUE_NEVER_REAL"
FAKE_CHAT_ID = "-100123456"


def _ok_response():
    r = MagicMock()
    r.ok = True
    return r


def _fail_response(code=500):
    r = MagicMock()
    r.ok = False
    r.status_code = code
    r.text = "Internal Server Error"
    return r


def test_send_message_success_first_try():
    session = MagicMock()
    session.post.return_value = _ok_response()
    send_message("hello", FAKE_TOKEN, FAKE_CHAT_ID, session=session)
    assert session.post.call_count == 1


def test_send_message_retries_then_succeeds():
    session = MagicMock()
    session.post.side_effect = [_fail_response(), _fail_response(), _ok_response()]
    with patch("news_brief.telegram.time.sleep"):
        send_message("hello", FAKE_TOKEN, FAKE_CHAT_ID, session=session)
    assert session.post.call_count == 3


def test_send_message_raises_after_max_retries():
    session = MagicMock()
    session.post.return_value = _fail_response()
    with patch("news_brief.telegram.time.sleep"):
        with pytest.raises(TelegramSendError):
            send_message("hello", FAKE_TOKEN, FAKE_CHAT_ID, session=session)
    assert session.post.call_count == 5  # MAX_RETRIES


def test_send_message_missing_credentials_raises_immediately():
    with pytest.raises(TelegramSendError):
        send_message("hello", "", "", session=MagicMock())


def test_send_messages_stops_at_first_unrecoverable_failure():
    session = MagicMock()
    session.post.side_effect = [_ok_response()] + [_fail_response()] * 5
    with patch("news_brief.telegram.time.sleep"):
        with pytest.raises(TelegramSendError):
            send_messages(["msg1", "msg2"], FAKE_TOKEN, FAKE_CHAT_ID, session=session)
    # msg1 succeeded (1 call), msg2 exhausted its 5 retries
    assert session.post.call_count == 1 + 5


def test_token_never_appears_in_exception_text():
    session = MagicMock()
    session.post.return_value = _fail_response()
    with patch("news_brief.telegram.time.sleep"):
        with pytest.raises(TelegramSendError) as exc_info:
            send_message("hello", FAKE_TOKEN, FAKE_CHAT_ID, session=session)
    assert FAKE_TOKEN not in str(exc_info.value)


def test_token_never_logged(caplog):
    session = MagicMock()
    session.post.return_value = _fail_response()
    with patch("news_brief.telegram.time.sleep"):
        with caplog.at_level(logging.WARNING, logger="news_brief.telegram"):
            with pytest.raises(TelegramSendError):
                send_message("hello", FAKE_TOKEN, FAKE_CHAT_ID, session=session)
    for record in caplog.records:
        assert FAKE_TOKEN not in record.getMessage()
