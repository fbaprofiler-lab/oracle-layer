#!/usr/bin/env python3
"""Bounded cohort dry-run.

Default mode validates wiring and shows the cohort manifest that would be
created. Use --execute to write the manifest and collect snapshots.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from oracle.calibration.cohorts import create_cohort_manifest, write_manifest, status
from oracle.calibration.forward_collector import collect_market_batch
from oracle.calibration.forward_adapters import ForwardFeatureCollector, LayaForwardJudgment
from oracle.sources.polymarket import polymarket_source
from oracle.judgment.laya_client import LayaClient


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="write manifest and collect snapshots")
    parser.add_argument("--cohort-id", default="cohort_forward_smoke")
    parser.add_argument("--category", default=None, help="optional active-market category")
    parser.add_argument("--limit", type=int, default=3, help="max markets to collect")
    parser.add_argument("--manifest-path", default="data/forward/cohorts/cohort.json")
    parser.add_argument("--snapshot-path", default="data/forward/cohort_snapshots.jsonl")
    parser.add_argument("--dry-run", action="store_true", help="alias for default mode")
    return parser.parse_args()


async def fetch_active_markets(category: str | None, limit: int) -> list[dict]:
    return await polymarket_source.get_active_markets(category=category, limit=limit)


async def run(args: argparse.Namespace) -> int:
    markets = await fetch_active_markets(args.category, args.limit)
    if not markets:
        print(json.dumps({"error": "no active markets returned"}, indent=2))
        return 2

    features = [
        "question_text", "latest_market_price", "category",
        "macro_context", "smart_money_net_flow"
    ]
    gates = {
        "ece_threshold": 0.05,
        "brier_threshold": 0.20,
        "hit_rate_threshold": 0.55,
        "min_samples": 100,
    }
    selection = {"active": True, "category": args.category, "limit": args.limit}
    manifest = create_cohort_manifest(
        cohort_id=args.cohort_id,
        selection_criteria=selection,
        markets=markets,
        features=features,
        gates=gates,
        target_n=len(markets),
    )

    if not args.execute:
        print(json.dumps({
            "mode": "dry-run",
            "external_calls": False,
            "manifest_written": False,
            "cohort_status": status(manifest),
        }, indent=2))
        return 0

    manifest_path = Path(args.manifest_path).with_name(f"{args.cohort_id}.json")
    write_manifest(manifest_path, manifest)

    snapshot_path = Path(args.snapshot_path)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    judgment = LayaForwardJudgment(LayaClient(mode="remote", preload=False))
    # collect_market_batch, not collect_one: the resolution-window filter lives
    # in the batch path. Calling collect_one directly let 2028 nomination
    # markets into a 30-day cohort.
    collected = await collect_market_batch(
        markets,
        evaluation_id=args.cohort_id,
        feature_collector=ForwardFeatureCollector(polymarket_source),
        judgment=judgment,
        snapshot_path=snapshot_path,
    )
    markets_collected = len(collected)

    await polymarket_source.close()
    await judgment.client.close()

    print(json.dumps({
        "mode": "execute",
        "external_calls": True,
        "manifest_written": True,
        "manifest_path": str(manifest_path),
        "snapshot_path": str(snapshot_path),
        "markets_collected": markets_collected,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(parse_args())))
