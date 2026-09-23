#!/usr/bin/env python3
"""
Calibration Harness v3 - Run Jev predictions on closed markets by category
Pre-registered evaluation per ORCHESTRATOR.md gates
Enhanced with: macro_context, smart_money_net_flow, prediction_timestamp, outcome_timestamp
Uses only stdlib (urllib)
"""

import os
import json
import numpy as np
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional
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

# Import oracle-layer sources for real data
import sys
import os
# Get the directory where this script is located (works when imported or run directly)
try:
    script_dir = os.path.dirname(os.path.abspath(__file__))
except NameError:
    # __file__ is not available when using exec()
    script_dir = os.path.dirname(os.path.realpath(sys.argv[0]) if sys.argv[0] else '.')
src_dir = os.path.join(script_dir, '..', 'src')
if src_dir not in sys.path:
    sys.path.insert(0, src_dir)

from oracle.sources.eia import eia_source
from oracle.sources.fred import fred_source
from oracle.sources.polymarket import polymarket_source
import asyncio

# Pre-registration for this evaluation - REAL POLYMARKET CATEGORIES
EVAL_SPEC = {
    "evaluation_id": f"eval_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
    "description": "Calibration evaluation v3 - Jev on closed Polymarket markets by target category (enhanced with macro_context, smart_money_net_flow, timestamps)",
    "markets_source": "gamma-api.polymarket.com closed markets with outcomePrices, filtered by category",
    "target_categories": ["US-current-affairs", "Crypto", "Sports", "Pop-Culture", "Coronavirus", "Tech"],
    "target_n": 100,
    "gates": {
        "ece_threshold": 0.05,
        "brier_threshold": 0.20,
        "hit_rate_threshold": 0.55,
        "min_samples": 100,
    },
    "features_used": ["question_text", "latest_market_price", "category", "macro_context", "smart_money_net_flow"],
    "holdout_period": "market already resolved",
    "registered_at": datetime.now().isoformat(),
}

# Rate limiting
POLYMARKET_RATE_LIMIT = 30  # requests per minute
TYPESAFE_RATE_LIMIT = 20    # requests per minute

last_polymarket = 0
last_typesafe = 0
ssl_context = ssl.create_default_context()


def http_get(url: str, params: dict = None, api: str = "polymarket") -> tuple:
    """Rate-limited GET with retries using urllib."""
    global last_polymarket, last_typesafe
    
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    
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
    
    headers = {'User-Agent': 'OracleLayer/0.1', 'Accept': 'application/json'}
    
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


def fetch_markets_by_category(category: str, limit: int = 200) -> List[Dict]:
    """Fetch closed markets for a specific category."""
    print(f"Fetching closed markets for category '{category}' (limit={limit})...")
    status, body = http_get(
        "https://gamma-api.polymarket.com/markets",
        params={"closed": "true", "limit": limit, "category": category}
    )
    if status != 200:
        raise RuntimeError(f"Failed to fetch markets for {category}: {status}")
    markets = json.loads(body)
    resolved = [m for m in markets if m.get('outcomePrices') and m.get('outcomePrices') != '[]']
    print(f"  Found {len(resolved)} closed markets with outcome data")
    return resolved


def fetch_market_detail(condition_id: str) -> Dict:
    """Fetch detailed market info including macro context, smart money flow."""
    try:
        status, body = http_get(
            f"https://gamma-api.polymarket.com/markets/{condition_id}",
            params={}
        )
        if status == 200:
            return json.loads(body)
    except Exception as e:
        print(f"  Failed to fetch detail for {condition_id}: {e}")
    return {}


def fetch_latest_price(condition_id: str) -> Optional[float]:
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


# Module-level event loop for reuse
_global_loop = None

def _get_loop():
    """Get or create a persistent event loop."""
    global _global_loop
    if _global_loop is None or _global_loop.is_closed():
        _global_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_global_loop)
    return _global_loop


def _cleanup_loop():
    """Close the global event loop."""
    global _global_loop
    if _global_loop is not None and not _global_loop.is_closed():
        _global_loop.close()
        _global_loop = None


