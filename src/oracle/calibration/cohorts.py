"""Pre-registered forward cohort manifests and observation states."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

VALID_STATES = {"pending", "resolved", "out_of_scope", "invalid"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_cohort_manifest(
    *, cohort_id: str, selection_criteria: Mapping[str, Any], markets: list[Mapping[str, Any]],
    features: list[str], gates: Mapping[str, Any], target_n: int,
) -> dict[str, Any]:
    if not cohort_id or not markets:
        raise ValueError("cohort_id and at least one market are required")
    if target_n < len(markets):
        raise ValueError("target_n cannot be smaller than selected market count")
    seen = set()
    entries = []
    for market in markets:
        cid = str(market.get("conditionId", ""))
        if not cid or cid in seen:
            raise ValueError("markets require unique conditionId values")
        seen.add(cid)
        end_date = market.get("endDateIso") or market.get("endDate")
        entries.append({
            "condition_id": cid,
            "question": market.get("question", ""),
            "category": market.get("category", "unknown"),
            "end_date": end_date[:10] if end_date and "T" in end_date else end_date,
            "state": "pending",
            "snapshot_id": None,
        })
    return {
        "cohort_id": cohort_id,
        "registered_at": utc_now(),
        "selection_criteria": dict(selection_criteria),
        "target_n": int(target_n),
        "features": list(features),
        "gates": dict(gates),
        "qualifies_for_gates": False,
        "markets": entries,
    }


def write_manifest(path: str | Path, manifest: Mapping[str, Any]) -> None:
    target = Path(path)
    if target.exists():
        raise ValueError(f"cohort manifest already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(dict(manifest), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_manifest(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def update_observation_state(path: str | Path, condition_id: str, state: str, snapshot_id: str | None = None) -> dict[str, Any]:
    if state not in VALID_STATES:
        raise ValueError(f"state must be one of {sorted(VALID_STATES)}")
    manifest = read_manifest(path)
    for entry in manifest["markets"]:
        if entry["condition_id"] == condition_id:
            entry["state"] = state
            if snapshot_id is not None:
                entry["snapshot_id"] = snapshot_id
            Path(path).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            return manifest
    raise KeyError(condition_id)


def status(manifest: Mapping[str, Any]) -> dict[str, Any]:
    counts = {state: 0 for state in VALID_STATES}
    for entry in manifest.get("markets", []):
        counts[entry.get("state", "pending")] = counts.get(entry.get("state", "pending"), 0) + 1
    return {
        "cohort_id": manifest.get("cohort_id"),
        "selected": len(manifest.get("markets", [])),
        "target_n": manifest.get("target_n"),
        "states": counts,
        "snapshots_recorded": sum(1 for e in manifest.get("markets", []) if e.get("snapshot_id")),
    }
