"""Validate a drafted note BEFORE it is submitted.

This is the main quality gate, aimed straight at the admission bars:
- UrlValidity needs >= 95% `high` — every cited URL must return HTTP 200.
  A note with a dead link is skipped, never submitted.
- ClaimOpinion needs >= 30% `high` and <= 30% `low` — the note must be
  short, factual, and free of opinion markers, hashtags, and emojis.
- A note is 1–280 characters, URLs excluded from the count, and must
  include at least one URL and at least one misleading tag.
"""

from __future__ import annotations

import re
import unicodedata

import requests

from models import Note, Tag

_URL_RE = re.compile(r"https?://\S+")
_HASHTAG_RE = re.compile(r"#\w")
_MAX_CHARS = 280


def extract_urls(text: str) -> list[str]:
    return _URL_RE.findall(text)


def chars_excluding_urls(text: str) -> int:
    """Character count with URLs removed (the API counts it this way)."""
    return len(_URL_RE.sub("", text).strip())


def _has_emoji(text: str) -> bool:
    return any(
        unicodedata.category(ch) in ("So", "Sk") or ord(ch) > 0x1F000
        for ch in text
    )


def _url_is_live(url: str, timeout: float = 10.0) -> bool:
    """True when the URL answers HTTP 200. HEAD first, GET as fallback
    (some hosts reject HEAD)."""
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True)
        if resp.status_code == 200:
            return True
        if resp.status_code in (400, 403, 405):
            resp = requests.get(
                url, timeout=timeout, allow_redirects=True, stream=True
            )
            return resp.status_code == 200
        return False
    except requests.RequestException:
        return False


def validate_note(note: Note, check_urls_live: bool = True) -> list[str]:
    """Return a list of problems; empty means the note may be submitted."""
    problems: list[str] = []
    text = note.text
    urls = extract_urls(text)
    if not text.strip():
        problems.append("note text is empty")
        return problems
    if chars_excluding_urls(text) > _MAX_CHARS:
        problems.append(
            f"note is {chars_excluding_urls(text)} chars excluding URLs "
            f"(max {_MAX_CHARS})"
        )
    if not urls:
        problems.append("note contains no source URL")
    if _HASHTAG_RE.search(text):
        problems.append("note contains a hashtag")
    if _has_emoji(text):
        problems.append("note contains an emoji or symbol")
    if not note.misleading_tags:
        problems.append("note has no misleading tag")
    bad_tags = [t for t in note.misleading_tags if t not in Tag.ALL]
    if bad_tags:
        problems.append(f"unknown misleading tags: {bad_tags}")
    if check_urls_live:
        for url in urls:
            if not _url_is_live(url):
                problems.append(f"source URL does not return HTTP 200: {url}")
    return problems
