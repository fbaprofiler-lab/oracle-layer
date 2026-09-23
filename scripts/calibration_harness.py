#!/usr/bin/env python3
"""
Calibration Harness - Run Jev predictions on closed markets and compare with outcomes
Pre-registered evaluation per ORCHESTRATOR.md gates
Uses only stdlib (urllib) to avoid dependency issues
"""

import os
import json
import asyncio
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any
import time
import ssl

# Load environment
env_path = Path('/home/openclaw/.openclaw/workspace/oracle-layer/.env')
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k] = v

TYPESAFE_API_KEY = os.environ.get("TYPESAFE_API_KEY", "")
POLYMARKET_API_KEY = os.environ.get("POLYMARKET_API_KEY", "")

# Pre-registration for this evaluation
EVAL_SPEC = {
    "evaluation_id": f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
    "description": "First calibration evaluation - Jev on closed Polymarket markets",
    "markets_source": "gamma-api.polymarket.com closed markets with outcomePrices",
    "target_n": 100,  # ORCHESTRATOR.md minimum
    "gates": {
        "ece_threshold": 0.05,
        "brier_threshold": 0.20,
        "hit_rate_threshold": 0.55,
        "min_samples": 100,
    },
    "features_used": ["question_text", "latest_market_price", "category"],
    "holdout_period": "market already resolved",
    "registered_at": datetime.now().isoformat(),
}

# Rate limiting
POLYMARKET_RATE_LIMIT = 30  # requests per minute
TYPESAFE_RATE_LIMIT = 20    # requests per minute

last_polymarket = 0
last_typesafe = 0

# SSL context for https
ssl_context = ssl.create_default_context()


