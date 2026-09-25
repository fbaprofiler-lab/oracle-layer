"""Forward evaluation collector.

The collector is intentionally dependency-injected: it can be exercised with
fakes in tests and connected to live sources in a scheduled job later. It only
writes the immutable prediction snapshot; it never fetches or scores outcomes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Protocol

from .forward_snapshot import append_snapshot, create_snapshot

FeatureCollector = Callable[[Mapping[str, Any]], Awaitable[dict[str, Any]]]
Judgment = Callable[[str, Mapping[str, Any]], Awaitable[tuple[float, float, str]]]


class ActiveMarketSource(Protocol):
    async def get_active_markets(self, category: str | None = None, limit: int = 100) -> list[dict[str, Any]]: ...


async def collect_one(
    market: Mapping[str, Any], *, evaluation_id: str, feature_collector: FeatureCollector,
    judgment: Judgment, snapshot_path: str | Path,
) -> dict[str, Any]:
    """Create and append one forward snapshot for an active market."""
    condition_id = str(market.get("conditionId", ""))
    question = str(market.get("question", ""))
    if not condition_id or not question:
        raise ValueError("market must contain conditionId and question")
    features = await feature_collector(market)
    probability, confidence, backend = await judgment(question, features)
    timestamp = datetime.now(timezone.utc).isoformat()
    record = create_snapshot(
        evaluation_id=evaluation_id,
        prediction_timestamp=timestamp,
        condition_id=condition_id,
        question=question,
        category=str(market.get("category", "unknown")),
        features=features,
        probability=probability,
        confidence=confidence,
        judgment_backend=backend,
    )
    append_snapshot(snapshot_path, record)
    return record


async def collect_market_batch(
    markets: list[Mapping[str, Any]], *, evaluation_id: str, feature_collector: FeatureCollector,
    judgment: Judgment, snapshot_path: str | Path,
) -> list[dict[str, Any]]:
    """Collect a batch without allowing one market failure to hide the rest."""
    snapshots = []
    for market in markets:
        try:
            snapshots.append(await collect_one(
                market, evaluation_id=evaluation_id, feature_collector=feature_collector,
                judgment=judgment, snapshot_path=snapshot_path,
            ))
        except Exception as exc:
            # Returned by the operational wrapper as an auditable collection error.
            print(f"forward collection failed for {market.get('conditionId', '<unknown>')}: {exc}")
    return snapshots
