"""Hypothesis generator for the evolution layer.

Proposes feature/lag/transform combinations for the fusion engine.
Each hypothesis is a concrete, testable modification to the signal pipeline.
"""
from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
import random


# ─── Hypothesis Space Definition ───

@dataclass
class FeatureHypothesis:
    """A concrete feature hypothesis."""
    name: str
    description: str
    feature_type: str  # "macro", "micro", "derived", "cross"
    extraction_code: str  # Python code to extract the feature
    expected_impact: str  # "macro_transmission", "smart_money", "mispricing", "regime"
    priority: int  # 1-10


@dataclass
class LagHypothesis:
    """A transmission lag hypothesis."""
    chain_name: str
    lag_weeks: int
    rationale: str
    source_series: List[str]
    target_series: List[str]


@dataclass
class TransformHypothesis:
    """A feature transformation hypothesis."""
    name: str
    description: str
    transform_code: str  # Python code: input feature dict -> transformed feature dict
    applies_to: List[str]  # feature names this applies to


@dataclass
class SignalCombinationHypothesis:
    """A signal fusion weight hypothesis."""
    name: str
    macro_weight: float
    market_weight: float
    judgment_weight: float
    rationale: str


# ─── Hypothesis Catalog ───

FEATURE_HYPOTHESES = [
    FeatureHypothesis(
        name="wti_momentum_4w",
        description="4-week WTI momentum as leading indicator for energy markets",
        feature_type="macro",
        extraction_code="""
def extract(context):
    wti = context.get('wti')
    wti_hist = context.get('wti_history', [])
    if wti and len(wti_hist) >= 4:
        return {'wti_momentum_4w': (wti - wti_hist[-4]) / wti_hist[-4] if wti_hist[-4] else 0}
    return {}
""",
        expected_impact="macro_transmission",
        priority=8,
    ),
    FeatureHypothesis(
        name="crack_spread_volatility",
        description="Rolling volatility of gasoline/diesel crack spreads",
        feature_type="macro",
        extraction_code="""
def extract(context):
    gas_crack = context.get('gasoline_crack')
    diesel_crack = context.get('diesel_crack')
    hist = context.get('crack_history', [])
    if gas_crack and diesel_crack and len(hist) >= 8:
        import statistics
        recent = [h.get('gasoline_crack', 0) for h in hist[-8:]]
        return {'crack_vol_8w': statistics.stdev(recent) if len(recent) > 1 else 0}
    return {}
""",
        expected_impact="macro_transmission",
        priority=7,
    ),
    FeatureHypothesis(
        name="smart_money_flow_acceleration",
        description="Rate of change in smart money net flow over last 3 snapshots",
        feature_type="micro",
        extraction_code="""
def extract(market_metrics):
    flow = market_metrics.smart_money_net_flow
    if not flow:
        return {}
    # Would need historical flow snapshots
    # Placeholder for acceleration metric
    return {'smart_money_accel': 0}
""",
        expected_impact="smart_money",
        priority=8,
    ),
    FeatureHypothesis(
        name="wallet_concentration_entropy",
        description="Shannon entropy of wallet volume distribution",
        feature_type="micro",
        extraction_code="""
def extract(market_metrics):
    wallets = market_metrics.smart_money_wallets
    if not wallets:
        return {}
    import math
    total = sum(wallets.values())
    probs = [v/total for v in wallets.values() if v > 0]
    entropy = -sum(p * math.log2(p) for p in probs)
    return {'wallet_entropy': entropy}
""",
        expected_impact="smart_money",
        priority=6,
    ),
    FeatureHypothesis(
        name="mispricing_zscore",
        description="Z-score of current mispricing vs historical distribution",
        feature_type="derived",
        extraction_code="""
def extract(market_metrics, history=None):
    mispricing = market_metrics.mispricing_score
    if history and len(history) >= 20:
        scores = [h.mispricing_score for h in history]
        import statistics
        mean = statistics.mean(history)
        stdev = statistics.stdev(history) if len(history) > 1 else 0.01
        return {'mispricing_zscore': (mispricing - mean) / stdev}
    return {}
""",
        expected_impact="mispricing",
        priority=7,
    ),
    FeatureHypothesis(
        name="macro_micro_interaction",
        description="Cross feature: macro trend * micro momentum",
        feature_type="cross",
        extraction_code="""
def extract(market_metrics, macro_context):
    macro_trend = macro_context.get('wti_momentum_4w', 0)
    micro_momentum = 1 if market_metrics.momentum_signal == 'bullish' else -1 if market_metrics.momentum_signal == 'bearish' else 0
    return {'macro_micro_interaction': macro_trend * micro_momentum}
""",
        expected_impact="macro_transmission",
        priority=9,
    ),
    FeatureHypothesis(
        name="fed_policy_surprise",
        description="Difference between market-implied fed funds and survey expectations",
        feature_type="macro",
        extraction_code="""
def extract(context):
    implied = context.get('fed_funds_implied')
    survey = context.get('fed_funds_survey')
    if implied is not None and survey is not None:
        return {'fed_surprise': implied - survey}
    return {}
""",
        expected_impact="macro_transmission",
        priority=8,
    ),
    FeatureHypothesis(
        name="energy_inflation_passthrough",
        description="Ratio of CPI energy change to crude price change over 8 weeks",
        feature_type="macro",
        extraction_code="""
def extract(context, history=None):
    if history and len(history) >= 8:
        cpi_energy_now = context.get('cpi_energy')
        cpi_energy_then = history[-8].get('cpi_energy')
        wti_now = context.get('wti')
        wti_then = history[-8].get('wti')
        if all(v is not None for v in [cpi_energy_now, cpi_energy_then, wti_now, wti_then]):
            cpi_change = (cpi_energy_now - cpi_energy_then) / cpi_energy_then
            wti_change = (wti_now - wti_then) / wti_then
            if wti_change != 0:
                return {'energy_passthrough': cpi_change / wti_change}
    return {}
""",
        expected_impact="macro_transmission",
        priority=8,
    ),
]

