"""Resolution adapter for forward outcomes.

This module is intentionally separate from prediction collection. It reads a
resolved market only when called and appends an outcome artifact; it never
opens or rewrites the prediction snapshot store.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .outcomes import append_outcome, create_outcome, read_snapshots


def _parse_outcome_timestamp(market: Mapping[str, Any]) -> str | None:
    for key in ("resolutionTimestamp", "resolvedAt", "endDate"):
        value = market.get(key)
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
    return None


def _resolved_outcome(market: Mapping[str, Any]) -> tuple[int, float] | None:
    # A market is resolved only when Gamma explicitly marks it closed or
    # provides a completed resolution status. resolvedBy alone is routing
    # metadata and must not turn an active market into an outcome.
    resolution_status = str(market.get("umaResolutionStatus") or "").lower()
    resolved_flag = bool(market.get("closed")) or resolution_status in {"resolved", "settled", "finalized"}
    if not resolved_flag:
        return None
    prices = market.get("outcomePrices")
    if isinstance(prices, str):
        import json
        try:
            prices = json.loads(prices)
        except json.JSONDecodeError:
            return None
    if not isinstance(prices, list) or not prices:
        return None
    try:
        yes_price = float(prices[0])
    except (TypeError, ValueError):
        return None
    if not 0.0 <= yes_price <= 1.0:
        return None
    return (1 if yes_price > 0.5 else 0), yes_price


async def collect_outcome_for_snapshot(
    snapshot: Mapping[str, Any], *, market_source: Any, outcome_path: str | Path,
    resolution_source: str = "gamma-api",
) -> dict[str, Any] | None:
    """Fetch and append one outcome, or return None if still unresolved."""
    market = await market_source.get_market_details(str(snapshot["condition_id"]))
    if not market:
        return None
    resolved = _resolved_outcome(market)
    outcome_timestamp = _parse_outcome_timestamp(market)
    # endDate is a scheduled future boundary, not proof of resolution.
    if outcome_timestamp and not (market.get("closed") or str(market.get("umaResolutionStatus") or "").lower() in {"resolved", "settled", "finalized"}):
        outcome_timestamp = None
    if resolved is None or outcome_timestamp is None:
        return None
    actual_outcome, actual_price = resolved
    record = create_outcome(
        snapshot_id=str(snapshot["snapshot_id"]),
        condition_id=str(snapshot["condition_id"]),
        outcome_timestamp=outcome_timestamp,
        actual_outcome=actual_outcome,
        actual_price=actual_price,
        resolution_source=resolution_source,
    )
    append_outcome(outcome_path, record)
    return record


async def collect_outcomes_for_snapshots(
    snapshot_path: str | Path, *, market_source: Any, outcome_path: str | Path,
    resolution_source: str = "gamma-api",
) -> list[dict[str, Any]]:
    """Resolve all snapshots independently; no prediction artifact is changed."""
    outcomes = []
    for snapshot in read_snapshots(snapshot_path):
        try:
            outcome = await collect_outcome_for_snapshot(
                snapshot, market_source=market_source, outcome_path=outcome_path,
                resolution_source=resolution_source,
            )
            if outcome is not None:
                outcomes.append(outcome)
        except ValueError as exc:
            # An already-recorded outcome is idempotently skipped on reruns.
            if "already exists" not in str(exc):
                raise
    return outcomes
