"""Leakage and pre-verdict honesty checks for Oracle Layer evaluations.

The scanner accepts pre-registration, raw prediction, and report JSON files. It
is deliberately conservative: missing enhanced fields are findings, not proof
of safety. File glob patterns are supported by the CLI and API layer.
"""
from __future__ import annotations

import argparse
import glob
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REQUIRED_FIELDS = (
    "macro_context",
    "smart_money_net_flow",
    "prediction_timestamp",
    "outcome_timestamp",
)


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _load(path: str) -> tuple[Any, str | None]:
    matches = sorted(glob.glob(path))
    if not matches:
        return None, f"file_not_found:{path}"
    selected = matches[-1]
    try:
        text = Path(selected).read_text(encoding="utf-8")
        # Forward snapshot and outcome stores are JSONL artifacts. Try the
        # document form first, then parse each non-empty line.
        try:
            return json.loads(text), None
        except json.JSONDecodeError:
            records = []
            for line_number, line in enumerate(text.splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    return None, f"file_read_error:{selected}:{line_number}:{exc}"
            return records, None
    except OSError as exc:
        return None, f"file_read_error:{selected}:{exc}"


def _records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("results"), list):
            return [item for item in payload["results"] if isinstance(item, dict)]
        if isinstance(payload.get("raw_results"), list):
            return [item for item in payload["raw_results"] if isinstance(item, dict)]
        # A JSONL artifact containing exactly one record parses as a dict.
        if any(field in payload for field in REQUIRED_FIELDS):
            return [payload]
    return []


def _finding(kind: str, severity: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"type": kind, "severity": severity, "detail": detail, **extra}


def _scan_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        missing = [field for field in REQUIRED_FIELDS if field not in record or record[field] is None]
        if missing:
            findings.append(_finding(
                "MISSING_ENHANCED_FIELDS", "high",
                f"record {index} missing {', '.join(missing)}",
                record_index=index, fields=missing,
            ))

        prediction = _parse_timestamp(record.get("prediction_timestamp"))
        outcome = _parse_timestamp(record.get("outcome_timestamp"))
        if record.get("prediction_timestamp") and prediction is None:
            findings.append(_finding("INVALID_PREDICTION_TIMESTAMP", "high", f"record {index} has invalid prediction_timestamp", record_index=index))
        if record.get("outcome_timestamp") and outcome is None:
            findings.append(_finding("INVALID_OUTCOME_TIMESTAMP", "high", f"record {index} has invalid outcome_timestamp", record_index=index))
        if prediction and outcome and prediction >= outcome:
            findings.append(_finding(
                "LOOKAHEAD_BIAS", "critical",
                f"record {index} prediction_timestamp is not before outcome_timestamp",
                record_index=index,
            ))

        probability = record.get("jev_prob")
        actual = record.get("actual_outcome")
        if isinstance(probability, (int, float)) and isinstance(actual, (int, float)):
            if probability in (0.0, 1.0) and int(probability) == int(actual):
                findings.append(_finding(
                    "SUSPICIOUS_CERTAINTY", "medium",
                    f"record {index} has perfect certainty and matching outcome",
                    record_index=index,
                ))
    return findings


def run_leakage_scan(pre_reg_file: str, raw_data_file: str | None = None, eval_report_file: str | None = None) -> dict[str, Any]:
    """Scan one evaluation's artifacts and return an API/CLI-compatible report."""
    findings: list[dict[str, Any]] = []
    loaded: dict[str, Any] = {}
    for label, path in (("prereg", pre_reg_file), ("raw", raw_data_file), ("report", eval_report_file)):
        if not path:
            continue
        payload, error = _load(path)
        loaded[label] = payload
        if error:
            findings.append(_finding("MISSING_ARTIFACT", "critical", error, artifact=label, path=path))

    prereg = loaded.get("prereg")
    raw_records = _records(loaded.get("raw"))
    report = loaded.get("report") or {}
    report_records = _records(report)
    records = raw_records or report_records
    if raw_records and report_records and len(raw_records) != len(report_records):
        findings.append(_finding("ARTIFACT_COUNT_MISMATCH", "high", f"raw n={len(raw_records)} differs from report n={len(report_records)}"))

    if prereg is not None:
        features = set(prereg.get("features_used", []))
        required_features = {"macro_context", "smart_money_net_flow"}
        if not required_features.issubset(features):
            findings.append(_finding("PREREG_FEATURE_MISMATCH", "high", f"pre-registration omits {sorted(required_features - features)}"))
        if not prereg.get("registered_at"):
            findings.append(_finding("PREREG_TIMESTAMP_MISSING", "high", "pre-registration has no registered_at"))
    if not records:
        findings.append(_finding("NO_RECORDS", "high", "no raw or report records were available to scan"))

    findings.extend(_scan_records(records))
    by_type: dict[str, int] = {}
    by_severity: dict[str, int] = {}
    for finding in findings:
        by_type[finding["type"]] = by_type.get(finding["type"], 0) + 1
        by_severity[finding["severity"]] = by_severity.get(finding["severity"], 0) + 1
    return {
        "total_findings": len(findings),
        "by_severity": by_severity,
        "by_type": by_type,
        "critical_count": by_severity.get("critical", 0),
        "pass": not findings,
        "findings": findings,
        "total_markets": len(records),
        "artifacts": {"prereg": pre_reg_file, "raw": raw_data_file, "report": eval_report_file},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prereg")
    parser.add_argument("raw_data", nargs="?")
    parser.add_argument("eval_report", nargs="?")
    args = parser.parse_args()
    result = run_leakage_scan(args.prereg, args.raw_data, args.eval_report)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["pass"] else 1)


if __name__ == "__main__":
    main()
