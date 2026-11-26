"""Run the vinzagent Community Notes writer once.

Pipeline: fetch the daily feed -> filter (sensitive / already seen) ->
rank (most note requests + suggested links first) -> research each post
with Grok -> validate the draft (live URLs, <=280 chars, tags) ->
submit via the AI Note Writer API (unless --dry-run).

Daily quota: new writers start at 10 notes/day on the X API side, so
DAILY_NOTE_LIMIT defaults to 10. Raise it as the CRH rate grows, never
above the competition cap of 65. The counter lives in data/counters.json
and is shared across runs on the same machine.

Usage:
  uv run src/main.py --num-posts 5 --dry-run     # check the pipeline
  uv run src/main.py --num-posts 10              # test mode (default)
  uv run src/main.py --num-posts 20 --concurrency 4
Environment (.env): XAI_API_KEY, TEST_MODE (default true),
DAILY_NOTE_LIMIT (default 10), LLM_MODEL (default grok-4.3).
The four X OAuth keys live in `xurl`, not in .env (see README).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

import dotenv  # noqa: E402

from cnapi import fetch_eligible_posts, submit_note  # noqa: E402
from models import Outcome, PostWithContext  # noqa: E402
from research import DECISION_WRITE, research_post_and_write_note  # noqa: E402
from state import (  # noqa: E402
    append_run,
    processed_post_ids,
    record_submission,
    submitted_today,
)
from validate import validate_note  # noqa: E402


def _check_setup() -> None:
    if not os.getenv("XAI_API_KEY"):
        sys.exit(
            "XAI_API_KEY is not set. Copy .env.example to .env and fill "
            "in your xAI API key."
        )
    if shutil.which("xurl") is None:
        sys.exit(
            "xurl is not installed, or its folder is not on your PATH. "
            "See the setup guide step A.1 in the README."
        )


def _rank(posts: list[PostWithContext]) -> list[PostWithContext]:
    """Highest-yield first: most note requests, then most suggested
    source links, then newest. The daily quota is small, so spend it
    where people are already asking for a note."""
    return sorted(
        posts,
        key=lambda p: (
            -p.request_count,
            -p.suggested_link_count,
            -p.post.created_at.timestamp(),
        ),
    )


def _process_one(
    post_with_context: PostWithContext,
    *,
    dry_run: bool,
    test_mode: bool,
    model: str,
    daily_limit: int,
) -> Outcome:
    post_id = post_with_context.post.post_id
    outcome = research_post_and_write_note(post_with_context, model=model)
    if outcome.decision != DECISION_WRITE or outcome.note is None:
        return outcome

    problems = validate_note(outcome.note)
    if problems:
        return Outcome(
            post_id=post_id,
            decision="SKIPPED",
            note=outcome.note,
            reason="validation failed: " + "; ".join(problems),
        )
    if submitted_today() >= daily_limit:
        return Outcome(
            post_id=post_id,
            decision="SKIPPED",
            note=outcome.note,
            reason=f"daily limit reached ({daily_limit} notes today)",
        )
    if dry_run:
        return Outcome(
            post_id=post_id,
            decision=DECISION_WRITE,
            note=outcome.note,
            reason="dry run — not submitted",
        )
    try:
        resp = submit_note(outcome.note, test_mode=test_mode)
        note_id = (resp.get("data") or {}).get("id")
        record_submission()
        return Outcome(
            post_id=post_id,
            decision=DECISION_WRITE,
            note=outcome.note,
            note_id=note_id,
            submitted=True,
        )
    except Exception as exc:  # noqa: BLE001 - logged, run continues
        return Outcome(
            post_id=post_id,
            decision="ERROR",
            note=outcome.note,
            reason=f"submit failed: {exc}",
        )


def _log(outcome: Outcome, post: PostWithContext) -> None:
    stamp = datetime.now(timezone.utc).isoformat()
    record = {
        "ts": stamp,
        "post_id": outcome.post_id,
        "decision": outcome.decision,
        "reason": outcome.reason,
        "submitted": outcome.submitted,
        "note_id": outcome.note_id,
        "note_text": outcome.note.text if outcome.note else None,
        "tags": outcome.note.misleading_tags if outcome.note else None,
    }
    append_run(record)
    bar = "-" * 20
    lines = [bar, f"Post: {outcome.post_id}", bar]
    lines.append(f"\n*POST:*\n{post.post.text[:500]}\n")
    if outcome.note is not None:
        lines.append(f"\n*NOTE:*\n  {outcome.note.text}\n")
        lines.append(f"\n*TAGS:*\n  {outcome.note.misleading_tags}\n")
    lines.append(f"\n*DECISION:* {outcome.decision}")
    if outcome.reason:
        lines.append(f" ({outcome.reason})")
    if outcome.note_id:
        lines.append(f"\n*NOTE ID:* {outcome.note_id}")
    print("".join(lines) + "\n")


def main(
    num_posts: int = 10,
    dry_run: bool = False,
    concurrency: int = 1,
    test_mode: bool = True,
    model: str = "grok-4.3",
    daily_limit: int = 10,
) -> None:
    print(
        f"Fetching up to {num_posts} posts eligible for notes "
        f"(test_mode={test_mode}, daily limit {daily_limit}, "
        f"already submitted today: {submitted_today()})"
    )
    try:
        feed = fetch_eligible_posts(max_results=num_posts, test_mode=test_mode)
    except Exception as exc:  # noqa: BLE001 - fatal setup error
        sys.exit(
            "Could not fetch posts eligible for notes. The X API said:\n"
            f"{exc}\n\nCheck that xurl is logged in (`xurl auth status`), "
            "that your account is enrolled as an AI Note Writer, and that "
            "your app has Read and write permissions."
        )
    print(f"Found {len(feed)} posts in the feed")

    seen = processed_post_ids()
    fresh = [p for p in feed if p.post.post_id not in seen]
    sensitive = [p for p in fresh if p.post.possibly_sensitive]
    fresh = [p for p in fresh if not p.post.possibly_sensitive]
    print(
        f"Skipping {len(feed) - len(fresh) - len(sensitive)} already seen, "
        f"{len(sensitive)} possibly sensitive; {len(fresh)} to process"
    )
    if not fresh:
        print("No posts to process.")
        return

    ranked = _rank(fresh)

    def work(post: PostWithContext) -> None:
        outcome = _process_one(
            post,
            dry_run=dry_run,
            test_mode=test_mode,
            model=model,
            daily_limit=daily_limit,
        )
        _log(outcome, post)

    if concurrency > 1:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            list(pool.map(work, ranked))
    else:
        for post in ranked:
            work(post)
    print("Done.")


if __name__ == "__main__":
    dotenv.load_dotenv()
    parser = argparse.ArgumentParser(description="Run the note writer once.")
    parser.add_argument("--num-posts", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true",
                        help="Write notes but do not submit them.")
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()
    _check_setup()
    main(
        num_posts=args.num_posts,
        dry_run=args.dry_run,
        concurrency=args.concurrency,
        test_mode=os.getenv("TEST_MODE", "true").strip().lower() != "false",
        model=os.getenv("LLM_MODEL", "grok-4.3"),
        daily_limit=int(os.getenv("DAILY_NOTE_LIMIT", "10")),
    )
