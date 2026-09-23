#!/usr/bin/env python3
"""
Jev/TypeSafe Access Check & Calibration Test Harness
Fixed version with proper headers for Polymarket API and TypeSafe API
"""

import os
import json
import urllib.request
import urllib.parse
from pathlib import Path

# Load environment manually
def load_env():
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k] = v

load_env()

TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY")
TYPESAFE_BASE_URL = os.getenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1")


def http_get(url, headers=None, query_params=None, timeout=30):
    """Simple HTTP GET using urllib."""
    if query_params:
        query_string = urllib.parse.urlencode(query_params)
        url = f"{url}?{query_string}"
    
    req_headers = {
        "User-Agent": "OracleLayer/0.1",
        "Accept": "application/json",
    }
    if headers:
        req_headers.update(headers)
    
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.status, response.read().decode()


def http_post(url, headers=None, json_data=None, timeout=30):
    """Simple HTTP POST using urllib."""
    data = json.dumps(json_data).encode() if json_data else None
    req_headers = {
        "User-Agent": "OracleLayer/0.1",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }
    if headers:
        req_headers.update(headers)
    
    req = urllib.request.Request(url, data=data, headers=req_headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.status, response.read().decode()


def check_typesafe_access():
    """Check if TypeSafe/Jev API is accessible."""
    if not TYPESAFE_API_KEY or TYPESAFE_API_KEY == "***":
        print("❌ TYPESAFE_API_KEY not set in environment")
        return False, None

    print(f"🔑 Testing TypeSafe access with key: {TYPESAFE_API_KEY[:10]}...")
    
    try:
        # Test 1: List models
        print("   Testing /models endpoint...")
        status, body = http_get(
            f"{TYPESAFE_BASE_URL}/models",
            headers={"Authorization": f"Bearer {TYPESAFE_API_KEY}"}
        )
        print(f"   Models endpoint: {status}")
        models_list = []
        if status == 200:
            models = json.loads(body)
            models_list = [m["name"] for m in models.get("models", [])]
            print(f"   Available models: {models_list}")
        
        # Test 2: Try chat completions with different model names
        for model_name in ["jev-latest", "jev-preview", "jev"]:
            print(f"   Testing /chat/completions with model: {model_name}...")
            try:
                status, body = http_post(
                    f"{TYPESAFE_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {TYPESAFE_API_KEY}",
                        "Content-Type": "application/json"
                    },
                    json_data={
                        "model": model_name,
                        "messages": [
                            {"role": "system", "content": "You are Jev, a calibrated probabilistic judgment engine. Output only JSON."},
                            {"role": "user", "content": 'Predict if "YES" probability will increase. Output JSON: {"probability_up": 0.5, "confidence": 0.5, "reasoning": "test"}'}
                        ],
                        "temperature": 0.1,
                        "max_tokens": 200,
                        "response_format": {"type": "json_object"}
                    }
                )
                print(f"   Chat completions ({model_name}): {status}")
                if status == 200:
                    result = json.loads(body)
                    print(f"   Jev response: {json.dumps(result, indent=2)[:500]}")
                    return True, model_name
                else:
                    print(f"   Error: {body[:200]}")
            except Exception as e:
                print(f"   Error with {model_name}: {e}")
        
        return False, None
            
    except Exception as e:
        print(f"   Connection failed: {e}")
        return False, None


def check_polymarket_data():
    """Verify we can fetch historical Polymarket data for calibration."""
    print("\n📊 Checking Polymarket historical data access...")
    
    try:
        # Get active markets to understand structure
        print("   Testing Gamma API /markets...")
        status, body = http_get(
            "https://gamma-api.polymarket.com/markets",
            query_params={"active": "true", "closed": "false", "limit": 10},
            headers={"User-Agent": "OracleLayer/0.1", "Accept": "application/json"}
        )
        print(f"   Gamma markets: {status}")
        if status == 200:
            markets = json.loads(body)
            print(f"   Sample market: {markets[0].get('question', 'N/A') if markets else 'None'}")
            
        # Check data API
        print("   Testing Data API /trades...")
        status, body = http_get(
            "https://data-api.polymarket.com/trades",
            query_params={"limit": 1},
            headers={"User-Agent": "OracleLayer/0.1", "Accept": "application/json"}
        )
        print(f"   Data API trades: {status}")
        
        return True
    except Exception as e:
        print(f"   Polymarket access failed: {e}")
        return False


def main():
    print("=" * 60)
    print("JEV SPIKE & CALIBRATION TEST (stdlib only)")
    print("=" * 60)
    
    # Check TypeSafe access
    typesafe_ok, working_model = check_typesafe_access()
    
    # Check Polymarket access
    polymarket_ok = check_polymarket_data()
    
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"TypeSafe/Jev Access: {'✅ PASS' if typesafe_ok else '❌ FAIL'}")
    if working_model:
        print(f"Working model: {working_model}")
    print(f"Polymarket Data Access: {'✅ PASS' if polymarket_ok else '❌ FAIL'}")
    
    if typesafe_ok and polymarket_ok:
        print("\n✅ READY FOR CALIBRATION TEST")
        print("   Next: Run calibration harness on 180 days of Fed/CPI markets")
    elif polymarket_ok:
        print("\n⚠️  POLYMARKET OK, TYPESAFE NEEDS ACCESS")
        print("   Next: Request TypeSafe early access, then run calibration")
        print("   Fallback: Build rules-engine + lightweight ML calibration")
    else:
        print("\n❌ BOTH NEED SETUP")
    
    return typesafe_ok, polymarket_ok


if __name__ == "__main__":
    main()