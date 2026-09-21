"""
news_brief.translate tests. Never hits the live network -- requests.Session
is mocked throughout, matching the pattern in test_news_brief_telegram.py.
"""
from unittest.mock import MagicMock, patch

from news_brief.translate import make_cached_translator, translate_to_ru


def _ok_response(translated="Привет"):
    r = MagicMock()
    r.raise_for_status.return_value = None
    r.json.return_value = [[[translated, "hello", None, None, 1]]]
    return r


def _fail_response():
    r = MagicMock()
    r.raise_for_status.side_effect = Exception("HTTP 500")
    return r


def test_translate_success_first_try():
    session = MagicMock()
    session.get.return_value = _ok_response("Привет")
    result = translate_to_ru("hello", session=session)
    assert result == "Привет"
    assert session.get.call_count == 1


def test_translate_retries_then_succeeds():
    session = MagicMock()
    session.get.side_effect = [_fail_response(), _fail_response(), _ok_response("Привет")]
    with patch("news_brief.translate.time.sleep"):
        result = translate_to_ru("hello", session=session)
    assert result == "Привет"
    assert session.get.call_count == 3


def test_translate_falls_back_to_original_after_max_retries():
    session = MagicMock()
    session.get.return_value = _fail_response()
    with patch("news_brief.translate.time.sleep"):
        result = translate_to_ru("hello world", session=session)
    assert result == "hello world"  # never raises, never fabricates -- original text preserved
    assert session.get.call_count == 3  # MAX_RETRIES


def test_translate_empty_or_whitespace_text_skips_network_entirely():
    session = MagicMock()
    assert translate_to_ru("", session=session) == ""
    assert translate_to_ru("   ", session=session) == "   "
    assert session.get.call_count == 0


def test_translate_malformed_response_falls_back_to_original():
    session = MagicMock()
    r = MagicMock()
    r.raise_for_status.return_value = None
    r.json.return_value = [[]]  # no segments -- nothing to join
    session.get.return_value = r
    result = translate_to_ru("hello", session=session)
    assert result == "hello"


def test_cached_translator_memoizes_repeated_text():
    session = MagicMock()
    session.get.return_value = _ok_response("Привет")
    translate = make_cached_translator(session=session)
    assert translate("hello") == "Привет"
    assert translate("hello") == "Привет"
    assert session.get.call_count == 1  # second call served from cache, no network


def test_cached_translator_distinguishes_different_text():
    session = MagicMock()
    session.get.side_effect = [_ok_response("Привет"), _ok_response("Мир")]
    translate = make_cached_translator(session=session)
    assert translate("hello") == "Привет"
    assert translate("world") == "Мир"
    assert session.get.call_count == 2