def http_get(url: str, params: dict = None, api: str = "polymarket") -> tuple:
    """Rate-limited GET with retries using urllib."""
    global last_polymarket, last_typesafe
    
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    
    # Rate limiting
    if api == "polymarket":
        min_interval = 60.0 / POLYMARKET_RATE_LIMIT
        elapsed = time.time() - last_polymarket
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        last_polymarket = time.time()
    else:
        min_interval = 60.0 / TYPESAFE_RATE_LIMIT
        elapsed = time.time() - last_typesafe
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        last_typesafe = time.time()
    
    headers = {
        'User-Agent': 'OracleLayer/0.1',
        'Accept': 'application/json',
    }
    
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30, context=ssl_context) as r:
                if r.status == 429:
                    wait = 2 ** attempt * 5
                    print(f"  Rate limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** attempt * 5
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("Max retries exceeded")


def http_post(url: str, json_data: dict, api: str = "typesafe") -> tuple:
    """Rate-limited POST with retries using urllib."""
    global last_typesafe
    
    min_interval = 60.0 / TYPESAFE_RATE_LIMIT
    elapsed = time.time() - last_typesafe
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    last_typesafe = time.time()
    
    data = json.dumps(json_data).encode()
    headers = {
        'Authorization': f'Bearer {TYPESAFE_API_KEY}',
        'Content-Type': 'application/json',
        'User-Agent': 'OracleLayer/0.1',
    }
    
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=30, context=ssl_context) as r:
                if r.status == 429:
                    wait = 2 ** attempt * 5
                    print(f"  Rate limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = 2 ** attempt * 5
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            raise
        except Exception as e:
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("Max retries exceeded")


def fetch_closed_markets(limit: int = 200) -> List[Dict]:
    """Fetch closed markets with outcome data."""
    print(f"Fetching closed markets (limit={limit})...")
    status, body = http_get(
        "https://gamma-api.polymarket.com/markets",
        params={"closed": "true", "limit": limit}
    )
    if status != 200:
        raise RuntimeError(f"Failed to fetch markets: {status}")
    markets = json.loads(body)
    resolved = [m for m in markets if m.get('outcomePrices') and m.get('outcomePrices') != '[]']
    print(f"Found {len(resolved)} closed markets with outcome data")
    return resolved


def fetch_latest_price(condition_id: str) -> float:
    """Get latest trade price for a market."""
    try:
        status, body = http_get(
            "https://data-api.polymarket.com/trades",
            params={"market": condition_id, "limit": 1}
        )
        if status == 200:
            trades = json.loads(body)
            if trades:
                return float(trades[0].get('price', 0))
    except Exception as e:
        print(f"  Failed to fetch trades for {condition_id}: {e}")
    return None


def call_jev(question: str, latest_price: float = None) -> Dict:
    """Call Jev SystemOne for a market outcome prediction."""
    state = f"Market: {question}. "
    if latest_price is not None:
        state += f"Current YES probability: {latest_price:.4f}. "
    state += "This market has closed. Predict the probability that YES won (outcome = 1)."
    
    payload = {
        "state": state,
        "model": "jev",
        "questions": {
            "outcome": {
                "type": "noul",
                "instructions": "Did the YES outcome win? Output calibrated probability (0-1)."
            }
        }
    }
    
    status, body = http_post(
        "https://api.typesafe.ai/v1/systemone",
        json_data=payload
    )
    if status != 200:
        raise RuntimeError(f"Jev API error: {status} - {body[:200]}")
    
    result = json.loads(body)
    jev_prob = result.get('answers', {}).get('outcome', {}).get('noul', 0.5)
    confidence = 0.5  # Default
    
    return {
        "probability": max(0.0, min(1.0, float(jev_prob))),
        "confidence": confidence,
        "raw_response": result,
    }


def compute_calibration(results: List[Dict]) -> Dict:
    """Compute calibration metrics: ECE, Brier, reliability curve."""
    if not results:
        return {"status": "no_data"}
    
    n = len(results)
    correct = sum(1 for r in results if r['correct'])
    accuracy = correct / n
    
    # Brier score
    brier = sum((r['jev_prob'] - r['actual_outcome']) ** 2 for r in results) / n
    
    # ECE (Expected Calibration Error) - 10 bins
    bins = 10
    bin_edges = [i / bins for i in range(bins + 1)]
    ece = 0.0
    calibration_curve = []
    
    for i in range(bins):
        low, high = bin_edges[i], bin_edges[i + 1]
        bin_preds = [r for r in results if low <= r['jev_prob'] < high]
        
        if not bin_preds:
            calibration_curve.append({
                "bin": f"{low:.1f}-{high:.1f}", "count": 0, 
                "accuracy": None, "avg_prob": None
            })
            continue
        
        avg_prob = sum(r['jev_prob'] for r in bin_preds) / len(bin_preds)
        bin_accuracy = sum(r['actual_outcome'] for r in bin_preds) / len(bin_preds)
        bin_weight = len(bin_preds) / n
        ece += bin_weight * abs(avg_prob - bin_accuracy)
        
        calibration_curve.append({
            "bin": f"{low:.1f}-{high:.1f}",
            "count": len(bin_preds),
            "accuracy": round(bin_accuracy, 4),
            "avg_prob": round(avg_prob, 4),
        })
    
    # Per-category breakdown
    categories = {}
    for r in results:
        cat = r.get('category', 'unknown')
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(r)
    
    cat_metrics = {}
    for cat, cat_results in categories.items():
        cat_n = len(cat_results)
        cat_correct = sum(1 for r in cat_results if r['correct'])
        cat_brier = sum((r['jev_prob'] - r['actual_outcome']) ** 2 for r in cat_results) / cat_n
        cat_metrics[cat] = {
            "n": cat_n,
            "accuracy": cat_correct / cat_n,
            "brier": round(cat_brier, 4),
        }
    
    return {
        "status": "ok",
        "n": n,
        "accuracy": round(accuracy, 4),
        "brier_score": round(brier, 4),
        "ece": round(ece, 4),
        "calibration_curve": calibration_curve,
        "by_category": cat_metrics,
        "reliability": "good" if ece < 0.05 else "moderate" if ece < 0.10 else "poor",
    }


def run_evaluation(max_markets: int = 100) -> Dict:
    """Run the full calibration evaluation."""
    print(f"\n{'='*60}")
    print(f"ORACLE LAYER - CALIBRATION EVALUATION")
    print(f"Evaluation ID: {EVAL_SPEC['evaluation_id']}")
    print(f"Registered: {EVAL_SPEC['registered_at']}")
    print(f"Target n: {EVAL_SPEC['target_n']}")
    print(f"Gates: ECE<{EVAL_SPEC['gates']['ece_threshold']}, Brier<{EVAL_SPEC['gates']['brier_threshold']}, HitRate>{EVAL_SPEC['gates']['hit_rate_threshold']}")
    print(f"{'='*60}\n")
    
    # Save pre-registration
    with open(f"/home/openclaw/.openclaw/workspace/oracle-layer/eval_prereg_{EVAL_SPEC['evaluation_id']}.json", 'w') as f:
        json.dump(EVAL_SPEC, f, indent=2)
    print(f"Pre-registration saved.")
    
    # Fetch markets
    resolved = fetch_closed_markets(limit=200)
    if len(resolved) < EVAL_SPEC['target_n']:
        print(f"WARNING: Only {len(resolved)} markets available, target was {EVAL_SPEC['target_n']}")
    
    test_markets = resolved[:max_markets]
    print(f"Testing {len(test_markets)} markets...\n")
    
    results = []
    for i, market in enumerate(test_markets, 1):
        condition_id = market.get('conditionId', '')
        question = market.get('question', '')
        category = market.get('category', 'unknown')
        end_date = market.get('endDate', '')
        
        try:
            outcome_prices = json.loads(market.get('outcomePrices', '[]'))
            actual_yes_price = float(outcome_prices[0]) if outcome_prices else 0.0
        except:
            actual_yes_price = 0.0
        
        actual_outcome = 1 if actual_yes_price > 0.5 else 0
        
        print(f"[{i}/{len(test_markets)}] {question[:70]}...")
        print(f"  Category: {category} | End: {end_date} | Actual: {actual_yes_price:.6f} ({'YES' if actual_outcome else 'NO'})")
        
        # Get latest market price before close
        latest_price = fetch_latest_price(condition_id)
        if latest_price:
            print(f"  Latest market price: {latest_price:.4f}")
        
        # Call Jev
        try:
            jev_result = call_jev(question, latest_price)
            jev_prob = jev_result['probability']
            jev_conf = jev_result['confidence']
            print(f"  Jev: P(YES)={jev_prob:.4f}, conf={jev_conf:.2f}")
            
            correct = (jev_prob > 0.5) == (actual_outcome == 1)
            
            results.append({
                "question": question,
                "condition_id": condition_id,
                "category": category,
                "end_date": end_date,
                "actual_outcome": actual_outcome,
                "actual_price": actual_yes_price,
                "latest_market_price": latest_price,
                "jev_prob": round(jev_prob, 4),
                "jev_confidence": round(jev_conf, 4),
                "correct": correct,
                "raw_jev": jev_result['raw_response'],
            })
            
        except Exception as e:
            print(f"  Jev error: {e}")
            results.append({
                "question": question,
                "condition_id": condition_id,
                "category": category,
                "end_date": end_date,
                "actual_outcome": actual_outcome,
                "actual_price": actual_yes_price,
                "latest_market_price": latest_price,
                "jev_prob": None,
                "jev_confidence": None,
                "correct": None,
                "error": str(e),
            })
        
        print()
    
    # Filter valid results
    valid_results = [r for r in results if r['jev_prob'] is not None]
    print(f"\nValid predictions: {len(valid_results)}/{len(results)}")
    
    # Compute metrics
    metrics = compute_calibration(valid_results)
    
    # Gate evaluation
    gate_ece = metrics['ece'] < EVAL_SPEC['gates']['ece_threshold']
    gate_brier = metrics['brier_score'] < EVAL_SPEC['gates']['brier_threshold']
    gate_hitrate = metrics['accuracy'] > EVAL_SPEC['gates']['hit_rate_threshold']
    gate_n = metrics['n'] >= EVAL_SPEC['gates']['min_samples']
    
    gates_passed = sum([gate_ece, gate_brier, gate_hitrate, gate_n])
    
    if gates_passed == 4:
        verdict = "BUILD-1"
    elif gates_passed >= 2:
        verdict = "NARROW + RETEST"
    else:
        verdict = "KILL"
    
    if metrics['n'] < EVAL_SPEC['gates']['min_samples']:
        verdict = "INCONCLUSIVE"
    
    # Final report
    report = {
        "evaluation_spec": EVAL_SPEC,
        "results": results,
        "metrics": metrics,
        "gates": {
            "ece": {"threshold": EVAL_SPEC['gates']['ece_threshold'], "actual": metrics['ece'], "passed": gate_ece},
            "brier": {"threshold": EVAL_SPEC['gates']['brier_threshold'], "actual": metrics['brier_score'], "passed": gate_brier},
            "hit_rate": {"threshold": EVAL_SPEC['gates']['hit_rate_threshold'], "actual": metrics['accuracy'], "passed": gate_hitrate},
            "min_samples": {"threshold": EVAL_SPEC['gates']['min_samples'], "actual": metrics['n'], "passed": gate_n},
        },
        "verdict": verdict,
        "completed_at": datetime.now().isoformat(),
    }
    
    # Save report
    report_path = f"/home/openclaw/.openclaw/workspace/oracle-layer/eval_report_{EVAL_SPEC['evaluation_id']}.json"
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    # Also save to calibration_results.json for compatibility
    with open('/home/openclaw/.openclaw/workspace/oracle-layer/calibration_results.json', 'w') as f:
        json.dump(valid_results, f, indent=2, default=str)
    
    # Print summary
    print(f"\n{'='*60}")
    print(f"EVALUATION COMPLETE - VERDICT: {verdict}")
    print(f"{'='*60}")
    print(f"N: {metrics['n']} (gate: {'PASS' if gate_n else 'FAIL'})")
    print(f"Accuracy: {metrics['accuracy']:.2%} (gate: {'PASS' if gate_hitrate else 'FAIL'} >{EVAL_SPEC['gates']['hit_rate_threshold']:.0%})")
    print(f"Brier Score: {metrics['brier_score']:.4f} (gate: {'PASS' if gate_brier else 'FAIL'} <{EVAL_SPEC['gates']['brier_threshold']})")
    print(f"ECE: {metrics['ece']:.4f} (gate: {'PASS' if gate_ece else 'FAIL'} <{EVAL_SPEC['gates']['ece_threshold']})")
    print(f"Reliability: {metrics['reliability']}")
    print(f"\nCalibration Curve:")
    for bin_data in metrics['calibration_curve']:
        if bin_data['count'] > 0:
            print(f"  {bin_data['bin']}: n={bin_data['count']}, avg_prob={bin_data['avg_prob']:.2f}, accuracy={bin_data['accuracy']:.2%}")
    print(f"\nBy Category:")
    for cat, cat_m in metrics['by_category'].items():
        print(f"  {cat}: n={cat_m['n']}, acc={cat_m['accuracy']:.2%}, brier={cat_m['brier']:.4f}")
    print(f"\nReport saved: {report_path}")
    print(f"Calibration results saved: calibration_results.json")
    
    return report


if __name__ == '__main__':
    run_evaluation(max_markets=100)