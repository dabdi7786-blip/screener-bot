"""Small text helpers shared by normalize.py and classify.py -- kept in
one place so the word-boundary fix (see kw_in's docstring) only has to
exist once."""
from __future__ import annotations

import re
from html import unescape

_WORD_BOUNDARY_CACHE: dict[str, re.Pattern] = {}
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def kw_in(keyword: str, text: str) -> bool:
    """Word-boundary-aware containment. Plain `keyword in text`
    substring checks caused a real false positive live: "putin" matched
    inside "com**puti**ng", routing an unrelated private-equity story
    into the RUSSIA category. \\b correctly handles single words and
    multi-word phrases (spaces act as boundaries too)."""
    pattern = _WORD_BOUNDARY_CACHE.get(keyword)
    if pattern is None:
        pattern = re.compile(r"\b" + re.escape(keyword.strip()) + r"\b")
        _WORD_BOUNDARY_CACHE[keyword] = pattern
    return pattern.search(text) is not None


def strip_html(text: str) -> str:
    """Google News RSS descriptions embed raw HTML (anchor tags, &nbsp;
    spacing, a trailing <font> publisher tag) -- observed live. Stripped
    so it never leaks into keyword matching or, if ever displayed, the
    Telegram message."""
    if not text:
        return ""
    no_tags = _TAG_RE.sub(" ", text)
    return _WHITESPACE_RE.sub(" ", unescape(no_tags)).strip()
