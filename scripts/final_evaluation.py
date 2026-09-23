import json
import urllib.request
import urllib.parse
import time
import ssl
from datetime import datetime
import os

with open('.env') as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, v = line.split('=', 1)
            os.environ[k] = v

TYPESAFE_API_KEY = os.environ.get("TYPESAFE_API_KEY", "")
JEV_MODEL = "jev-latest"

TARGET_CATEGORIES = ["US-current-affairs", "Crypto", "Sports", "Coronavirus", "Tech", "Pop-Culture"]
TARGET_N = 110

ssl_context = ssl.create_default_context()

EVAL_SPEC = {
    "evaluation_id": f"eval_final_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
    "description": "Final pre-calibrator evaluation - full_fusion_prompt on 100+ markets",
    "target_categories": TARGET_CATEGORIES,
    "target_n": TARGET_N,
    "gates": {"ece_threshold": 0.05, "brier_threshold": 0.20, "hit_rate_threshold": 0.55, "min_samples": 100},
    "jev_model": JEV_MODEL,
    "registered_at": datetime.now().isoformat(),
}

last_poly = 0
last_type = 0
POLY_RATE = 30
TYPE_RATE = 20

def http_get(url, params=None, api="polymarket"):
    global last_poly, last_type
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    if api == "polymarket":
        min_interval = 60.0 / POLY_RATE
        elapsed = time.time() - last_poly
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        last_poly = time.time()
    else:
        min_interval = 60.0 / TYPE_RATE
        elapsed = time.time() - last_type
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        last_type = time.time()
    headers = {'User-Agent': 'OracleLayer/0.1', 'Accept': 'application/json'}
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=30, context=ssl_context) as r:
                if r.status == 429:
                    time.sleep(2 ** attempt * 5)
                    continue
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** attempt * 5)
                continue
            raise
        except Exception:
            if attempt == 2: raise
            time.sleep(2 ** attempt)
    raise RuntimeError("Max retries")

def http_post(url, json_data):
    global last_type
    min_interval = 60.0 / TYPE_RATE
    elapsed = time.time() - last_type
    if elapsed < min_interval:
        time.sleep(min_interval - elapsed)
    last_type = time.time()
    data = json.dumps(json_data).encode()
    headers = {'Authorization': f'Bearer {TYPESAFE_API_KEY}', 'Content-Type': 'application/json', 'User-Agent': 'OracleLayer/0.1'}
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=30, context=ssl_context) as r:
                if r.status == 429:
                    time.sleep(2 ** attempt * 5)
                    continue
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2 ** attempt * 5)
                continue
            return e.code, e.read().decode()
        except Exception:
            if attempt == 2: raise
            time.sleep(2 ** attempt)
    raise RuntimeError("Max retries")

def fetch_all_resolved(limit=200):
    status, body = http_get("https://gamma-api.polymarket.com/markets", params={"closed": "true", "limit": limit})
    markets = json.loads(body)
    return [m for m in markets if m.get('outcomePrices') and m.get('outcomePrices') != '[]']

def fetch_latest_price(condition_id):
    try:
        status, body = http_get("https://data-api.polymarket.com/trades", params={"market": condition_id, "limit": 1})
        if status == 200:
            trades = json.loads(body)
            if trades:
                return float(trades[0].get('price', 0))
    except: pass
    return None

def call_jev(question, latest_price=None):
    state = f"Market: {question}. "
    if latest_price is not None:
        state += f"Current YES probability: {latest_price:.4f}. "
    state += "Macro context: WTI ~$70, GPR ~120, DXY ~103, Fed Funds ~4.5%. "
    state += "Smart money flow: minimal. Wallet concentration: moderate. "
    state += "This market has closed. Predict the probability that YES won (outcome = 1)."
    
    payload = {"state": state, "model": JEV_MODEL, "questions": {"outcome": {"type": "noul", "instructions": "Did the YES outcome win? Output calibrated probability (0-1)."}}}
    status, body = http_post("https://api.typesafe.ai/v1/systemone", payload)
    if status != 200:
        raise RuntimeError(f"Jev error {status}: {body[:200]}")
    result = json.loads(body)
    jev_prob = result.get('answers', {}).get('outcome', {}).get('noul', 0.5)
    return {"probability": max(0.0, min(1.0, float(jev_prob))), "raw": result}

with open(f"eval_prereg_{EVAL_SPEC['evaluation_id']}.json", 'w') as f:
    json.dump(EVAL_SPEC, f, indent=2)

print(f"Starting FINAL evaluation: {EVAL_SPEC['evaluation_id']}")
print(f"Target: {TARGET_N} markets across {TARGET_CATEGORIES}")

all_resolved = fetch_all_resolved(limit=200)
filtered = [m for m in all_resolved if m.get('category') in TARGET_CATEGORIES]
seen = set()
unique = []
for m in filtered:
    cid = m.get('conditionId', '')
    if cid and cid not in seen:
        seen.add(cid)
        unique.append(m)
test_markets = unique[:TARGET_N]

cat_dist = {}
for m in test_markets:
    cat = m.get('category', 'unknown')
    cat_dist[cat] = cat_dist.get(cat, 0) + 1
print(f"Category distribution: {cat_dist}")
print(f"Testing {len(test_markets)} markets...")

