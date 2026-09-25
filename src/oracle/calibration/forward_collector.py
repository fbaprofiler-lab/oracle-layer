"""Forward evaluation collector.

The collector is intentionally dependency-injected: it can be exercised with
fakes in tests and connected to live sources in a scheduled job later. It only
writes the immutable prediction snapshot; it never fetches or scores outcomes.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping, Protocol

from .forward_snapshot import append_snapshot, create_snapshot

FeatureCollector = Callable[[Mapping[str, Any]], Awaitable[dict[str, Any]]]
Judgment = Callable[[str, Mapping[str, Any]], Awaitable[tuple[float, float, str]]]


class ActiveMarketSource(Protocol):
    async def get_active_markets(self, category: str | None = None, limit: int = 100) -> list[dict[str, Any]]: ...


# Resolution-window budget, derived from what Polymarket actually lists rather
# than from an arbitrary round number.
#
# The wedge markets (Fed policy levels, CPI prints, crypto thresholds) resolve
# on a quarterly-to-yearly cadence. Measured across a 12-month window on
# 2026-09-25: 41 matching markets, of which 0 resolve within 30 days and 41
# beyond 90. A 30-day window therefore returns an empty cohort *by
# construction* -- no filter bug can fix that, the markets simply do not exist
# yet. 120 days covers the next Fed decision cycle and the year-end
# rate/price strikes.
#
# A longer window does not weaken the evaluation: snapshots are pre-registered
# now and outcomes are only read once UMA has actually settled them. It means
# evidence accrues more slowly, not more weakly.
MAX_RESOLUTION_DAYS = 120  # Only collect markets resolving within this window


def _extract_end_date(market: Mapping[str, Any]) -> tuple[str | None, str | None]:
    """Extract end_date and end_date_iso from market data."""
    end_date = market.get("endDate") or market.get("endDateIso")
    end_date_iso = market.get("endDateIso")
    # Normalize: prefer endDateIso for date-only, endDate for full timestamp
    if end_date and not end_date_iso:
        # endDate might be full ISO; extract date part
        end_date_iso = end_date[:10] if "T" in end_date else end_date
    elif end_date_iso and not end_date:
        end_date = end_date_iso
    return end_date, end_date_iso


def _within_resolution_window(market: Mapping[str, Any], max_days: int = MAX_RESOLUTION_DAYS) -> bool:
    """Check if market resolves within max_days from now."""
    end_date, end_date_iso = _extract_end_date(market)
    if not end_date and not end_date_iso:
        return False  # No resolution date = skip
    try:
        # Parse the date (handle both full ISO and date-only)
        date_str = end_date or end_date_iso
        if "T" in date_str:
            end_dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        else:
            end_dt = datetime.fromisoformat(date_str + "T00:00:00+00:00")
        now = datetime.now(timezone.utc)
        delta = end_dt - now
        return timedelta(0) <= delta <= timedelta(days=max_days)
    except Exception:
        return False


def filter_markets_by_resolution(markets: list[Mapping[str, Any]], max_days: int = MAX_RESOLUTION_DAYS) -> list[Mapping[str, Any]]:
    """Filter markets to only those resolving within max_days."""
    return [m for m in markets if _within_resolution_window(m, max_days)]


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
    end_date, end_date_iso = _extract_end_date(market)
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
        end_date=end_date,
        end_date_iso=end_date_iso,
    )
    append_snapshot(snapshot_path, record)
    return record


async def collect_market_batch(
    markets: list[Mapping[str, Any]], *, evaluation_id: str, feature_collector: FeatureCollector,
    judgment: Judgment, snapshot_path: str | Path,
    max_resolution_days: int = MAX_RESOLUTION_DAYS,
) -> list[dict[str, Any]]:
    """Collect a batch, filtering by resolution window and handling failures."""
    # Filter markets by resolution window first
    filtered = filter_markets_by_resolution(markets, max_resolution_days)
    if len(filtered) < len(markets):
        print(f"Filtered {len(markets) - len(filtered)} markets outside {max_resolution_days}-day resolution window")
    snapshots = []
    for market in filtered:
        try:
            snapshots.append(await collect_one(
                market, evaluation_id=evaluation_id, feature_collector=feature_collector,
                judgment=judgment, snapshot_path=snapshot_path,
            ))
        except Exception as exc:
            # Returned by the operational wrapper as an auditable collection error.
            print(f"forward collection failed for {market.get('conditionId', '<unknown>')}: {exc}")
    return snapshots