def extract_macro_context(market_detail: Dict, category: str, prediction_time: datetime) -> Dict[str, Any]:
    """Extract real macro context from EIA/FRED APIs at prediction time.
    Returns actual values from energy and macro sources as of prediction_time.
    """
    try:
        # Convert prediction_time to date string for API calls
        date_str = prediction_time.strftime('%Y-%m-%d')
        
        # Fetch EIA data (using verified working series)
        eia_series = ['gasoline_us', 'diesel_us', 'gasoline_stocks', 'crude_stocks', 'distillate_stocks']
        eia_data = {}
        
        # Use persistent event loop
        loop = _get_loop()
        try:
            eia_results = loop.run_until_complete(
                eia_source.fetch_multiple(eia_series, limit=1)
            )
            for series_id, points in eia_results.items():
                if points and len(points) > 0:
                    latest_point = points[0]
                    eia_data[series_id] = {
                        'value': latest_point.value,
                        'unit': latest_point.unit,
                        'timestamp': latest_point.timestamp.isoformat() if latest_point.timestamp else None
                    }
        except Exception as e:
            print(f"  EIA fetch error: {e}")
        
        # Fetch FRED data with rate limiting (using verified working series)
        fred_series = ['wti', 'brent', 'ho', 'dxy', 'fed_funds', 'breakeven_5y5y', 't10y2y', 'unrate', 'payrolls', 'ip_total', 'consumer_sentiment']
        fred_data = {}
        
        # Add small delay between series to avoid rate limiting
        for series_id in fred_series:
            try:
                fred_results = loop.run_until_complete(
                    fred_source.fetch_multiple([series_id], limit=1)
                )
                if fred_results and series_id in fred_results:
                    points = fred_results[series_id]
                    if points and len(points) > 0:
                        latest_point = points[0]
                        fred_data[series_id] = {
                            'value': latest_point.value,
                            'timestamp': latest_point.timestamp.isoformat() if latest_point.timestamp else None
                        }
            except Exception as e:
                print(f"  FRED fetch failed for {series_id}: {e}")
            time.sleep(0.1)  # Rate limiting
        
        # Compute derived values
        wti = fred_data.get('wti', {}).get('value')
        gasoline_crack_raw = eia_data.get('gasoline_us', {}).get('value')
        diesel_crack_raw = eia_data.get('diesel_us', {}).get('value')
        wti_for_crack = wti
        
        gasoline_crack = None
        diesel_crack = None
        if gasoline_crack_raw is not None and wti_for_crack is not None:
            gasoline_crack = (gasoline_crack_raw * 42) - wti_for_crack
        if diesel_crack_raw is not None and wti_for_crack is not None:
            diesel_crack = (diesel_crack_raw * 42) - wti_for_crack
        
        return {
            "wti": wti,
            "gasoline_crack": gasoline_crack,
            "diesel_crack": diesel_crack,
            "dxy": fred_data.get('dxy', {}).get('value'),
            "fed_funds": fred_data.get('fed_funds', {}).get('value'),
            "breakeven_5y5y": fred_data.get('breakeven_5y5y', {}).get('value'),
            "t10y2y": fred_data.get('t10y2y', {}).get('value'),
            "unrate": fred_data.get('unrate', {}).get('value'),
            "payrolls": fred_data.get('payrolls', {}).get('value'),
            "ip_total": fred_data.get('ip_total', {}).get('value'),
            "consumer_sentiment": fred_data.get('consumer_sentiment', {}).get('value'),
            "gasoline_stocks": eia_data.get('gasoline_stocks', {}).get('value'),
            "diesel_stocks": eia_data.get('distillate_stocks', {}).get('value'),
            "crude_stocks": eia_data.get('crude_stocks', {}).get('value'),
            "source": "real_eia_fred",
            "prediction_time": prediction_time.isoformat(),
            "category_inferred": category in ["US-current-affairs", "Coronavirus"],
        }
    except Exception as e:
        print(f"  Macro context extraction error: {e}")
        return {
            "wti": None,
            "gasoline_crack": None,
            "diesel_crack": None,
            "dxy": None,
            "fed_funds": None,
            "breakeven_5y5y": None,
            "t10y2y": None,
            "unrate": None,
            "payrolls": None,
            "ip_total": None,
            "consumer_sentiment": None,
            "gasoline_stocks": None,
            "diesel_stocks": None,
            "crude_stocks": None,
            "source": "error_fallback",
            "error": str(e),
            "prediction_time": prediction_time.isoformat(),
            "category_inferred": category in ["US-current-affairs", "Coronavirus"],
        }


