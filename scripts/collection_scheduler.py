#!/usr/bin/env python3
"""Daily forward-collection job.

Runs alongside the 2 AM resolution scheduler and is the half that was never
scheduled: the scheduler only reads outcomes for snapshots that already exist,
so without this the pipeline held 93 frozen snapshots forever.

Both jobs are deliberately separate. Collection writes pre-registered
predictions; resolution reads settled outcomes into a separate append-only
store. Neither writes the other's artifact.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone, timedelta, timezone as _tz
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from oracle.calibration.forward_collector import (
    MAX_RESOLUTION_DAYS,
    collect_market_batch,
)
from oracle.calibration.forward_adapters import (
    ForwardFeatureCollector,
    LayaForwardJudgment,
)
from oracle.sources.polymarket import polymarket_source
from oracle.judgment.laya_client import LayaClient

# Categories the charter evaluates on. Verified available on 2026-09-25:
# fed-rate-decisions and crypto-prices return markets; cpi-inflation does not
# (Polymarket had no US CPI contracts listed) and is retained so the cohort
# starts collecting automatically if one is posted.
COLLECT_CATEGORIES = ("fed-rate-decisions", "crypto-prices", "cpi-inflation")

SNAPSHOT_PATH = "data/forward/cohort_snapshots.jsonl"
LOG_PATH = "data/forward/logs/collection_scheduler.log"
PER_CATEGORY_LIMIT = 40


async def main() -> int:
    started = datetime.now(timezone.utc)
    now = started
    horizon = now + timedelta(days=MAX_RESOLUTION_DAYS)
    lo = now.isoformat().replace("+00:00", "Z")
    hi = horizon.isoformat().replace("+00:00", "Z")
    print(f"[{started.isoformat()}] collection start (window {MAX_RESOLUTION_DAYS}d)")

    judgment = LayaForwardJudgment(LayaClient(mode="remote", preload=False))
    feature_collector = ForwardFeatureCollector(polymarket_source)

    results = []
    total = 0
    try:
        for category in COLLECT_CATEGORIES:
            cohort_id = f"cohort_{category.replace('-', '_')}_{now:%Y%m%d}"
            try:
                markets = await polymarket_source.get_active_markets(
                    category=category,
                    limit=PER_CATEGORY_LIMIT,
                    end_date_min=lo,
                    end_date_max=hi,
                )
            except Exception as exc:
                print(f"  {category}: market fetch failed: {exc}", file=sys.stderr)
                results.append({"category": category, "error": str(exc)})
                continue

            if not markets:
                # An empty category is a legitimate state, not an error: the
                # market may simply not be listed right now.
                print(f"  {category}: 0 markets in window")
                results.append({"category": category, "collected": 0, "reason": "no markets listed in window"})
                continue

            snapshots = await collect_market_batch(
                markets,
                evaluation_id=cohort_id,
                feature_collector=feature_collector,
                judgment=judgment,
                snapshot_path=SNAPSHOT_PATH,
            )
            total += len(snapshots)
            print(f"  {category}: {len(snapshots)}/{len(markets)} snapshots -> {cohort_id}")
            results.append({
                "category": category,
                "candidates": len(markets),
                "collected": len(snapshots),
                "cohort_id": cohort_id,
            })
    finally:
        await polymarket_source.close()
        if getattr(judgment, "client", None) is not None:
            await judgment.client.close()

    summary = {
        "timestamp": started.isoformat(),
        "window_days": MAX_RESOLUTION_DAYS,
        "total_collected": total,
        "results": results,
    }
    log = Path(LOG_PATH)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as handle:
        handle.write(json.dumps(summary) + "\n")
    print(f"[{datetime.now(timezone.utc).isoformat()}] collected {total} snapshot(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
