#!/usr/bin/env python3
"""
Fetch resolved markets from Polymarket for calibration
"""

import os
import json
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
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
    req_headers = {'User-Agent': 'OracleLayer/0.1', 'Accept': 'application/json'}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode()

def http_post(url, headers=None, json_data=None, timeout=30):
    import json
    data = json.dumps(json_data).encode() if json_data else None
    req_headers = {'User-Agent': 'OracleLayer/0.1', 'Accept': 'application/json', 'Content-Type': 'application/json'}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=data, headers=req_headers, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode()

def main():
    # Fetch ALL markets without category filter to find resolved ones
    status, body = http_get(
        'https://gamma-api.polymarket.com/markets',
        query_params={'limit': 1000}
    )
    
    if status != 200:
        print(f"Failed to fetch markets: {status}")
        return
    
    markets = json.loads(body)
    print(f'Total markets: {len(markets)}')
    
    # Find markets with actual resolution
    resolved = []
    for m in markets:
        has_resolution = any([
            m.get('closed') == True,
            m.get('closedAt') is not None,
            m.get('resolvedAt') is not None,
            m.get('outcome') is not None,
            m.get('outcomePrices') is not None and m.get('outcomePrices') != '[]',
        ])
        if has_resolution:
            resolved.append(m)
    
    print(f'Markets with resolution indicators: {len(resolved)}')
    
    # Check for actual resolution data
    actually_resolved = []
    for m in resolved:
        outcome = m.get('outcome')
        outcome_prices = m.get('outcomePrices', '[]')
        resolved_at = m.get('resolvedAt') or m.get('closedAt')
        
        if outcome is not None or (outcome_prices and outcome_prices != '[]') or resolved_at:
            m['resolution_date'] = resolved_at
            print(f'  - {m.get("question", "N/A")[:80]}')
            print(f'    closed: {m.get("closed")}, resolvedAt: {m.get("resolvedAt")}, closedAt: {m.get("closedAt")}')
            print(f'    endDate: {m.get("endDate")}, outcome: {m.get("outcome")}')
            print(f'    outcomePrices: {m.get("outcomePrices", "N/A")[:100]}')
            print()

if __name__ == '__main__':
    import urllib.request
    import urllib.parse
    import json
    from pathlib import Path
    
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
        req_headers = {'User-Agent': 'OracleLayer/0.1', 'Accept': 'application/json'}
        if headers:
            req_headers.update(headers)
        req = urllib.request.Request(url, headers=req_headers)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()

    main()