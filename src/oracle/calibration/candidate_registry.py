"""Candidate registry for evolution experiments.

Tracks all experiments from sandbox → charter evaluation.
Append-only JSONL store with search/filter capabilities.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, List, Optional


class CandidateRegistry:
    """Append-only registry for evolution experiments."""
    
    def __init__(self, registry_path: Path = Path("data/evolution/candidates.jsonl")):
        self.path = Path(registry_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
    
    def add(self, experiment: Mapping[str, Any]) -> None:
        """Add an experiment to the registry."""
        record = dict(experiment)
        record["registered_at"] = datetime.now(timezone.utc).isoformat()
        record["status"] = experiment.get("status", "pending")
        self._append(record)
    
    def update_status(self, experiment_id: str, status: str, **updates) -> bool:
        """Update experiment status and fields."""
        records = self._read_all()
        for record in records:
            if record.get("experiment_id") == experiment_id:
                record["status"] = status
                record["updated_at"] = datetime.now(timezone.utc).isoformat()
                record.update(updates)
                self._rewrite_all(records)
                return True
        return False
    
    def get(self, experiment_id: str) -> Optional[Mapping[str, Any]]:
        """Get a single experiment by ID."""
        for record in self._read_all():
            if record.get("experiment_id") == experiment_id:
                return record
        return None
    
    def query(
        self,
        status: Optional[str] = None,
        min_sandbox_score: Optional[float] = None,
        max_sandbox_score: Optional[float] = None,
        charter_verdict: Optional[str] = None,
        impact_filter: Optional[str] = None,
        limit: int = 100,
    ) -> List[Mapping[str, Any]]:
        """Query experiments with filters."""
        results = []
        for record in self._read_all():
            if status and record.get("status") != status:
                continue
            if min_sandbox_score is not None and (record.get("sandbox_score") or 0) < min_sandbox_score:
                continue
            if max_sandbox_score is not None and (record.get("sandbox_score") or float('inf')) > max_sandbox_score:
                continue
            if charter_verdict and record.get("charter_verdict") != charter_verdict:
                continue
            if impact_filter and record.get("feature_hypothesis", {}).get("expected_impact") != impact_filter:
                continue
            results.append(record)
            if len(results) >= limit:
                break
        return results
    
    def stats(self) -> dict:
        """Get registry statistics."""
        records = self._read_all()
        stats = {
            "total": len(records),
            "by_status": {},
            "by_verdict": {},
            "by_impact": {},
        }
        for r in records:
            stats["by_status"][r.get("status", "unknown")] = stats["by_status"].get(r.get("status", "unknown"), 0) + 1
            if r.get("charter_verdict"):
                stats["by_verdict"][r["charter_verdict"]] = stats["by_verdict"].get(r["charter_verdict"], 0) + 1
            if r.get("feature_hypothesis", {}).get("expected_impact"):
                stats["by_impact"][r["feature_hypothesis"]["expected_impact"]] = stats["by_impact"].get(r["feature_hypothesis"]["expected_impact"], 0) + 1
        return stats
    
    def _append(self, record: dict) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
    
    def _read_all(self) -> List[dict]:
        if not self.path.exists():
            return []
        records = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return records
    
    def _rewrite_all(self, records: List[dict]) -> None:
        with self.path.open("w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, default=str) + "\n")


# ─── Experiment Runner ───

class ExperimentRunner:
    """Runs experiments through the full pipeline: sandbox → charter eval."""
    
    def __init__(self, registry: CandidateRegistry):
        self.registry = registry
    
    async def run_sandbox_evaluation(self, experiment: dict) -> dict:
        """Run sandbox evaluation on historical data using the real SandboxEvaluator."""
        from .sandbox_evaluator import SandboxEvaluator
        
        evaluator = SandboxEvaluator(min_holdout_samples=1)  # Use 1 for testing with limited data
        result = await evaluator.evaluate(experiment)
        
        return {
            "sandbox_score": result.composite_score,
            "sandbox_ece": result.ece,
            "sandbox_brier": result.brier,
            "sandbox_hit_rate": result.hit_rate,
            "sandbox_n": result.n,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
    
    async def run_charter_evaluation(self, experiment_id: str, cohort_id: str) -> dict:
        """Run full charter evaluation on a cohort."""
        from ..evaluation_runner import run_evaluation_for_cohort
        
        cohort_manifest = f"data/forward/cohorts/{cohort_id}.json"
        snapshots = "data/forward/cohort_snapshots.jsonl"
        outcomes_dir = "data/forward/outcomes"
        
        result = run_evaluation_for_cohort(cohort_manifest, "data/forward/cohort_snapshots.jsonl", "data/forward/outcomes")
        
        return {
            "charter_verdict": result.get("verdict"),
            "charter_ece": result.get("metrics", {}).get("ece"),
            "charter_brier": result.get("metrics", {}).get("brier_score"),
            "charter_hit_rate": result.get("metrics", {}).get("accuracy"),
            "charter_n": result.get("n"),
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
    
    async def run_full_pipeline(self, experiment: dict, cohort_id: str) -> dict:
        """Run full pipeline: sandbox → charter."""
        sandbox_result = await self.run_sandbox_evaluation(experiment)
        
        # Update registry with sandbox results
        self.registry.update_status(
            experiment["experiment_id"],
            "sandbox_complete",
            sandbox_score=sandbox_result.get("sandbox_score"),
            sandbox_ece=sandbox_result.get("sandbox_ece"),
            sandbox_brier=sandbox_result.get("sandbox_brier"),
            sandbox_hit_rate=sandbox_result.get("sandbox_hit_rate"),
        )
        
        # If sandbox passes threshold, run charter evaluation
        if sandbox_result.get("sandbox_score", 0) >= 0.6:  # threshold
            charter_result = await self.run_charter_evaluation(experiment["experiment_id"], cohort_id)
            
            self.registry.update_status(
                experiment["experiment_id"],
                "charter_complete",
                charter_verdict=charter_result.get("charter_verdict"),
                charter_ece=charter_result.get("charter_ece"),
                charter_brier=charter_result.get("charter_brier"),
                charter_hit_rate=charter_result.get("charter_hit_rate"),
            )
            return {**sandbox_result, **charter_result}
        else:
            self.registry.update_status(
                experiment["experiment_id"],
                "sandbox_failed",
                sandbox_score=sandbox_result.get("sandbox_score"),
            )
            return sandbox_result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Evolution experiment runner")
    parser.add_argument("command", choices=["stats", "run", "list"], help="Command")
    parser.add_argument("--experiment-id", help="Experiment ID to run")
    parser.add_argument("--cohort-id", help="Cohort ID for charter evaluation")
    args = parser.parse_args()
    
    registry = CandidateRegistry()
    runner = ExperimentRunner(registry)
    
    if args.command == "stats":
        print(json.dumps(registry.stats(), indent=2))
    elif args.command == "list":
        results = registry.query(limit=20)
        for r in results:
            print(f"{r.get('experiment_id')}: {r.get('status')} | verdict={r.get('charter_verdict')} | score={r.get('sandbox_score')}")
    elif args.command == "run":
        if not args.experiment_id or not args.cohort_id:
            print("Need --experiment-id and --cohort-id")
            return
        experiment = registry.get(args.experiment_id)
        if not experiment:
            print(f"Experiment {args.experiment_id} not found")
            return
        import asyncio
        result = asyncio.run(runner.run_full_pipeline(experiment, args.cohort_id))
        print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
