#!/usr/bin/env python3
"""
TypeSafe API Documentation & Endpoint Discovery
Fetch docs and try more endpoint patterns
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

TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY")
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


def fetch_docs():
    """Fetch TypeSafe documentation."""
    print("📚 Fetching TypeSafe documentation...")
    
    doc_urls = [
        "https://docs.typesafe.ai",
        "https://docs.typesafe.ai/api-reference",
        "https://docs.typesafe.ai/api",
        "https://docs.typesafe.ai/reference",
        "https://typesafe.ai/docs",
        "https://typesafe.ai/api",
        "https://typesafe.ai/docs/api-reference",
    ]
    
    for url in doc_urls:
        try:
            print(f"   Fetching {url}...")
            status, body = http_get(url, timeout=15)
            print(f"   {url}: {status}")
            if status == 200 and len(body) > 500:
                # Look for API endpoint patterns
                endpoints = re.findall(r'(/[a-zA-Z0-9/_/-]+(?:chat|completions|generate|predict|jev|judgment)[a-zA-Z0-9/_/-]*)', body)
                if endpoints:
                    print(f"   Found potential endpoints: {list(set(endpoints))[:20]}")
                # Also look for code blocks
                code_blocks = re.findall(r'```[\w]*\n(.*?)\n```', body, re.DOTALL)
                for block in code_blocks[:5]:
                    if 'chat' in block.lower() or 'completion' in block.lower() or 'jev' in block.lower():
                        print(f"   Code block: {block[:300]}")
        except Exception as e:
            pass


def try_openai_compatible_endpoints():
    """Try various OpenAI-compatible endpoint patterns."""
    print("\n🔧 Trying OpenAI-compatible endpoint patterns...")
    
    base_urls = [
        "https://api.typesafe.ai/v1",
        "https://api.typesafe.ai",
    ]
    
    # Different endpoint patterns
    endpoints = [
        "/chat/completions",
        "/completions",
        "/v1/chat/completions",
        "/v1/completions",
        "/api/v1/chat/completions",
        "/api/v1/completions",
        "/generate",
        "/v1/generate",
        "/predict",
        "/v1/predict",
        "/inference",
        "/v1/inference",
        "/jev/completions",
        "/jev/chat",
        "/api/jev/completions",
    ]
    
    # Different payload formats
    payloads = [
        # OpenAI format
        {"model": "jev-latest", "messages": [{"role": "user", "content": "test"}], "max_tokens": 10},
        # Simple prompt format
        {"model": "jev-latest", "prompt": "test", "max_tokens": 10},
        # With system message
        {"model": "jev-latest", "messages": [{"role": "system", "content": "You are Jev."}, {"role": "user", "content": "test"}], "max_tokens": 10},
        # Minimal
        {"model": "jev-latest", "input": "test", "max_tokens": 10},
    ]
    
    for base in base_urls:
        for endpoint in endpoints:
            url = f"{base.rstrip('/')}{endpoint}"
            for i, payload in enumerate(payloads):
                try:
                    status, body = http_post(
                        url,
                        headers={"Authorization": f"Bearer {TYPESAFE_API_KEY}", "Content-Type": "application/json"},
                        json_data=payload,
                        timeout=10
                    )
                    if status != 404:
                        print(f"   POST {base}{endpoint} (payload {i+1}): {status}")
                        if status == 200:
                            print(f"   ✅ SUCCESS: {body[:200]}")
                            return True, url, payload
                        elif status in [400, 422]:
                            print(f"   📝 Validation error (endpoint exists): {body[:200]}")
                            return True, url, payload
                except Exception as e:
                    if "404" not in str(e):
                        pass
    
    return False, None, None


def check_rate_limits_and_auth():
    """Check if auth works on known endpoints."""
    print("\n🔐 Checking auth on working endpoints...")
    
    # Test auth on /models
    status, body = http_get(
        "https://api.typesafe.ai/v1/models",
        headers={"Authorization": f"Bearer {TYPESAFE_API_KEY}"}
    )
    print(f"   /models with auth: {status}")
    
    # Test without auth
    status, body = http_get("https://api.typesafe.ai/v1/models")
    print(f"   /models without auth: {status}")


def main():
    print("=" * 60)
    print("TYPESAFE API DOCS & ENDPOINT DISCOVERY")
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
    TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY")
    TYPESAFE_BASE_URL = os.getenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1")
    
    fetch_docs()
    try_openai_compatible_endpoints()
    check_rate_limits_and_auth()
    
    print("\n" + "=" * 60)
    print("EXPLORATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    main()