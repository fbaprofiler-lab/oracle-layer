#!/usr/bin/env python3
"""
Deep TypeSafe API Exploration
Try various endpoint patterns to find the correct Jev API structure
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


def explore_typesafe_api():
    """Systematically explore TypeSafe API endpoints."""
    print("=" * 60)
    print("TYPESAFE API DEEP EXPLORATION")
    print("=" * 60)
    
    if not TYPESAFE_API_KEY or TYPESAFE_API_KEY == "***":
        print("❌ TYPESAFE_API_KEY not set")
        return

    base = TYPESAFE_BASE_URL.rstrip('/')
    headers = {"Authorization": f"Bearer {TYPESAFE_API_KEY}"}
    
    # Test various base paths
    base_paths = [
        "https://api.typesafe.ai",
        "https://api.typesafe.ai/v1",
        "https://api.typesafe.ai/v2",
        "https://api.typesafe.ai/api",
        "https://api.typesafe.ai/api/v1",
    ]
    
    endpoints_to_try = [
        "/models",
        "/chat/completions",
        "/completions",
        "/generate",
        "/predict",
        "/judgment",
        "/jev",
        "/jev/chat",
        "/jev/completions",
        "/jev/predict",
        "/v1/models",
        "/v1/chat/completions",
        "/v1/completions",
        "/v1/generate",
        "/v1/predict",
    ]
    
    for base_path in base_paths:
        print(f"\n🔍 Testing base: {base_path}")
        for endpoint in endpoints_to_try:
            url = f"{base_path}{endpoint}"
            try:
                # Try GET first
                status, body = http_get(url, headers={"Authorization": f"Bearer {TYPESAFE_API_KEY}"}, timeout=10)
                if status != 404:
                    print(f"   GET {endpoint}: {status} - {body[:100] if body else 'empty'}")
                
                # Try POST with minimal payload
                if endpoint in ["/chat/completions", "/completions", "/generate", "/predict", "/judgment", "/jev/chat", "/jev/completions", "/jev/predict", "/v1/chat/completions", "/v1/completions", "/v1/generate", "/v1/predict"]:
                    try:
                        status, body = http_post(
                            url,
                            headers={"Authorization": f"Bearer {TYPESAFE_API_KEY}", "Content-Type": "application/json"},
                            json_data={"model": "jev-latest", "prompt": "test", "max_tokens": 10},
                            timeout=10
                        )
                        if status != 404:
                            print(f"   POST {endpoint}: {status} - {body[:100] if body else 'empty'}")
                    except Exception:
                        pass
                        
            except Exception as e:
                if "404" not in str(e) and "403" not in str(e) and "401" not in str(e):
                    print(f"   {endpoint}: Error - {e}")

    # Also try the typesafe.ai website for docs
    print("\n📚 Checking for API docs...")
    try:
        status, body = http_get("https://typesafe.ai/docs/api", timeout=10)
        print(f"   /docs/api: {status}")
        if status == 200 and "jev" in body.lower():
            print("   Found Jev references in docs!")
    except:
        pass
    
    try:
        status, body = http_get("https://docs.typesafe.ai", timeout=10)
        print(f"   docs.typesafe.ai: {status}")
    except:
        pass


def main():
    print("=" * 60)
    print("TYPESAFE API DEEP EXPLORATION")
    print("=" * 60)
    explore_typesafe_api()


if __name__ == "__main__":
    main()