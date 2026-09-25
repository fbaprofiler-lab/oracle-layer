#!/usr/bin/env python3
"""Bounded forward-collection dry run.

Default mode performs no external calls and writes no snapshots. Use
``--execute`` only to assemble one real market snapshot; this command never
resolves outcomes.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from oracle.calibration.forward_adapters import ForwardFeatureCollector, LayaForwardJudgment
from oracle.calibration.forward_collector import collect_one
from oracle.sources.polymarket import polymarket_source


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="perform one real collection; otherwise only validate wiring")
    parser.add_argument("--category", default=None, help="optional active-market category")
    parser.add_argument("--evaluation-id", default="forward_smoke")
    parser.add_argument("--snapshot-path", default="data/forward/predictions.jsonl")
    return parser.parse_args()


async def run(args: argparse.Namespace) -> int:
    # Delay source imports/initialization until execution is explicitly requested.
    if not args.execute:
        print(json.dumps({
            "mode": "dry-run",
            "external_calls": False,
            "snapshot_written": False,
            "adapters": ["ForwardFeatureCollector", "LayaForwardJudgment", "collect_one"],
        }, indent=2))
        return 0

    markets = await polymarket_source.get_active_markets(category=args.category, limit=1)
    if not markets:
        print(json.dumps({"error": "no active markets returned", "snapshot_written": False}, indent=2))
        return 2

    snapshot_path = Path(args.snapshot_path)
    # Laya local model loading is expensive and may require checkpoints; this
    # bounded smoke path uses the existing compatibility client only when the
    # operator has configured it in the environment.
    try:
        from oracle.judgment.laya_client import LayaClient
        judgment = LayaForwardJudgment(LayaClient(mode="remote", preload=False))
        record = await collect_one(
            markets[0], evaluation_id=args.evaluation_id,
            feature_collector=ForwardFeatureCollector(polymarket_source),
            judgment=judgment, snapshot_path=snapshot_path,
        )
    finally:
        await polymarket_source.close()

    print(json.dumps({
        "mode": "execute", "external_calls": True, "snapshot_written": True,
        "snapshot_path": str(snapshot_path), "snapshot_id": record["snapshot_id"],
        "condition_id": record["condition_id"], "backend": record["judgment_backend"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
