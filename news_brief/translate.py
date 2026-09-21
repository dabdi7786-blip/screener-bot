"""
Best-effort translation of real, verbatim-fetched headlines into Russian
for Telegram display (spec follow-up: the brief must arrive in Russian).

Uses the free, keyless Google Translate web endpoint -- same "no paid
API, no secret" posture already used for Google News RSS in sources.py.
This is unofficial/undocumented and can be rate-limited or blocked at
any time; translation failure must NEVER block or fail the briefing --
callers get the original (English) text back for that one item, and the
rest of the run is unaffected. This module never uses an LLM: it only
ever passes real fetched text into a translation call and returns the
result or the original -- it does not invent replacement text.
"""
from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger("news_brief.translate")

_ENDPOINT = "https://translate.googleapis.com/translate_a/single"
_TIMEOUT = 10
MAX_RETRIES = 3
BACKOFF_SCHEDULE = (1, 2, 4)


def translate_to_ru(text: str, session: requests.Session | None = None) -> str:
    """Translates `text` to Russian. Returns `text` unchanged if it is
    empty/whitespace, or if translation fails after retries -- never
    raises, never fabricates a replacement."""
    if not text or not text.strip():
        return text

    session = session or requests.Session()
    params = {"client": "gtx", "sl": "auto", "tl": "ru", "dt": "t", "q": text}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(_ENDPOINT, params=params, timeout=_TIMEOUT)
            resp.raise_for_status()
            data = resp.json()
            translated = "".join(seg[0] for seg in data[0] if seg and seg[0])
            if translated:
                return translated
            return text  # malformed-but-non-erroring response -- fall back rather than send empty text
        except Exception as exc:
            log.warning("translate attempt %d/%d failed: %s", attempt, MAX_RETRIES, exc)
            if attempt < MAX_RETRIES:
                time.sleep(BACKOFF_SCHEDULE[attempt - 1])

    log.warning("translation unavailable after %d attempts -- keeping original text", MAX_RETRIES)
    return text


def make_cached_translator(session: requests.Session | None = None):
    """Returns a translate(text) -> str callable that memoizes results
    for the lifetime of one run, so repeated/overlapping strings (e.g.
    a source title echoed in both a cluster headline and the SOURCES
    list) only trigger one network call."""
    session = session or requests.Session()
    cache: dict[str, str] = {}

    def translate(text: str) -> str:
        if text not in cache:
            cache[text] = translate_to_ru(text, session=session)
        return cache[text]

    return translate