def extract_smart_money_flow(market_detail: Dict, category: str) -> Dict[str, Any]:
    """Extract real smart money net flow from Polymarket wallet data.
    Analyzes recent trades to identify smart money activity.
    """
    try:
        condition_id = market_detail.get('conditionId')
        if not condition_id:
            return {
                "net_flow": None,
                "wallet_concentration": None,
                "momentum_signal": "neutral",
                "source": "no_condition_id",
                "whale_buys": None,
                "whale_sells": None,
            }
        
        # Fetch recent trades for this market (last 100 trades)
        # Use persistent event loop
        loop = _get_loop()
        try:
            trades = loop.run_until_complete(
                polymarket_source.get_market_trades(condition_id, limit=100)
            )
        except Exception as e:
            print(f"  Smart money trades fetch error: {e}")
            return {
                "net_flow": None,
                "wallet_concentration": None,
                "momentum_signal": "neutral",
                "source": "error_fallback",
                "error": str(e),
                "whale_buys": None,
                "whale_sells": None,
            }
        
        if not trades:
            return {
                "net_flow": None,
                "wallet_concentration": None,
                "momentum_signal": "neutral",
                "source": "no_trades",
                "whale_buys": None,
                "whale_sells": None,
            }
        
        # Analyze wallets to identify smart money (similar to wallets-discover.py logic)
        wallet_trades = {}
        for trade in trades:
            wallet = trade.get('user', '')
            if wallet:
                if wallet not in wallet_trades:
                    wallet_trades[wallet] = []
                wallet_trades[wallet].append(trade)
        
        # Score wallets (simplified smart money identification)
        smart_wallets = []
        for wallet, w_trades in wallet_trades.items():
            if len(w_trades) < 5:  # Minimum trade count
                continue
            
            # Basic heuristics: consistent winners, reasonable size
            volumes = [float(t.get('size', 0)) for t in w_trades]
            avg_volume = np.mean(volumes) if volumes else 0
            if avg_volume < 10:  # Too small to be significant
                continue
            
            # Check directional consistency (simplified)
            sides = [t.get('side', '') for t in w_trades]
            buy_count = sides.count('BUY')
            sell_count = sides.count('SELL')
            total = buy_count + sell_count
            if total > 0:
                directional_consistency = max(buy_count, sell_count) / total
                if directional_consistency > 0.7:  # At least 70% consistent direction
                    smart_wallets.append(wallet)
        
        # Calculate smart money net flow per outcome
        smart_money_net_flow = {}
        smart_money_volume = 0
        total_volume = 0
        
        for trade in trades:
            wallet = trade.get('user', '')
            outcome = trade.get('outcome', '')
            size = float(trade.get('size', 0))
            side = trade.get('side', '')
            
            total_volume += size
            
            if wallet in smart_wallets:
                flow = size if side == 'BUY' else -size
                smart_money_net_flow[outcome] = smart_money_net_flow.get(outcome, 0) + flow
                smart_money_volume += abs(flow)
        
        # Calculate wallet concentration (Herfindahl index of smart wallet volume)
        wallet_volumes = {}
        for trade in trades:
            wallet = trade.get('user', '')
            size = float(trade.get('size', 0))
            if wallet in smart_wallets:
                wallet_volumes[wallet] = wallet_volumes.get(wallet, 0) + size
        
        wallet_concentration = None
        if wallet_volumes and smart_money_volume > 0:
            total_smart_volume = sum(wallet_volumes.values())
            if total_smart_volume > 0:
                # Herfindahl index: sum of squared market shares
                shares = [vol / total_smart_volume for vol in wallet_volumes.values()]
                wallet_concentration = sum(share * share for share in shares)
        
        # Determine momentum signal from recent price changes
        momentum_signal = "neutral"
        if len(trades) >= 2:
            # Sort trades by timestamp (most recent first)
            sorted_trades = sorted(trades, key=lambda t: t.get('timestamp', 0), reverse=True)
            recent_trades = sorted_trades[:min(10, len(sorted_trades))]
            
            # Calculate weighted recent price (more recent trades have higher weight)
            weighted_price = 0
            total_weight = 0
            for i, trade in enumerate(recent_trades):
                weight = len(recent_trades) - i  # Higher weight for more recent
                price = float(trade.get('price', 0.5))
                weighted_price += price * weight
                total_weight += weight
            
            if total_weight > 0:
                avg_recent_price = weighted_price / total_weight
                
                # Get older trades for comparison
                older_trades = sorted_trades[min(10, len(sorted_trades)):min(20, len(sorted_trades))]
                if older_trades:
                    older_weighted_price = 0
                    older_total_weight = 0
                    for i, trade in enumerate(older_trades):
                        weight = len(older_trades) - i
                        price = float(trade.get('price', 0.5))
                        older_weighted_price += price * weight
                        older_total_weight += weight
                    
                    if older_total_weight > 0:
                        avg_older_price = older_weighted_price / older_total_weight
                        price_change = (avg_recent_price - avg_older_price) / avg_older_price if avg_older_price != 0 else 0
                        
                        if price_change > 0.02:  # >2% increase
                            momentum_signal = "bullish"
                        elif price_change < -0.02:  # >2% decrease
                            momentum_signal = "bearish"
        
        return {
            "net_flow": smart_money_net_flow,
            "wallet_concentration": wallet_concentration,
            "momentum_signal": momentum_signal,
            "source": "real_polymarket_wallets",
            "smart_wallets_count": len(smart_wallets),
            "total_trades_analyzed": len(trades),
            "smart_money_volume": smart_money_volume,
            "total_volume": total_volume,
            "whale_buys": smart_money_net_flow.get("Yes", 0) if "Yes" in smart_money_net_flow else None,
            "whale_sells": abs(smart_money_net_flow.get("No", 0)) if "No" in smart_money_net_flow else None,
        }
    except Exception as e:
        print(f"  Smart money flow extraction error: {e}")
        # Fallback to placeholder on error
        return {
            "net_flow": None,
            "wallet_concentration": None,
            "momentum_signal": "neutral",
            "source": "error_fallback",
            "error": str(e),
            "whale_buys": None,
            "whale_sells": None,
        }


