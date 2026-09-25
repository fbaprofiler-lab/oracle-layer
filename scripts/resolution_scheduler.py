#!/usr/bin/env python3
"""
Resolution Scheduler - Daily cron job to collect outcomes for resolved markets.

This script is designed to run daily (e.g., via cron) to automatically
collect outcomes as markets resolve. It polls all cohort manifests,
checks for resolved markets, and appends outcomes to the separate
outcome store.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from oracle.calibration.resolution_collector import collect_all_cohorts
from oracle.sources.polymarket import polymarket_source


async def main():
    """Run resolution collection for all cohorts."""
    print(f"[{datetime.now(timezone.utc).isoformat()}] Starting resolution collection...")
    
    try:
        results = await collect_all_cohorts(
            cohort_dir="data/forward/cohorts",
            snapshot_path="data/forward/cohort_snapshots.jsonl",
            outcome_dir="data/forward/outcomes",
            market_source=polymarket_source,
            resolution_source="gamma-api",
        )
        
        total_collected = sum(r.get("outcomes_collected", 0) for r in results)
        total_pending = sum(r.get("total_pending", 0) for r in results)
        
        print(f"[{datetime.now(timezone.utc).isoformat()}] Resolution collection complete:")
        print(f"  Total outcomes collected: {total_collected}")
        print(f"  Total markets still pending: {total_pending}")
        
        for r in results:
            if "error" in r:
                print(f"  ERROR ({r.get('manifest', 'unknown')}): {r['error']}")
            else:
                print(f"  {r.get('cohort_id', 'unknown')}: collected={r.get('outcomes_collected', 0)}, pending={r.get('total_pending', 0)}")
        
        # Write summary log
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "total_collected": total_collected,
            "total_pending": total_pending,
            "results": results,
        }
        
        log_dir = Path("data/forward/logs")
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "resolution_scheduler.log"
        
        with log_file.open("a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, default=str) + "\n")
        
        if total_collected > 0:
            print(f"  Logged to {log_file}")
        
        return 0
        
    except Exception as e:
        print(f"[{datetime.now(timezone.utc).isoformat()}] ERROR: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
