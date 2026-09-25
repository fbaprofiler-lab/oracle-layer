#!/usr/bin/env python3
"""
Collect near-term markets using the fixed end_date filter.
Fetches multiple pages to get enough markets to find near-term ones.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from oracle.sources.polymarket import polymarket_source
from oracle.calibration.forward_collector import collect_market_batch, filter_markets_by_resolution
from oracle.calibration.forward_adapters import ForwardFeatureCollector, LayaForwardJudgment
from oracle.judgment.laya_client import LayaClient
from oracle.calibration.forward_snapshot import read_snapshots
from oracle.calibration.cohorts import create_cohort_manifest, write_manifest


async def fetch_all_markets(source, max_pages=5, limit=100):
    """Fetch multiple pages of markets."""
    all_markets = []
    for page in range(max_pages):
        markets = await source.get_active_markets(limit=limit)
        if not markets:
            break
        all_markets.extend(markets)
        # Check if we got fewer than requested (end of results)
        if len(markets) < limit:
            break
    return all_markets


async def main():
    print("Fetching active markets from Polymarket (multiple pages)...")
    markets = await fetch_all_markets(polymarket_source, max_pages=5, limit=100)
    print(f"Total markets fetched: {len(markets)}")

    # Filter by resolution window (30 days)
    filtered = filter_markets_by_resolution(markets, max_days=30)
    print(f"Markets within 30-day resolution window: {len(filtered)}")

    if not filtered:
        print("No near-term markets found. Trying with 90-day window...")
        filtered = filter_markets_by_resolution(markets, max_days=90)
        print(f"Markets within 90-day resolution window: {len(filtered)}")
        
        if filtered:
            print(f"\nNear-term markets (90 days):")
            for m in filtered[:20]:
                end_date = m.get("endDateIso", "unknown")
                print(f"  {end_date} | {m['question'][:80]}")

    if not filtered:
        print("Still no near-term markets. Showing earliest end dates...")
        end_dates = []
        for m in markets:
            end_date_iso = m.get("endDateIso", "")
            if end_date_iso:
                end_dates.append((end_date_iso, m["question"][:80]))
        end_dates.sort()
        for d, q in end_dates[:20]:
            print(f"  {d} | {q}")
        return

    print(f"\nNear-term markets:")
    for m in filtered[:20]:
        end_date = m.get("endDateIso", "unknown")
        print(f"  {end_date} | {m['question'][:80]}")

    # Create feature collector and judgment
    from oracle.sources.eia import eia_source
    from oracle.sources.fred import fred_source
    
    feature_collector = ForwardFeatureCollector(polymarket_source, eia_source, fred_source)
    laya_client = LayaClient(base_url="http://localhost:8000")
    judgment = LayaForwardJudgment(laya_client)

    # Collect snapshots
    evaluation_id = "near_term_collection_20260925"
    snapshot_path = "data/forward/cohort_snapshots.jsonl"

    print(f"\nCollecting snapshots for {len(filtered)} markets...")
    snapshots = await collect_market_batch(
        filtered,
        evaluation_id=evaluation_id,
        feature_collector=feature_collector,
        judgment=judgment,
        snapshot_path=snapshot_path,
        max_resolution_days=90,
    )

    print(f"\nCollected {len(snapshots)} snapshots")

    # Show existing snapshots
    all_snaps = read_snapshots(snapshot_path)
    print(f"Total snapshots in store: {len(all_snaps)}")

    # Create cohort manifest
    manifest = create_cohort_manifest(
        cohort_id="cohort_near_term_20260925",
        selection_criteria={"active": True, "max_resolution_days": 90, "limit": len(filtered)},
        markets=filtered,
        features=["question_text", "latest_market_price", "category", "macro_context", "smart_money_net_flow"],
        gates={"ece_threshold": 0.05, "brier_threshold": 0.20, "hit_rate_threshold": 0.55, "min_samples": 100},
        target_n=len(filtered),
    )

    manifest_path = "data/forward/cohorts/cohort_near_term_20260925.json"
    write_manifest(manifest_path, manifest)
    print(f"Cohort manifest written: {manifest_path}")


if __name__ == "__main__":
    asyncio.run(main())
