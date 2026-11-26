"""Admission dashboard: test-note evaluator scores vs the admission bars.

Reads every test-mode note this writer submitted
(GET /2/notes/search/notes_written) and prints one block per note, then
the bucket counts per evaluator and progress toward admission:

  ClaimOpinion:    >= 30% high AND <= 30% low   (over 50 most recent notes)
  UrlValidity:     >= 95% high
  HarassmentAbuse: >= 98% high

Usage:
  uv run src/check_scores.py
  uv run src/check_scores.py --json   # raw notes as JSON
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(__file__))

import dotenv  # noqa: E402

from cnapi import fetch_written_notes  # noqa: E402

ADMISSION = {
    # evaluator -> (bucket that must clear, minimum share of notes)
    "ClaimOpinion": ("high", 0.30),
    "UrlValidity": ("high", 0.95),
    "HarassmentAbuse": ("high", 0.98),
}
CLAIM_OPINION_LOW_MAX = 0.30  # at most 30% `low` on ClaimOpinion


def _outcomes(note: dict) -> list[dict]:
    return (note.get("test_result") or {}).get("evaluation_outcome") or []


def admission_progress(notes: list[dict]) -> list[str]:
    """Human-readable lines: where the writer stands vs each bar."""
    recent = notes[-50:] if len(notes) > 50 else notes
    lines = [
        f"Admission is judged on the {len(recent)} most recent test notes "
        f"({len(notes)} total)."
    ]
    buckets: dict[str, Counter] = defaultdict(Counter)
    for note in recent:
        for outcome in _outcomes(note):
            buckets[outcome["evaluator_type"]][
                outcome["evaluator_score_bucket"]
            ] += 1
    for evaluator, (good_bucket, minimum) in ADMISSION.items():
        counts = buckets.get(evaluator, Counter())
        total = sum(counts.values())
        if total == 0:
            lines.append(f"  {evaluator}: no scores yet")
            continue
        share = counts.get(good_bucket, 0) / total
        verdict = "PASS" if share >= minimum else "BELOW BAR"
        lines.append(
            f"  {evaluator}: {good_bucket}={counts.get(good_bucket, 0)}/{total} "
            f"({share:.0%}, need {minimum:.0%}) [{verdict}]"
        )
        if evaluator == "ClaimOpinion":
            low_share = counts.get("low", 0) / total
            verdict = (
                "PASS" if low_share <= CLAIM_OPINION_LOW_MAX else "BELOW BAR"
            )
            lines.append(
                f"    low={counts.get('low', 0)}/{total} ({low_share:.0%}, "
                f"at most {CLAIM_OPINION_LOW_MAX:.0%}) [{verdict}]"
            )
    return lines


def print_report(notes: list[dict]) -> None:
    print(f"{len(notes)} test-mode notes written\n")
    buckets: dict[str, Counter] = defaultdict(Counter)
    for note in notes:
        info = note.get("info") or {}
        print(
            f"Note {note.get('id')}  post {info.get('post_id')}  "
            f"status {note.get('status')}"
        )
        print(f"  {info.get('text', '')}")
        outcomes = _outcomes(note)
        if not outcomes:
            print("  (no evaluator results yet)")
        for outcome in outcomes:
            print(
                f"  {outcome['evaluator_type']}: "
                f"{outcome['evaluator_score_bucket']}"
            )
            buckets[outcome["evaluator_type"]][
                outcome["evaluator_score_bucket"]
            ] += 1
        print()
    if buckets:
        print("Summary")
        for evaluator, counts in sorted(buckets.items()):
            print(
                f"  {evaluator}: "
                + ", ".join(f"{b}={n}" for b, n in counts.most_common())
            )
    pending = sum(1 for n in notes if not _outcomes(n))
    if pending:
        print(f"  {pending} notes have no evaluator results yet")
    print()
    print("Admission progress")
    for line in admission_progress(notes):
        print(line)


if __name__ == "__main__":
    dotenv.load_dotenv()
    parser = argparse.ArgumentParser(
        description="Show evaluator scores for test-mode notes."
    )
    parser.add_argument("--json", action="store_true",
                        help="Print the raw notes as JSON.")
    args = parser.parse_args()
    if shutil.which("xurl") is None:
        sys.exit(
            "xurl is not installed, or its folder is not on your PATH. "
            "See the setup guide step A.1 in the README."
        )
    try:
        notes = fetch_written_notes(test_mode=True)
    except Exception as exc:  # noqa: BLE001 - fatal setup error
        sys.exit(
            "Could not fetch your notes. The X API said:\n"
            f"{exc}\n\nCheck that xurl is logged in (`xurl auth status`) "
            "and that your account is enrolled as an AI Note Writer."
        )
    if args.json:
        print(json.dumps(notes, indent=2))
    else:
        print_report(notes)