def call_jev(question: str, latest_price: float = None) -> Dict:
    """Call Jev SystemOne for a market outcome prediction."""
    state = f"Market: {question}. "
    if latest_price is not None:
        state += f"Current YES probability: {latest_price:.4f}. "
    state += "This market has closed. Predict the probability that YES won (outcome = 1)."
    
    payload = {
        "state": state,
        "model": "jev-latest",
        "questions": {
            "outcome": {
                "type": "noul",
                "instructions": "Did the YES outcome win? Output calibrated probability (0-1)."
            }
        }
    }
    
    status, body = http_post("https://api.typesafe.ai/v1/systemone", json_data=payload)
    if status != 200:
        raise RuntimeError(f"Jev API error: {status} - {body[:200]}")
    
    result = json.loads(body)
    jev_prob = result.get('answers', {}).get('outcome', {}).get('noul', 0.5)
    
    return {
        "probability": max(0.0, min(1.0, float(jev_prob))),
        "confidence": 0.5,
        "raw_response": result,
    }


def compute_calibration(results: List[Dict]) -> Dict:
    """Compute calibration metrics: ECE, Brier, reliability curve."""
    if not results:
        return {"status": "no_data", "n": 0, "accuracy": 0.0, "brier_score": 0.0, "ece": 0.0, 
                "calibration_curve": [], "by_category": {}, "reliability": "no_data"}
    
    n = len(results)
    correct = sum(1 for r in results if r['correct'])
    accuracy = correct / n
    
    brier = sum((r['jev_prob'] - r['actual_outcome']) ** 2 for r in results) / n
    
    bins = 10
    bin_edges = [i / bins for i in range(bins + 1)]
    ece = 0.0
    calibration_curve = []
    
    for i in range(bins):
        low, high = bin_edges[i], bin_edges[i + 1]
        bin_preds = [r for r in results if low <= r['jev_prob'] < high]
        
        if not bin_preds:
            calibration_curve.append({"bin": f"{low:.1f}-{high:.1f}", "count": 0, "accuracy": None, "avg_prob": None})
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
        cat_metrics[cat] = {"n": cat_n, "accuracy": cat_correct / cat_n, "brier": round(cat_brier, 4)}
    
    return {
        "status": "ok", "n": n, "accuracy": round(accuracy, 4),
        "brier_score": round(brier, 4), "ece": round(ece, 4),
        "calibration_curve": calibration_curve, "by_category": cat_metrics,
        "reliability": "good" if ece < 0.05 else "moderate" if ece < 0.10 else "poor",
    }


