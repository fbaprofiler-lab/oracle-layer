"""
Oracle Layer — Macro Transmission Lag Validation
Validates: crude→gasoline→CPI→Fed→rates markets chain has predictive signal.
Required for GO gate: ≥2 evaluations showing predictive signal in ≥2 lag chains.
"""

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
import numpy as np


@dataclass
class LagChainResult:
    """Result for a single macro transmission lag chain."""
    chain_name: str
    lag_weeks: int
    n_observations: int
    correlation: float
    p_value: float
    predictive_accuracy: float
    signal_strength: str  # strong, moderate, weak, none
    passes_gate: bool


class MacroTransmissionValidator:
    """
    Validates macro transmission chains using historical data.
    Tests whether energy→inflation→Fed→prediction markets lags have predictive signal.
    """

    # Defined lag chains from ORCHESTRATOR.md + fuel-briefing design
    LAG_CHAINS = {
        "crude_to_gasoline_retail": {
            "source": ("eia", "crude_runs"),
            "target": ("eia", "gasoline_us"),
            "lag_weeks": 2,
            "description": "Crude runs → retail gasoline price (2 weeks)",
        },
        "crude_to_diesel_retail": {
            "source": ("fred", "wti"),
            "target": ("eia", "diesel_us"),
            "lag_weeks": 2,
            "description": "WTI crude → retail diesel price (2 weeks)",
        },
        "gasoline_to_cpi_energy": {
            "source": ("eia", "gasoline_us"),
            "target": ("fred", "cpi_energy"),
            "lag_weeks": 4,
            "description": "Retail gasoline → CPI Energy (4 weeks)",
        },
        "diesel_to_freight": {
            "source": ("eia", "diesel_us"),
            "target": ("fred", "cass_freight"),
            "lag_weeks": 3,
            "description": "Diesel price → Cass Freight Index (3 weeks)",
        },
        "diesel_to_food_cpi": {
            "source": ("eia", "diesel_us"),
            "target": ("fred", "cpi_all"),
            "lag_weeks": 6,
            "description": "Diesel → Food CPI via transport (6 weeks)",
        },
        "energy_to_core_cpi": {
            "source": ("fred", "cpi_energy"),
            "target": ("fred", "cpi_all"),
            "lag_weeks": 8,
            "description": "Energy CPI → Core CPI (8 weeks)",
        },
        "energy_to_fed_policy": {
            "source": ("fred", "cpi_energy"),
            "target": ("fred", "fed_funds"),
            "lag_weeks": 10,
            "description": "Energy inflation → Fed funds rate (10 weeks)",
        },
        "fed_policy_to_rates_markets": {
            "source": ("fred", "fed_funds"),
            "target": ("polymarket", "fed-rate-decisions"),
            "lag_weeks": 1,
            "description": "Fed policy → Fed rate decision markets (1 week)",
        },
        "gpr_to_crude": {
            "source": ("fred", "gpr"),
            "target": ("fred", "wti"),
            "lag_weeks": 0,
            "description": "Geopolitical risk → Crude oil (immediate)",
        },
        "cracks_to_chemicals_ppi": {
            "source": ("computed", "gasoline_crack"),
            "target": ("fred", "cpi_all"),
            "lag_weeks": 7,
            "description": "Crack spreads → Chemicals PPI (7 weeks)",
        },
    }

    def __init__(self):
        self.results: List[LagChainResult] = []

    def load_historical_data(self, data_dir: str = "/home/openclaw/.openclaw/workspace/oracle-layer") -> Dict[str, List[Dict]]:
        """Load historical macro data from evaluation files or cached data."""
        macro_data = defaultdict(list)
        
        eval_files = list(Path(data_dir).glob("eval_report_eval_*.json"))
        for ef in eval_files:
            with open(ef) as f:
                report = json.load(f)
            
            for r in report.get("results", []):
                context = r.get("macro_context", {})
                if context:
                    ts = r.get("timestamp") or report.get("completed_at", datetime.now().isoformat())
                    try:
                        dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                    except:
                        dt = datetime.now()
                    
                    for key, value in context.items():
                        if isinstance(value, (int, float)):
                            macro_data[key].append({"timestamp": dt, "value": value})
        
        return macro_data

    def compute_changes(self, series: List[Dict], lag_weeks: int) -> List[Tuple[float, float]]:
        """Compute (source_change, target_change) pairs with lag."""
        if len(series) < lag_weeks + 2:
            return []
        
        series = sorted(series, key=lambda x: x["timestamp"])
        
        pairs = []
        for i in range(len(series) - lag_weeks):
            source_now = series[i]["value"]
            source_prev = series[i - 1]["value"] if i > 0 else source_now
            target_now = series[i + lag_weeks]["value"]
            target_prev = series[i + lag_weeks - 1]["value"] if i + lag_weeks > 0 else target_now
            
            source_change = (source_now - source_prev) / abs(source_prev) if source_prev != 0 else 0
            target_change = (target_now - target_prev) / abs(target_prev) if target_prev != 0 else 0
            
            pairs.append((source_change, target_change))
        
        return pairs

    def test_chain(self, chain_name: str, macro_data: Dict[str, List[Dict]]) -> LagChainResult:
        """Test a single lag chain for predictive signal."""
        chain = self.LAG_CHAINS[chain_name]
        source_key = f"{chain['source'][0]}_{chain['source'][1]}"
        target_key = f"{chain['target'][0]}_{chain['target'][1]}"
        
        if chain["source"][0] == "computed":
            source_key = chain["source"][1]
        
        source_series = macro_data.get(source_key, [])
        target_series = macro_data.get(target_key, [])
        
        if len(source_series) < 10 or len(target_series) < 10:
            return LagChainResult(
                chain_name=chain_name,
                lag_weeks=chain["lag_weeks"],
                n_observations=min(len(source_series), len(target_series)),
                correlation=0.0,
                p_value=1.0,
                predictive_accuracy=0.5,
                signal_strength="none",
                passes_gate=False,
            )
        
        pairs = self.compute_changes(source_series, chain["lag_weeks"])
        
        if len(pairs) < 10:
            return LagChainResult(
                chain_name=chain_name,
                lag_weeks=chain["lag_weeks"],
                n_observations=len(pairs),
                correlation=0.0,
                p_value=1.0,
                predictive_accuracy=0.5,
                signal_strength="none",
                passes_gate=False,
            )
        
        source_changes = [p[0] for p in pairs]
        target_changes = [p[1] for p in pairs]
        
        corr_matrix = np.corrcoef(source_changes, target_changes)
        correlation = corr_matrix[0, 1] if not np.isnan(corr_matrix[0, 1]) else 0.0
        
        correct = sum(1 for s, t in pairs if (s > 0) == (t > 0))
        predictive_accuracy = correct / len(pairs)
        
        n = len(pairs)
        if abs(correlation) < 1.0:
            t_stat = correlation * math.sqrt((n - 2) / (1 - correlation**2))
            p_value = 2 * (1 - 0.5 * (1 + math.erf(abs(t_stat) / math.sqrt(2)))) if n > 2 else 1.0
        else:
            p_value = 0.0
        
        if abs(correlation) > 0.3 and p_value < 0.05 and predictive_accuracy > 0.55:
            signal_strength = "strong"
        elif abs(correlation) > 0.2 and p_value < 0.1 and predictive_accuracy > 0.52:
            signal_strength = "moderate"
        elif abs(correlation) > 0.1:
            signal_strength = "weak"
        else:
            signal_strength = "none"
        
        passes_gate = signal_strength in ("strong", "moderate") and predictive_accuracy > 0.55
        
        return LagChainResult(
            chain_name=chain_name,
            lag_weeks=chain["lag_weeks"],
            n_observations=len(pairs),
            correlation=round(correlation, 4),
            p_value=round(p_value, 4),
            predictive_accuracy=round(predictive_accuracy, 4),
            signal_strength=signal_strength,
            passes_gate=passes_gate,
        )

    def validate_all(self, macro_data: Dict[str, List[Dict]] = None) -> Dict[str, Any]:
        """Validate all lag chains."""
        if macro_data is None:
            macro_data = self.load_historical_data()
        
        results = []
        for chain_name in self.LAG_CHAINS:
            result = self.test_chain(chain_name, macro_data)
            results.append(result)
            self.results.append(result)
        
        passing = [r for r in results if r.passes_gate]
        
        return {
            "validated_at": datetime.now().isoformat(),
            "chains_tested": len(results),
            "chains_passing": len(passing),
            "gate_requirement": "≥2 chains with predictive signal in ≥2 evaluations",
            "current_passing": [r.chain_name for r in passing],
            "results": [
                {
                    "chain": r.chain_name,
                    "lag_weeks": r.lag_weeks,
                    "n": r.n_observations,
                    "correlation": r.correlation,
                    "p_value": r.p_value,
                    "predictive_accuracy": r.predictive_accuracy,
                    "signal_strength": r.signal_strength,
                    "passes_gate": r.passes_gate,
                }
                for r in results
            ],
            "summary": {
                "strong_signals": len([r for r in results if r.signal_strength == "strong"]),
                "moderate_signals": len([r for r in results if r.signal_strength == "moderate"]),
                "weak_signals": len([r for r in results if r.signal_strength == "weak"]),
                "no_signal": len([r for r in results if r.signal_strength == "none"]),
            }
        }

    def validate_from_evaluations(self, eval_files: List[str]) -> Dict[str, Any]:
        """Validate using macro context from evaluation reports."""
        macro_data = defaultdict(list)
        
        for ef in eval_files:
            with open(ef) as f:
                report = json.load(f)
            
            for r in report.get("results", []):
                context = r.get("macro_context", {})
                ts = r.get("timestamp") or report.get("completed_at", datetime.now().isoformat())
                try:
                    dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
                except:
                    dt = datetime.now()
                
                key_map = {
                    "wti": "fred_wti",
                    "brent": "fred_brent",
                    "gasoline_crack": "computed_gasoline_crack",
                    "diesel_crack": "computed_diesel_crack",
                    "gpr": "fred_gpr",
                    "dxy": "fred_dxy",
                    "fed_funds": "fred_fed_funds",
                    "breakeven_5y5y": "fred_breakeven_5y5y",
                    "cass_freight": "fred_cass_freight",
                    "cpi_energy": "fred_cpi_energy",
                    "cpi_all": "fred_cpi_all",
                }
                
                for k, v in context.items():
                    if isinstance(v, (int, float)) and k in key_map:
                        macro_data[key_map[k]].append({"timestamp": dt, "value": v})
        
        return self.validate_all(macro_data)


if __name__ == "__main__":
    validator = MacroTransmissionValidator()
    
    eval_files = [
        "/home/openclaw/.openclaw/workspace/oracle-layer/eval_report_eval_20260920_171015.json",
        "/home/openclaw/.openclaw/workspace/oracle-layer/eval_report_eval_20260920_172200.json",
        "/home/openclaw/.openclaw/workspace/oracle-layer/eval_report_eval_final_20260920_180142.json",
        "/home/openclaw/.openclaw/workspace/oracle-layer/eval_report_eval_ablation_20260920_173921.json",
    ]
    
    result = validator.validate_from_evaluations(eval_files)
    print(json.dumps(result, indent=2))
    
    with open("/home/openclaw/.openclaw/workspace/oracle-layer/macro_transmission_validation.json", "w") as f:
        json.dump(result, f, indent=2, default=str)
    
    print("\nMacro transmission validation complete.")
