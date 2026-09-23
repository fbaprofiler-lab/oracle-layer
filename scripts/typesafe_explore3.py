#!/usr/bin/env python3
"""
TypeSafe API - Fetch actual API reference content and try more endpoints
"""

import os
import json
import urllib.request
import urllib.parse
import re
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

TYPESAFE_API_KEY = ***"TYPESAFE_API_KEY")
TYPESAFE_BASE_URL = os.getenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1")


def http_get(url, headers=None, query_params=None, timeout=30):
    """Simple HTTP GET using urllib."""
    if query_params:
        query_string = urllib.parse.urlencode(query_params)
        url = f"{url}?{query_string}"
    
    req_headers = {
        "User-Agent": "OracleLayer/0.1",
        "Accept": "application/json, text/html",
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


def fetch_api_reference():
    """Fetch the actual API reference page content."""
    print("📚 Fetching API reference page...")
    
    urls = [
        "https://docs.typesafe.ai/api-reference",
        "https://docs.typesafe.ai/reference",
        "https://docs.typesafe.ai/api",
    ]
    
    for url in urls:
        try:
            print(f"   Fetching {url}...")
            status, body = http_get(url, timeout=15)
            print(f"   {url}: {status}")
            if status == 200:
                # Save for inspection
                fname = url.replace("https://", "").replace("/", "_") + ".html"
                with open(f"/tmp/{fname}", "w") as f:
                    f.write(body)
                print(f"   Saved to /tmp/{fname} ({len(body)} chars)")
                
                # Look for API patterns
                patterns = [
                    r'chat/completions',
                    r'completions',
                    r'generate',
                    r'predict',
                    r'jev',
                    r'judgment',
                    r'baseURL',
                    r'baseUrl',
                    r'endpoint',
                    r'POST',
                    r'curl',
                ]
                for pattern in patterns:
                    matches = [(m.start(), body[max(0,m.start()-50):m.end()+50]) for m in re.finditer(pattern, body, re.IGNORECASE)]
                    if matches:
                        print(f"   Found '{pattern}': {matches[:3]}")
        except Exception as e:
            print(f"   Error fetching {url}: {e}")


def try_all_endpoint_patterns():
    """Try all possible endpoint patterns systematically."""
    print("\n🔧 Trying ALL endpoint patterns...")
    
    base_urls = [
        "https://api.typesafe.ai",
        "https://api.typesafe.ai/v1",
        "https://api.typesafe.ai/api",
        "https://api.typesafe.ai/api/v1",
    ]
    
    endpoints = [
        "/chat/completions",
        "/completions",
        "/generate",
        "/predict",
        "/inference",
        "/jev",
        "/jev/chat",
        "/jev/completions",
        "/jev/generate",
        "/api/chat/completions",
        "/api/completions",
        "/api/generate",
        "/api/predict",
        "/v1/chat/completions",
        "/v1/completions",
        "/v1/generate",
        "/v1/predict",
        "/api/v1/chat/completions",
        "/api/v1/completions",
        "/api/v1/generate",
        "/api/v1/predict",
    ]
    
    # Different payload formats that APIs might expect
    payloads = [
        # Standard OpenAI
        {"model": "jev-latest", "messages": [{"role": "user", "content": "test"}], "max_tokens": 10},
        # Anthropic style
        {"model": "jev-latest", "prompt": "\n\nHuman: test\n\nAssistant:", "max_tokens_to_sample": 10},
        # Simple prompt
        {"model": "jev-latest", "prompt": "test", "max_tokens": 10},
        # Input field
        {"model": "jev-latest", "input": "test", "max_tokens": 10},
        # Minimal
        {"model": "jev-latest", "text": "test", "max_tokens": 10},
    ]
    
    headers = {
        "Authorization": f"Bearer {TYPESAFE_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "OracleLayer/0.1",
        "Accept": "application/json",
    }
    
    for base in ["https://api.typesafe.ai/v1", "https://api.typesafe.ai", "https://api.typesafe.ai/api/v1"]:
        for endpoint in [
            "/chat/completions",
            "/completions",
            "/generate",
            "/predict",
            "/inference",
            "/jev/completions",
            "/jev/chat",
            "/api/chat/completions",
            "/api/completions",
            "/v1/chat/completions",
            "/v1/completions",
        ]:
            url = f"{base.rstrip('/')}{endpoint}"
            for i, payload in enumerate([
                {"model": "jev-latest", "messages": [{"role": "user", "content": "test"}], "max_tokens": 10},
                {"model": "jev-latest", "prompt": "test", "max_tokens": 10},
                {"model": "jev-latest", "prompt": "test", "max_tokens_to_sample": 10},
            ]):
                try:
                    status, body = http_post(
                        url,
                        headers={"Authorization": f"Bearer {TYPESAFE_API_KEY}", "Content-Type": "application/json"},
                        json_data=payload,
                        timeout=10
                    )
                    if status != 404:
                        print(f"   POST {base}{endpoint} (payload): {status}")
                        if status == 200:
                            print(f"   ✅ SUCCESS: {body[:300]}")
                            return True
                        elif status in [400, 422, 401, 403]:
                            print(f"   📝 Endpoint exists (status {status}): {body[:200]}")
                            return True
                except Exception as e:
                    if "404" not in str(e):
                        pass
    return False


def try_websocket_or_sse():
    """Check if Jev uses WebSocket or SSE."""
    print("\n🔌 Checking for WebSocket/SSE endpoints...")
    ws_endpoints = [
        "wss://api.typesafe.ai/v1/ws",
        "wss://api.typesafe.ai/ws",
        "wss://api.typesafe.ai/v1/jev/ws",
        "https://api.typesafe.ai/v1/stream",
        "https://api.typesafe.ai/v1/jev/stream",
    ]
    for url in ws_endpoints:
        try:
            # Just try HTTP GET first
            status, body = http_get(url.replace("wss://", "https://"), timeout=5)
            print(f"   {url}: {status}")
        except:
            pass


def check_typesafe_github():
    """Check if there's a TypeSafe SDK or examples on GitHub."""
    print("\n🔍 Checking GitHub for TypeSafe SDK/examples...")
    try:
        status, body = http_get("https://api.github.com/search/repositories?q=typesafe+jev", timeout=10)
        print(f"   GitHub search: {status}")
        if status == 200:
            data = json.loads(body)
            for repo in data.get("items", [])[:5]:
                print(f"   {repo['full_name']}: {repo['description'][:100]}")
    except:
        pass


def main():
    print("=" * 60)
    print("TYPESAFE API COMPREHENSIVE EXPLORATION")
    print("=" * 60)
    
    # Load environment
    from pathlib import Path
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ[k] = v
    
    global TYPESAFE_API_KEY, TYPESAFE_BASE_URL
    TYPESAFE_API_KEY = ***"TYPESAFE_API_KEY")
    TYPESAFE_BASE_URL = os.getenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1")
    
    fetch_api_reference()
    try_all_endpoint_patterns()
    try_websocket_or_sse()
    check_typesafe_github()
    
    print("\n" + "=" * 60)
    print("EXPLORATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()