"""Pure evaluation qualification policy for Oracle Layer runs."""
from __future__ import annotations

from typing import Any, Mapping


def determine_verdict(metrics: Mapping[str, Any], mode: str, gates: Mapping[str, Any]) -> str:
    """Return a charter verdict, never promoting retrospective evidence."""
    normalized = mode.strip().lower()
    if normalized not in {"retrospective", "forward"}:
        raise ValueError("mode must be 'retrospective' or 'forward'")
    if normalized == "retrospective":
        return "RETROSPECTIVE ONLY"

    n = int(metrics.get("n", 0))
    if n < int(gates["min_samples"]):
        return "INCONCLUSIVE"
    passed = (
        float(metrics.get("ece", float("inf"))) < float(gates["ece_threshold"])
        and float(metrics.get("brier_score", float("inf"))) < float(gates["brier_threshold"])
        and float(metrics.get("accuracy", 0)) > float(gates["hit_rate_threshold"])
    )
    return "BUILD-1" if passed else "KILL"
