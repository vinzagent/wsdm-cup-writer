"""Talk to the X Community Notes API through the `xurl` CLI.

`xurl` holds the OAuth 1.0a session (see README step A.1 / the writer's
setup guide): `xurl auth oauth1 --consumer-key ... --consumer-secret ...
--access-token ... --token-secret ...`. This module only shells out to it
and parses the JSON it prints; it holds no credentials itself.

Endpoints (documented at https://docs.x.com/x-api/community-notes/introduction):
  GET  /2/notes/search/posts_eligible_for_notes
  POST /2/notes
  GET  /2/notes/search/notes_written
  POST /2/evaluate_note   (optional helper; payload shape unverified)
  DELETE /2/notes/{id}
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from typing import Any, Optional

from models import Media, Note, Post, PostWithContext

_TWEET_FIELDS = (
    "author_id,created_at,referenced_tweets,media_metadata,note_tweet,"
    "possibly_sensitive,note_request_suggestions,"
    "suggested_source_links_with_counts"
)
_EXPANSIONS = (
    "attachments.media_keys,referenced_tweets.id,"
    "referenced_tweets.id.attachments.media_keys"
)
_MEDIA_FIELDS = (
    "alt_text,duration_ms,height,media_key,preview_image_url,"
    "public_metrics,type,url,width,variants"
)


def _run_xurl(args: list[str]) -> dict[str, Any]:
    """Run `xurl <args>` and return its JSON stdout as a dict."""
    try:
        done = subprocess.run(
            ["xurl"] + args, check=True, text=True, capture_output=True
        )
    except subprocess.CalledProcessError as exc:
        detail = ((exc.stdout or "") + (exc.stderr or "")).strip()
        raise RuntimeError(
            f"xurl failed (exit {exc.returncode}): {detail or exc}"
        ) from exc
    return json.loads(done.stdout)


def _parse_post(item: dict, media_by_key: dict[str, dict]) -> Post:
    media: list[Media] = []
    for key in item.get("attachments", {}).get("media_keys", []):
        raw = media_by_key.get(key)
        if raw is None:
            continue
        media.append(
            Media(
                media_key=raw["media_key"],
                media_type=raw.get("type", ""),
                url=raw.get("url"),
                preview_image_url=raw.get("preview_image_url"),
                width=raw.get("width"),
                height=raw.get("height"),
                duration_ms=raw.get("duration_ms"),
            )
        )
    text = item.get("text", "")
    note_tweet = item.get("note_tweet", {}).get("text", "")
    if note_tweet:
        text = note_tweet
    return Post(
        post_id=item["id"],
        author_id=item.get("author_id", ""),
        created_at=datetime.fromisoformat(
            item["created_at"].replace("Z", "+00:00")
        ),
        text=text,
        media=media,
        possibly_sensitive=bool(item.get("possibly_sensitive", False)),
    )


def _parse_feed(resp: dict) -> list[PostWithContext]:
    media_by_key = {
        m["media_key"]: m for m in resp.get("includes", {}).get("media", [])
    }
    posts_by_id = {
        t["id"]: t for t in resp.get("includes", {}).get("tweets", [])
    }
    out: list[PostWithContext] = []
    for item in resp.get("data", []):
        post = _parse_post(item, media_by_key)
        quoted = None
        replied_to = None
        for ref in item.get("referenced_tweets", []):
            ref_item = posts_by_id.get(ref["id"])
            if ref_item is None:
                continue
            ref_post = _parse_post(ref_item, media_by_key)
            if ref.get("type") == "quoted":
                quoted = ref_post
            elif ref.get("type") == "replied_to":
                replied_to = ref_post
        out.append(
            PostWithContext(
                post=post,
                quoted_post=quoted,
                in_reply_to_post=replied_to,
                note_request_suggestions=item.get("note_request_suggestions", []),
                suggested_source_links=item.get(
                    "suggested_source_links_with_counts", []
                ),
            )
        )
    return out


def fetch_eligible_posts(
    max_results: int = 10, test_mode: bool = True
) -> list[PostWithContext]:
    """Fetch posts people requested notes on, newest first."""
    path = (
        "/2/notes/search/posts_eligible_for_notes"
        f"?test_mode={'true' if test_mode else 'false'}"
        f"&max_results={max_results}"
        f"&tweet.fields={_TWEET_FIELDS}"
        f"&expansions={_EXPANSIONS}"
        f"&media.fields={_MEDIA_FIELDS}"
    )
    return _parse_feed(_run_xurl([path]))


def submit_note(note: Note, test_mode: bool = True) -> dict[str, Any]:
    """Submit one note. Returns the API response (data.id is the note ID)."""
    payload = {
        "test_mode": test_mode,
        "post_id": note.post_id,
        "info": {
            "text": note.text,
            "classification": "misinformed_or_potentially_misleading",
            "misleading_tags": list(note.misleading_tags),
            "trustworthy_sources": note.trustworthy_sources,
        },
    }
    return _run_xurl(["-X", "POST", "/2/notes", "-d", json.dumps(payload)])


def fetch_written_notes(test_mode: bool = True) -> list[dict]:
    """Page through all notes this writer submitted, with evaluator scores."""
    notes: list[dict] = []
    token: Optional[str] = None
    while True:
        path = (
            "/2/notes/search/notes_written"
            f"?test_mode={'true' if test_mode else 'false'}"
            "&max_results=100"
            "&note.fields=id,info,status,test_result"
        )
        if token:
            path += f"&pagination_token={token}"
        resp = _run_xurl([path])
        notes.extend(resp.get("data", []))
        token = (resp.get("meta") or {}).get("next_token")
        if not token:
            return notes


def evaluate_note_text(text: str) -> dict[str, Any]:
    """Best-effort ClaimOpinion check via POST /2/evaluate_note.

    The endpoint is documented as returning the ClaimOpinion score for a
    note; its exact request shape is NOT verified against the official
    guide (communitynotes.x.com is blocked for text fetch here). Treat
    failures as "unknown", never as a verdict. The reliable admission
    signal is check_scores.py, which reads the real evaluator results.
    """
    try:
        return _run_xurl(
            ["-X", "POST", "/2/evaluate_note", "-d", json.dumps({"text": text})]
        )
    except Exception as exc:  # noqa: BLE001 - best-effort probe only
        return {"error": str(exc)}


def delete_note(note_id: str) -> dict[str, Any]:
    return _run_xurl(["-X", "DELETE", f"/2/notes/{note_id}"])