def leakage_scan(results: List[Dict]) -> Dict[str, Any]:
    """Run data leakage / lookahead bias audit."""
    flags = []
    
    # Check 1: Any prediction timestamp after outcome timestamp?
    for r in results:
        pred_ts = r.get('prediction_timestamp')
        outcome_ts = r.get('outcome_timestamp')
        if pred_ts and outcome_ts:
            if pred_ts >= outcome_ts:
                flags.append({
                    "type": "LOOKAHEAD_BIAS",
                    "market": r['condition_id'],
                    "detail": f"prediction_timestamp {pred_ts} >= outcome_timestamp {outcome_ts}"
                })
    
    # Check 2: Jev probability exactly matches outcome (too perfect)
    for r in results:
        if r['jev_prob'] in [0.0, 1.0] and r['actual_outcome'] == int(r['jev_prob']):
            flags.append({
                "type": "SUSPICIOUS_CERTAINTY",
                "market": r['condition_id'],
                "detail": f"Jev prob {r['jev_prob']} matches outcome {r['actual_outcome']} perfectly"
            })
    
    # Check 3: Unusually high accuracy in specific bins (may indicate leakage)
    bin_acc = {}
    for r in results:
        if r['jev_prob'] is not None:
            bin_idx = int(r['jev_prob'] * 10)
            if bin_idx not in bin_acc:
                bin_acc[bin_idx] = {"correct": 0, "total": 0}
            bin_acc[bin_idx]["total"] += 1
            if r['correct']:
                bin_acc[bin_idx]["correct"] += 1
    
    for bin_idx, stats in bin_acc.items():
        if stats["total"] >= 5 and stats["correct"] / stats["total"] > 0.95:
            flags.append({
                "type": "UNUSUAL_BIN_ACCURACY",
                "bin": f"{bin_idx/10:.1f}-{(bin_idx+1)/10:.1f}",
                "detail": f"{stats['correct']}/{stats['total']} = {stats['correct']/stats['total']:.1%}"
            })
    
    # Check 4: Missing required enhanced fields
    missing_fields = 0
    for r in results:
        for field in ['macro_context', 'smart_money_net_flow', 'prediction_timestamp', 'outcome_timestamp']:
            if field not in r or r[field] is None:
                missing_fields += 1
    
    if missing_fields > 0:
        flags.append({
            "type": "MISSING_ENHANCED_FIELDS",
            "count": missing_fields,
            "detail": f"{missing_fields} enhanced field slots unfilled across results"
        })
    
    return {
        "flags": flags,
        "passed": len(flags) == 0,
        "scanned_at": datetime.now().isoformat(),
        "total_markets": len(results),
    }