LAG_HYPOTHESES = [
    LagHypothesis(
        chain_name="crude_to_gasoline_retail",
        lag_weeks=1,
        rationale="Faster passthrough in tight markets",
        source_series=["wti"],
        target_series=["gasoline_us"],
    ),
    LagHypothesis(
        chain_name="crude_to_gasoline_retail",
        lag_weeks=3,
        rationale="Slower passthrough with inventory buffers",
        source_series=["wti"],
        target_series=["gasoline_us"],
    ),
    LagHypothesis(
        chain_name="gasoline_to_cpi_energy",
        lag_weeks=3,
        rationale="Faster CPI passthrough",
        source_series=["gasoline_us"],
        target_series=["cpi_energy"],
    ),
    LagHypothesis(
        chain_name="gasoline_to_cpi_energy",
        lag_weeks=5,
        rationale="Slower CPI passthrough",
        source_series=["gasoline_us"],
        target_series=["cpi_energy"],
    ),
    LagHypothesis(
        chain_name="energy_to_fed_policy",
        lag_weeks=8,
        rationale="Fed reacts faster to energy shocks",
        source_series=["wti", "gasoline_crack"],
        target_series=["fed_funds", "breakeven_5y5y"],
    ),
    LagHypothesis(
        chain_name="energy_to_fed_policy",
        lag_weeks=12,
        rationale="Fed reacts with standard lag",
        source_series=["wti", "gasoline_crack"],
        target_series=["fed_funds", "breakeven_5y5y"],
    ),
]

TRANSFORM_HYPOTHESES = [
    TransformHypothesis(
        name="log_return",
        description="Log returns instead of raw prices",
        transform_code="""
def transform(features):
    out = {}
    for k, v in features.items():
        if isinstance(v, (int, float)) and v > 0:
            import math
            out[f'log_{k}'] = math.log(v)
    return out
""",
        applies_to=["wti", "gasoline_us", "diesel_us", "volume_24h"],
    ),
    TransformHypothesis(
        name="zscore_normalize",
        description="Z-score normalization using rolling window",
        transform_code="""
def transform(features, history=None):
    if not history or len(history) < 20:
        return features
    out = {}
    for k, v in features.items():
        if isinstance(v, (int, float)):
            vals = [h.get(k, 0) for h in history[-20:] if k in h]
            if len(vals) > 1:
                import statistics
                mean = statistics.mean(vals)
                stdev = statistics.stdev(vals) if len(vals) > 1 else 0.01
                out[f'{k}_z'] = (v - mean) / stdev
    return out
""",
        applies_to=["wti", "gasoline_us", "diesel_us", "volume_24h", "smart_money_net_flow"],
    ),
    TransformHypothesis(
        name="regime_indicator",
        description="Add regime indicator based on VIX / GPR / vol",
        transform_code="""
def transform(features, macro_context=None):
    out = dict(features)
    gpr = macro_context.get('gpr') if macro_context else None
    vix = macro_context.get('vix') if macro_context else None
    regime = 'normal'
    if gpr and gpr > 150:
        regime = 'high_geopolitical'
    elif vix and vix > 30:
        regime = 'high_vol'
    out['regime'] = regime
    return out
""",
        applies_to=["all"],
    ),
]

