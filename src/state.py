"""Local run state: what was processed, and how many notes went out today.

Kept in `data/` next to the code (gitignored). Two files:
- runs.jsonl — one JSON object per processed post (append-only log).
- counters.json — per-day submission counts, for the daily quota guard.

The writer never re-processes a post ID that is already in the log
(the API allows only one note per post anyway).
"""

from __future__ import annotations

import json
import os
from datetime import date
from typing import Any

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
RUNS_PATH = os.path.join(DATA_DIR, "runs.jsonl")
COUNTERS_PATH = os.path.join(DATA_DIR, "counters.json")


def _ensure_data_dir() -> None:
    os.makedirs(DATA_DIR, exist_ok=True)


def processed_post_ids() -> set[str]:
    """Post IDs this writer has already handled (any outcome)."""
    if not os.path.exists(RUNS_PATH):
        return set()
    seen: set[str] = set()
    with open(RUNS_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                seen.add(json.loads(line)["post_id"])
            except (KeyError, json.JSONDecodeError):
                continue
    return seen


def append_run(record: dict[str, Any]) -> None:
    _ensure_data_dir()
    with open(RUNS_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_counters() -> dict[str, Any]:
    if not os.path.exists(COUNTERS_PATH):
        return {}
    try:
        with open(COUNTERS_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError:
        return {}


def submitted_today(today: str | None = None) -> int:
    """Notes submitted on `today` (UTC date string, default today)."""
    day = today or date.today().isoformat()
    return int(_load_counters().get(day, 0))


def record_submission(today: str | None = None) -> int:
    """Increment today's submission counter; return the new total."""
    _ensure_data_dir()
    day = today or date.today().isoformat()
    counters = _load_counters()
    counters[day] = int(counters.get(day, 0)) + 1
    with open(COUNTERS_PATH, "w", encoding="utf-8") as fh:
        json.dump(counters, fh)
    return counters[day]
