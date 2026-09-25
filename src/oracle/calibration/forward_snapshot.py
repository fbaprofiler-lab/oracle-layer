"""Immutable forward-evaluation prediction snapshots.

A snapshot is written before an outcome is known. The append-only writer
refuses replacement and validates that the record has the minimum evidence
needed for a forward evaluation.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REQUIRED_SNAPSHOT_FIELDS = (
    "snapshot_id", "evaluation_id", "prediction_timestamp", "condition_id",
    "question", "category", "features", "probability", "confidence",
    "judgment_backend", "feature_schema_version",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def snapshot_id(evaluation_id: str, condition_id: str, prediction_timestamp: str) -> str:
    payload = f"{evaluation_id}|{condition_id}|{prediction_timestamp}".encode()
    return hashlib.sha256(payload).hexdigest()


def create_snapshot(
    *, evaluation_id: str, prediction_timestamp: str, condition_id: str,
    question: str, category: str, features: Mapping[str, Any], probability: float,
    confidence: float, judgment_backend: str, feature_schema_version: str = "1",
) -> dict[str, Any]:
    if not 0.0 <= float(probability) <= 1.0:
        raise ValueError("probability must be between 0 and 1")
    if not 0.0 <= float(confidence) <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    if not condition_id or not question:
        raise ValueError("condition_id and question are required")
    parsed = datetime.fromisoformat(prediction_timestamp.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("prediction_timestamp must include a timezone")
    record = {
        "snapshot_id": snapshot_id(evaluation_id, condition_id, prediction_timestamp),
        "evaluation_id": evaluation_id,
        "prediction_timestamp": prediction_timestamp,
        "condition_id": condition_id,
        "question": question,
        "category": category,
        "features": dict(features),
        "probability": float(probability),
        "confidence": float(confidence),
        "judgment_backend": judgment_backend,
        "feature_schema_version": feature_schema_version,
        "created_at": utc_now(),
    }
    validate_snapshot(record)
    return record


def validate_snapshot(record: Mapping[str, Any]) -> None:
    missing = [field for field in REQUIRED_SNAPSHOT_FIELDS if field not in record or record[field] is None]
    if missing:
        raise ValueError(f"snapshot missing fields: {', '.join(missing)}")
    if not isinstance(record["features"], Mapping):
        raise ValueError("features must be an object")
    datetime.fromisoformat(str(record["prediction_timestamp"]).replace("Z", "+00:00"))
    if not 0.0 <= float(record["probability"]) <= 1.0:
        raise ValueError("probability must be between 0 and 1")
    if not 0.0 <= float(record["confidence"]) <= 1.0:
        raise ValueError("confidence must be between 0 and 1")


def append_snapshot(path: str | Path, record: Mapping[str, Any]) -> None:
    """Append a validated snapshot; never replace an existing snapshot ID."""
    validate_snapshot(record)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    for existing in read_snapshots(target):
        if existing.get("snapshot_id") == record.get("snapshot_id"):
            raise ValueError(f"snapshot already exists: {record['snapshot_id']}")
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(record), sort_keys=True, default=str) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_snapshots(path: str | Path) -> list[dict[str, Any]]:
    target = Path(path)
    if not target.exists():
        return []
    records = []
    for line in target.read_text(encoding="utf-8").splitlines():
        if line.strip():
            record = json.loads(line)
            validate_snapshot(record)
            records.append(record)
    return records
