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

TARGET_CATEGORIES = ["US-current-affairs", "Crypto", "Sports"]
TARGET_N = 50

ssl_context = ssl.create_default_context()

EVAL_SPEC = {
    "evaluation_id": f"eval_ablation_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
    "description": "Ablation test - Jev calibration with different prompt variants",
    "target_categories": TARGET_CATEGORIES,
    "target_n": TARGET_N,
    "gates": {"ece_threshold": 0.05, "brier_threshold": 0.20, "hit_rate_threshold": 0.55, "min_samples": 50},
    "jev_model": JEV_MODEL,
    "registered_at": datetime.now().isoformat(),
    "ablation_variants": [
        "baseline_question_only",
        "with_market_price",
        "with_macro_context",
        "full_fusion_prompt"
    ]
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

def call_jev(state):
    payload = {"state": state, "model": JEV_MODEL, "questions": {"outcome": {"type": "noul", "instructions": "Did the YES outcome win? Output calibrated probability (0-1)."}}}
    status, body = http_post("https://api.typesafe.ai/v1/systemone", payload)
    if status != 200:
        raise RuntimeError(f"Jev error {status}: {body[:200]}")
    result = json.loads(body)
    jev_prob = result.get('answers', {}).get('outcome', {}).get('noul', 0.5)
    return {"probability": max(0.0, min(1.0, float(jev_prob))), "raw": result}

# Fetch markets
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

print(f"Running ablation on {len(test_markets)} markets...")

def build_prompt_v1(question):
    return f"Market: {question}. This market has closed. Predict the probability that YES won (outcome = 1)."

def build_prompt_v2(question, latest_price):
    state = f"Market: {question}. "
    if latest_price is not None:
        state += f"Current YES probability: {latest_price:.4f}. "
    state += "This market has closed. Predict the probability that YES won (outcome = 1)."
    return state

def build_prompt_v3(question, latest_price):
    state = f"Market: {question}. "
    if latest_price is not None:
        state += f"Current YES probability: {latest_price:.4f}. "
    state += "Macro context: WTI ~$70, GPR ~120, DXY ~103, Fed Funds ~4.5%. "
    state += "This market has closed. Predict the probability that YES won (outcome = 1)."
    return state

def build_prompt_v4(question, latest_price):
    state = f"Market: {question}. "
    if latest_price is not None:
        state += f"Current YES probability: {latest_price:.4f}. "
    state += "Macro context: WTI ~$70, GPR ~120, DXY ~103, Fed Funds ~4.5%. "
    state += "Smart money flow: minimal. Wallet concentration: moderate. "
    state += "This market has closed. Predict the probability that YES won (outcome = 1)."
    return state

prompt_builders = {
    "baseline_question_only": build_prompt_v1,
    "with_market_price": build_prompt_v2,
    "with_macro_context": build_prompt_v3,
    "full_fusion_prompt": build_prompt_v4,
}

results_by_variant = {v: [] for v in prompt_builders}

for i, market in enumerate(test_markets, 1):
    cid = market.get('conditionId', '')
    question = market.get('question', '')
    category = market.get('category', 'unknown')
    
    try:
        outcome_prices = json.loads(market.get('outcomePrices', '[]'))
        actual_yes_price = float(outcome_prices[0]) if outcome_prices else 0.0
    except:
        actual_yes_price = 0.0
    actual_outcome = 1 if actual_yes_price > 0.5 else 0
    
    latest_price = fetch_latest_price(cid)
    
    print(f"[{i}/{len(test_markets)}] {question[:50]}... ({category})")
    
    for variant_name, builder in prompt_builders.items():
        if variant_name == "baseline_question_only":
            state = builder(question)
        else:
            state = builder(question, latest_price)
        
        try:
            jev_result = call_jev(state)
            jev_prob = jev_result['probability']
            correct = (jev_prob > 0.5) == (actual_outcome == 1)
            results_by_variant[variant_name].append({
                "question": question, "category": category,
                "actual_outcome": actual_outcome, "jev_prob": round(jev_prob, 4),
                "correct": correct,
            })
            print(f"  {variant_name}: {jev_prob:.4f} (correct={correct})")
        except Exception as e:
            print(f"  {variant_name}: ERROR - {e}")
            results_by_variant[variant_name].append({
                "question": question, "category": category,
                "actual_outcome": actual_outcome, "jev_prob": None, "error": str(e)
            })
    print()

# Compute metrics per variant
print("\n" + "="*60)
print("ABLATION RESULTS")
print("="*60)

for variant_name, results in results_by_variant.items():
    valid = [r for r in results if r['jev_prob'] is not None]
    if not valid:
        print(f"\n{variant_name}: NO VALID RESULTS")
        continue
    
    n = len(valid)
    correct = sum(1 for r in valid if r['correct'])
    accuracy = correct / n
    brier = sum((r['jev_prob'] - r['actual_outcome']) ** 2 for r in valid) / n
    
    bins = 10
    bin_edges = [i / bins for i in range(bins + 1)]
    ece = 0.0
    for i in range(bins):
        low, high = bin_edges[i], bin_edges[i + 1]
        bin_preds = [r for r in valid if low <= r['jev_prob'] < high]
        if not bin_preds: continue
        avg_prob = sum(r['jev_prob'] for r in bin_preds) / len(bin_preds)
        bin_acc = sum(r['actual_outcome'] for r in bin_preds) / len(bin_preds)
        bin_weight = len(bin_preds) / n
        ece += bin_weight * abs(avg_prob - bin_acc)
    
    print(f"\n{variant_name}: n={n}, acc={accuracy:.2%}, brier={brier:.4f}, ece={ece:.4f}")

# Save
with open(f"eval_report_{EVAL_SPEC['evaluation_id']}.json", 'w') as f:
    json.dump({"spec": EVAL_SPEC, "results_by_variant": results_by_variant}, f, indent=2, default=str)