SIGNAL_COMBINATION_HYPOTHESES = [
    SignalCombinationHypothesis(
        name="macro_heavy",
        macro_weight=0.5, market_weight=0.2, judgment_weight=0.3,
        rationale="Macro dominates in trending regimes"
    ),
    SignalCombinationHypothesis(
        name="judgment_heavy",
        macro_weight=0.2, market_weight=0.2, judgment_weight=0.6,
        rationale="Jev excels in noisy regimes"
    ),
    SignalCombinationHypothesis(
        name="balanced",
        macro_weight=0.33, market_weight=0.33, judgment_weight=0.34,
        rationale="Default balanced fusion"
    ),
    SignalCombinationHypothesis(
        name="market_heavy",
        macro_weight=0.2, market_weight=0.5, judgment_weight=0.3,
        rationale="Microstructure leads in liquid markets"
    ),
]


# ─── Hypothesis Generator ───

class HypothesisGenerator:
    """Generates concrete, testable hypotheses from the catalog."""
    
    def __init__(self, catalog_path: Optional[Path] = None):
        self.catalog_path = catalog_path or Path("data/evolution/hypothesis_catalog.json")
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
    
    def generate_feature_hypothesis(self, impact_filter: Optional[str] = None) -> FeatureHypothesis:
        """Select a feature hypothesis, optionally filtered by expected impact."""
        candidates = [h for h in FEATURE_HYPOTHESES 
                     if impact_filter is None or h.expected_impact == impact_filter]
        weights = [h.priority for h in candidates]
        return random.choices(candidates, weights=weights, k=1)[0]
    
    def generate_lag_hypothesis(self) -> LagHypothesis:
        return random.choice(LAG_HYPOTHESES)
    
    def generate_transform_hypothesis(self) -> TransformHypothesis:
        return random.choice(TRANSFORM_HYPOTHESES)
    
    def generate_signal_combination_hypothesis(self) -> SignalCombinationHypothesis:
        return random.choice(SIGNAL_COMBINATION_HYPOTHESES)
    
    def generate_full_experiment(self, experiment_id: str) -> dict[str, Any]:
        """Generate a complete experiment configuration."""
        feature_h = self.generate_feature_hypothesis()
        lag_h = self.generate_lag_hypothesis()
        transform_h = self.generate_transform_hypothesis()
        combo_h = self.generate_signal_combination_hypothesis()
        
        config = {
            "experiment_id": experiment_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "feature_hypothesis": asdict(feature_h),
            "lag_hypothesis": asdict(lag_h),
            "transform_hypothesis": asdict(transform_h),
            "signal_combination": asdict(combo_h),
            "status": "pending",
            "sandbox_score": None,
            "charter_verdict": None,
        }
        return config
    
    def save_experiment(self, config: dict[str, Any]) -> Path:
        """Save experiment config to registry."""
        exp_dir = Path("data/evolution/experiments")
        exp_dir.mkdir(parents=True, exist_ok=True)
        exp_path = exp_dir / f"{config['experiment_id']}.json"
        exp_path.write_text(json.dumps(config, indent=2, default=str))
        return exp_path


# ─── CLI ───

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate evolution hypotheses")
    parser.add_argument("--count", type=int, default=1, help="Number of experiments to generate")
    parser.add_argument("--impact", choices=["macro_transmission", "smart_money", "mispricing", "regime"], help="Filter by impact")
    parser.add_argument("--output-dir", default="data/evolution/experiments", help="Output directory")
    args = parser.parse_args()
    
    gen = HypothesisGenerator()
    for i in range(args.count):
        exp_id = f"exp_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{i:03d}"
        config = gen.generate_full_experiment(exp_id)
        exp_path = gen.save_experiment(config)
        print(f"Generated {exp_path}")
        print(json.dumps(config, indent=2, default=str))


if __name__ == "__main__":
    main()