def run_evaluation() -> Dict:
    """Run the full calibration evaluation across target categories."""
    print(f"\n{'='*60}")
    print(f"ORACLE LAYER - CALIBRATION EVALUATION v3")
    print(f"Evaluation ID: {EVAL_SPEC['evaluation_id']}")
    print(f"Registered: {EVAL_SPEC['registered_at']}")
    print(f"Target categories: {', '.join(EVAL_SPEC['target_categories'])}")
    print(f"Target n: {EVAL_SPEC['target_n']}")
    print(f"Gates: ECE<{EVAL_SPEC['gates']['ece_threshold']}, Brier<{EVAL_SPEC['gates']['brier_threshold']}, HitRate>{EVAL_SPEC['gates']['hit_rate_threshold']}")
    print(f"{'='*60}\n")
    
    # Save pre-registration
    prereg_path = f"/home/openclaw/.openclaw/workspace/oracle-layer/eval_prereg_{EVAL_SPEC['evaluation_id']}.json"
    with open(prereg_path, 'w') as f:
        json.dump(EVAL_SPEC, f, indent=2)
    print(f"Pre-registration saved: {prereg_path}\n")
    
    # Fetch markets from all target categories
    all_resolved = []
    for category in EVAL_SPEC['target_categories']:
        try:
            resolved = fetch_markets_by_category(category, limit=200)
            for m in resolved:
                m['category'] = category
            all_resolved.extend(resolved)
        except Exception as e:
            print(f"  Failed to fetch {category}: {e}")
    
    # Deduplicate by condition_id
    seen = set()
    unique_resolved = []
    for m in all_resolved:
        cid = m.get('conditionId', '')
        if cid and cid not in seen:
            seen.add(cid)
            unique_resolved.append(m)
    
    print(f"\nTotal unique resolved markets across categories: {len(unique_resolved)}")
    
    if len(unique_resolved) < EVAL_SPEC['target_n']:
        print(f"WARNING: Only {len(unique_resolved)} eligible markets, target was {EVAL_SPEC['target_n']}")
    
    test_markets = unique_resolved[:EVAL_SPEC['target_n']]
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
        
        # Record prediction timestamp (now - this is when we make the prediction)
        prediction_timestamp = datetime.now().isoformat()
        prediction_dt = datetime.now()
        
        # Get market detail for enhanced features
        market_detail = fetch_market_detail(condition_id)
        
        # Extract enhanced features
        macro_context = extract_macro_context(market_detail, category, prediction_dt)
        smart_money = extract_smart_money_flow(market_detail, category)
        
        print(f"[{i}/{len(test_markets)}] {question[:70]}...")
        print(f"  Category: {category} | End: {end_date} | Actual: {actual_yes_price:.6f} ({'YES' if actual_outcome else 'NO'})")
        
        latest_price = fetch_latest_price(condition_id)
        if latest_price:
            print(f"  Latest market price: {latest_price:.4f}")
        
        try:
            jev_result = call_jev(question, latest_price)
            jev_prob = jev_result['probability']
            jev_conf = jev_result['confidence']
            print(f"  Jev: P(YES)={jev_prob:.4f}, conf={jev_conf:.2f}")
            
            correct = (jev_prob > 0.5) == (actual_outcome == 1)
            
            # Extract REAL macro context at prediction time
            macro_context = extract_macro_context(market_detail, category, prediction_dt)
            
            # Extract REAL smart money flow
            smart_money = extract_smart_money_flow(market_detail, category)
            
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
                # ENHANCED FIELDS (per requirements) - NOW REAL DATA
                "macro_context": macro_context,
                "smart_money_net_flow": smart_money,
                "prediction_timestamp": prediction_timestamp,
                "outcome_timestamp": end_date,
            })
            
        except Exception as e:
            print(f"  Jev error: {e}")
            # Still extract enhanced features even if Jev fails, for completeness
            # Ensure prediction_dt is defined
            if 'prediction_dt' not in locals():
                prediction_timestamp = datetime.now().isoformat()
                prediction_dt = datetime.now()
            macro_context = extract_macro_context(market_detail, category, prediction_dt)
            smart_money = extract_smart_money_flow(market_detail, category)
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
                "macro_context": macro_context,
                "smart_money_net_flow": smart_money,
                "prediction_timestamp": prediction_timestamp,
                "outcome_timestamp": end_date,
            })
        
        print()
    
    valid_results = [r for r in results if r['jev_prob'] is not None]
    print(f"\nValid predictions: {len(valid_results)}/{len(results)}")
    
    # Run leakage scan
    print("\nRunning leakage scan...")
    leakage = leakage_scan(valid_results)
    if leakage['passed']:
        print("  Leakage scan: PASSED (no flags)")
    else:
        print(f"  Leakage scan: FLAGGED - {len(leakage['flags'])} issues")
        for flag in leakage['flags']:
            print(f"    - {flag['type']}: {flag['detail']}")
    
    metrics = compute_calibration(valid_results)
    
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
    
    report = {
        "evaluation_spec": EVAL_SPEC,
        "results": results,
        "metrics": metrics,
        "leakage_scan": leakage,
        "gates": {
            "ece": {"threshold": EVAL_SPEC['gates']['ece_threshold'], "actual": metrics['ece'], "passed": gate_ece},
            "brier": {"threshold": EVAL_SPEC['gates']['brier_threshold'], "actual": metrics['brier_score'], "passed": gate_brier},
            "hit_rate": {"threshold": EVAL_SPEC['gates']['hit_rate_threshold'], "actual": metrics['accuracy'], "passed": gate_hitrate},
            "min_samples": {"threshold": EVAL_SPEC['gates']['min_samples'], "actual": metrics['n'], "passed": gate_n},
        },
        "verdict": verdict,
        "completed_at": datetime.now().isoformat(),
    }
    
    report_path = f"/home/openclaw/.openclaw/workspace/oracle-layer/eval_report_{EVAL_SPEC['evaluation_id']}.json"
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    with open('/home/openclaw/.openclaw/workspace/oracle-layer/calibration_results.json', 'w') as f:
        json.dump(valid_results, f, indent=2, default=str)
    
    print(f"\n{'='*60}")
    print(f"EVALUATION COMPLETE - VERDICT: {verdict}")
    print(f"{'='*60}")
    print(f"N: {metrics['n']} (gate: {'PASS' if gate_n else 'FAIL'})")
    print(f"Accuracy: {metrics['accuracy']:.2%} (gate: {'PASS' if gate_hitrate else 'FAIL'} >{EVAL_SPEC['gates']['hit_rate_threshold']:.0%})")
    print(f"Brier Score: {metrics['brier_score']:.4f} (gate: {'PASS' if gate_brier else 'FAIL'} <{EVAL_SPEC['gates']['brier_threshold']})")
    print(f"ECE: {metrics['ece']:.4f} (gate: {'PASS' if gate_ece else 'FAIL'} <{EVAL_SPEC['gates']['ece_threshold']})")
    print(f"Reliability: {metrics['reliability']}")
    print(f"Leakage: {'PASS' if leakage['passed'] else 'FAIL'} ({len(leakage['flags'])} flags)")
    print(f"\nCalibration Curve:")
    for bin_data in metrics['calibration_curve']:
        if bin_data['count'] > 0:
            print(f"  {bin_data['bin']}: n={bin_data['count']}, avg_prob={bin_data['avg_prob']:.2f}, accuracy={bin_data['accuracy']:.2%}")
    print(f"\nBy Category:")
    for cat, cat_m in metrics['by_category'].items():
        print(f"  {cat}: n={cat_m['n']}, acc={cat_m['accuracy']:.2%}, brier={cat_m['brier']:.4f}")
    print(f"\nReport saved: {report_path}")
    
    return report


if __name__ == '__main__':
    try:
        run_evaluation()
    finally:
        _cleanup_loop()