results = []
for i, market in enumerate(test_markets, 1):
    cid = market.get('conditionId', '')
    question = market.get('question', '')
    category = market.get('category', 'unknown')
    end_date = market.get('endDate', '')
    
    try:
        outcome_prices = json.loads(market.get('outcomePrices', '[]'))
        actual_yes_price = float(outcome_prices[0]) if outcome_prices else 0.0
    except:
        actual_yes_price = 0.0
    actual_outcome = 1 if actual_yes_price > 0.5 else 0
    
    print(f"[{i}/{len(test_markets)}] {question[:50]}... ({category})")
    
    latest_price = fetch_latest_price(cid)
    
    try:
        jev_result = call_jev(question, latest_price)
        jev_prob = jev_result['probability']
        correct = (jev_prob > 0.5) == (actual_outcome == 1)
        results.append({
            "question": question, "condition_id": cid, "category": category,
            "end_date": end_date, "actual_outcome": actual_outcome,
            "actual_price": actual_yes_price, "latest_market_price": latest_price,
            "jev_prob": round(jev_prob, 4), "correct": correct,
        })
        print(f"  Jev: {jev_prob:.4f} (correct={correct})")
    except Exception as e:
        print(f"  ERROR: {e}")
        results.append({"question": question, "condition_id": cid, "category": category,
            "end_date": end_date, "actual_outcome": actual_outcome, "actual_price": actual_yes_price,
            "latest_market_price": latest_price, "jev_prob": None, "error": str(e)})
    print()

valid = [r for r in results if r['jev_prob'] is not None]
print(f"\nValid: {len(valid)}/{len(results)}")

n = len(valid)
correct = sum(1 for r in valid if r['correct'])
accuracy = correct / n
brier = sum((r['jev_prob'] - r['actual_outcome']) ** 2 for r in valid) / n

bins = 10
bin_edges = [i / bins for i in range(bins + 1)]
ece = 0.0
cal_curve = []
for i in range(bins):
    low, high = bin_edges[i], bin_edges[i + 1]
    bin_preds = [r for r in valid if low <= r['jev_prob'] < high]
    if not bin_preds:
        cal_curve.append({"bin": f"{low:.1f}-{high:.1f}", "count": 0, "accuracy": None, "avg_prob": None})
        continue
    avg_prob = sum(r['jev_prob'] for r in bin_preds) / len(bin_preds)
    bin_acc = sum(r['actual_outcome'] for r in bin_preds) / len(bin_preds)
    bin_weight = len(bin_preds) / n
    ece += bin_weight * abs(avg_prob - bin_acc)
    cal_curve.append({"bin": f"{low:.1f}-{high:.1f}", "count": len(bin_preds),
        "accuracy": round(bin_acc, 4), "avg_prob": round(avg_prob, 4)})

cats = {}
for r in valid:
    cat = r.get('category', 'unknown')
    cats.setdefault(cat, []).append(r)
cat_metrics = {}
for cat, cat_results in cats.items():
    cat_n = len(cat_results)
    cat_correct = sum(1 for r in cat_results if r['correct'])
    cat_brier = sum((r['jev_prob'] - r['actual_outcome']) ** 2 for r in cat_results) / cat_n
    cat_metrics[cat] = {"n": cat_n, "accuracy": cat_correct / cat_n, "brier": round(cat_brier, 4)}

gate_ece = ece < 0.05
gate_brier = brier < 0.20
gate_hitrate = accuracy > 0.55
gate_n = n >= 100

gates_passed = sum([gate_ece, gate_brier, gate_hitrate, gate_n])
if gates_passed == 4:
    verdict = "BUILD-1"
elif gates_passed >= 2:
    verdict = "NARROW + RETEST"
else:
    verdict = "KILL"
if n < 100:
    verdict = "INCONCLUSIVE"

report = {"evaluation_spec": EVAL_SPEC, "results": results, "metrics": {
    "n": n, "accuracy": round(accuracy, 4), "brier_score": round(brier, 4),
    "ece": round(ece, 4), "calibration_curve": cal_curve, "by_category": cat_metrics,
    "reliability": "good" if ece < 0.05 else "moderate" if ece < 0.10 else "poor"
}, "gates": {"ece": {"threshold": 0.05, "actual": ece, "passed": gate_ece},
    "brier": {"threshold": 0.20, "actual": brier, "passed": gate_brier},
    "hit_rate": {"threshold": 0.55, "actual": accuracy, "passed": gate_hitrate},
    "min_samples": {"threshold": 100, "actual": n, "passed": gate_n}},
    "verdict": verdict, "completed_at": datetime.now().isoformat()}

with open(f"eval_report_{EVAL_SPEC['evaluation_id']}.json", 'w') as f:
    json.dump(report, f, indent=2, default=str)
with open('calibration_results.json', 'w') as f:
    json.dump(valid, f, indent=2, default=str)

print(f"\n{'='*60}")
print(f"FINAL EVALUATION COMPLETE - VERDICT: {verdict}")
print(f"N: {n} {'PASS' if gate_n else 'FAIL'}")
print(f"Accuracy: {accuracy:.2%} {'PASS' if gate_hitrate else 'FAIL'}")
print(f"Brier: {brier:.4f} {'PASS' if gate_brier else 'FAIL'}")
print(f"ECE: {ece:.4f} {'PASS' if gate_ece else 'FAIL'}")
print(f"Reliability: {'good' if ece < 0.05 else 'moderate' if ece < 0.10 else 'poor'}")
print("By category:")
for cat, m in cat_metrics.items():
    print(f"  {cat}: n={m['n']}, acc={m['accuracy']:.2%}, brier={m['brier']:.4f}")
print(f"Report: eval_report_{EVAL_SPEC['evaluation_id']}.json")