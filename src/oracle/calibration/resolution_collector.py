"""Resolution collector for forward evaluations.

Polls cohort markets for resolution and appends outcomes to the separate
outcome store. Idempotent and append-only.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .outcome_adapters import collect_outcome_for_snapshot
from .forward_snapshot import read_snapshots
from .cohorts import read_manifest


async def collect_cohort_outcomes(
    cohort_manifest_path: str | Path,
    snapshot_path: str | Path,
    outcome_path: str | Path,
    market_source: Any,
    resolution_source: str = "gamma-api",
    batch_size: int = 10,
    delay_seconds: float = 1.0,
) -> dict[str, Any]:
    """Collect outcomes for all markets in a cohort manifest."""
    manifest = read_manifest(cohort_manifest_path)
    snapshots = read_snapshots(snapshot_path)
    
    # Filter snapshots belonging to this cohort
    cohort_snapshots = [
        s for s in snapshots 
        if s.get("evaluation_id") == manifest.get("cohort_id")
    ]
    
    if not cohort_snapshots:
        return {"cohort_id": manifest.get("cohort_id"), "outcomes_collected": 0, "message": "no snapshots for cohort"}
    
    outcomes = []
    for snapshot in cohort_snapshots:
        try:
            outcome = await collect_outcome_for_snapshot(
                snapshot, market_source=market_source, outcome_path=outcome_path,
                resolution_source="gamma-api"
            )
            if outcome is not None:
                outcomes.append(outcome)
            await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Failed to collect outcome for {snapshot.get('condition_id')}: {e}")
    
    # Update manifest observation states
    for outcome in outcomes:
        try:
            from .cohorts import update_observation_state
            update_observation_state(cohort_manifest_path, outcome["condition_id"], "resolved", outcome.get("snapshot_id"))
        except Exception:
            pass  # non-fatal
    
    return {
        "cohort_id": manifest.get("cohort_id"),
        "outcomes_collected": len(outcomes),
        "total_pending": sum(1 for m in manifest["markets"] if m["state"] == "pending"),
        "outcome_path": str(outcome_path),
    }


async def collect_all_cohorts(
    cohort_dir: str | Path,
    snapshot_path: str | Path,
    outcome_dir: str | Path,
    market_source: Any,
    resolution_source: str = "gamma-api",
) -> list[dict[str, Any]]:
    """Collect outcomes for all cohort manifests in a directory."""
    results = []
    for manifest_path in Path(cohort_dir).glob("*.json"):
        if manifest_path.name.startswith("."):
            continue
        try:
            outcome_path = Path(outcome_dir) / f"{manifest_path.stem}.outcomes.jsonl"
            result = await collect_cohort_outcomes(
                manifest_path, snapshot_path, outcome_path, market_source, "gamma-api"
            )
            results.append(result)
            await asyncio.sleep(0.5)
        except Exception as e:
            results.append({"manifest": str(manifest_path), "error": str(e)})
    return results
