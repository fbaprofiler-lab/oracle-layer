"""Append-only resolved-outcome records for forward evaluations.

Outcomes are stored separately from prediction snapshots. Resolution must not
mutate or replace a pre-outcome prediction artifact.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .forward_snapshot import read_snapshots

REQUIRED_OUTCOME_FIELDS = (
    "outcome_id", "snapshot_id", "condition_id", "outcome_timestamp",
    "actual_outcome", "actual_price", "resolution_source",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_outcome(
    *, snapshot_id: str, condition_id: str, outcome_timestamp: str,
    actual_outcome: int, actual_price: float, resolution_source: str,
) -> dict[str, Any]:
    if actual_outcome not in (0, 1):
        raise ValueError("actual_outcome must be 0 or 1")
    if not 0.0 <= float(actual_price) <= 1.0:
        raise ValueError("actual_price must be between 0 and 1")
    parsed = datetime.fromisoformat(outcome_timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("outcome_timestamp must include a timezone")
    record = {
        "outcome_id": f"{snapshot_id}:{condition_id}:{outcome_timestamp}",
        "snapshot_id": snapshot_id,
        "condition_id": condition_id,
        "outcome_timestamp": outcome_timestamp,
        "actual_outcome": int(actual_outcome),
        "actual_price": float(actual_price),
        "resolution_source": resolution_source,
        "collected_at": _utc_now(),
    }
    validate_outcome(record)
    return record


def validate_outcome(record: Mapping[str, Any]) -> None:
    missing = [field for field in REQUIRED_OUTCOME_FIELDS if field not in record or record[field] is None]
    if missing:
        raise ValueError(f"outcome missing fields: {', '.join(missing)}")
    if int(record["actual_outcome"]) not in (0, 1):
        raise ValueError("actual_outcome must be 0 or 1")
    if not 0.0 <= float(record["actual_price"]) <= 1.0:
        raise ValueError("actual_price must be between 0 and 1")
    datetime.fromisoformat(str(record["outcome_timestamp"]).replace("Z", "+00:00"))


def append_outcome(path: str | Path, record: Mapping[str, Any]) -> None:
    validate_outcome(record)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if any(existing.get("outcome_id") == record.get("outcome_id") for existing in read_outcomes(target)):
        raise ValueError(f"outcome already exists: {record['outcome_id']}")
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(record), sort_keys=True, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_outcomes(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    records = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            validate_outcome(record)
            records.append(record)
    return records


def join_outcomes(snapshots_path: str | Path, outcomes_path: str | Path) -> list[dict[str, Any]]:
    """Join outcomes to snapshots after collection, never before."""
    outcomes = {row["snapshot_id"]: row for row in read_outcomes(outcomes_path)}
    joined = []
    for snapshot in read_snapshots(snapshots_path):
        outcome = outcomes.get(snapshot["snapshot_id"])
        if outcome is None:
            continue
        joined.append({**snapshot, **outcome})
    return joined
