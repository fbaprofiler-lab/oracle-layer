#!/usr/bin/env python3
"""
TypeSafe API - Extract working examples and test SystemOne endpoint
"""

import os
import json
import urllib.request
import urllib.parse
import re
from pathlib import Path

# Load environment
env_path = Path('/home/openclaw/.openclaw/workspace/oracle-layer/.env')
if env_path.exists():
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                os.environ[k] = v

TYPESAFE_API_KEY = os.getenv('TYPESAFE_API_KEY')

def http_get(url, headers=None, query_params=None, timeout=30):
    if query_params:
        url = f'{url}?{urllib.parse.urlencode(query_params)}'
    req_headers = {'User-Agent': 'OracleLayer/0.1', 'Accept': 'application/json, text/html'}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode()

def http_post(url, headers=None, json_data=None, timeout=30):
    data = json.dumps(json_data).encode() if json_data else None
    req_headers = {'User-Agent': 'OracleLayer/0.1', 'Accept': 'application/json', 'Content-Type': 'application/json'}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=req_headers, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode()

def extract_code_blocks():
    """Fetch API docs and extract code blocks with working examples."""
    print("📚 Fetching TypeSafe API docs for code examples...")
    status, body = http_get('https://docs.typesafe.ai/api', timeout=15)
    
    if status != 200:
        print(f"Failed to fetch docs: {status}")
        return
    
    # Extract all pre/code blocks
    code_blocks = re.findall(r'<pre[^>]*><code[^>]*>(.*?)</code></pre>', body, re.DOTALL)
    print(f'Found {len(code_blocks)} code blocks')
    
    for i, block in enumerate(code_blocks):
        # Clean HTML entities
        block = block.replace('<', '<').replace('>', '>').replace('&', '&').replace('"', '"')
        if any(kw in block.lower() for kw in ['systemone', 'state', 'model', 'questions', 'noul', 'jev', 'evaluation', 'questions']):
            print(f'\n=== CODE BLOCK {i} ===')
            print(block[:3000])
            print('---')

def test_endpoint_variations():
    """Test different endpoint formats for SystemOne."""
    print("\n🔧 Testing SystemOne endpoint variations...")
    
    # Based on the API docs, the evaluation endpoint is POST /v1/systemone
    # The request body has: state (required), model (optional), questions (required map)
    # For noul type: { "type": "noul", "question": "..." }
    
    test_cases = [
        # Minimal - string state, questions map
        {
            'name': 'Minimal string state',
            'payload': {
                'state': 'Current market probability is 0.45 for YES',
                'model': 'jev-latest',
                'questions': {
                    'will_increase': {'type': 'noul', 'question': 'Will YES probability increase in 24h?'}
                }
            }
        },
        # State as object
        {
            'name': 'Object state',
            'payload': {
                'state': {'market': 'fed-rate', 'current_prob': 0.45, 'macro': {'wti': 70, 'crack': 20}},
                'model': 'jev-latest',
                'questions': {
                    'will_increase': {'type': 'noul', 'question': 'Will YES probability increase in 24h?'}
                }
            }
        },
        # Array of questions
        {
            'name': 'Questions as array',
            'payload': {
                'state': 'Test state',
                'model': 'jev-latest',
                'questions': [
                    {'name': 'q1', 'type': 'noul', 'question': 'Will it increase?'}
                ]
            }
        },
    ]
    
    for tc in test_cases:
        print(f"\n--- {tc['name']} ---")
        print(f"Payload: {json.dumps(tc['payload'], indent=2)}")
        
        try:
            status, body = http_post(
                'https://api.typesafe.ai/v1/systemone',
                headers={'Authorization': f'Bearer {TYPESAFE_API_KEY}', 'Content-Type': 'application/json'},
                json_data=tc['payload'],
                timeout=30
            )
            print(f"Status: {status}")
            if status == 200:
                result = json.loads(body)
                print(f"✅ SUCCESS: {json.dumps(result, indent=2)[:800]}")
                return True
            else:
                print(f"Error: {body[:500]}")
        except Exception as e:
            print(f"Error: {e}")
    
    return False

def main():
    print("=" * 60)
    print("TYPESAFE FINAL ATTEMPT - Extract Examples & Test")
    print("=" * 60)
    
    extract_code_blocks()
    success = test_endpoint_variations()
    
    print("\n" + "=" * 60)
    if success:
        print("✅ TypeSafe API WORKING!")
    else:
        print("❌ TypeSafe API still failing - need to check exact schema")
    print("=" * 60)


if __name__ == "__main__":
    import re
    main()