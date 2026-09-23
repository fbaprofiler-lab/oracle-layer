#!/usr/bin/env python3
"""
Fetch closed/resolved markets from Polymarket for calibration
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

TYPESAFE_API_KEY = os.getenv("TYPESAFE_API_KEY")

def http_get(url, headers=None, query_params=None, timeout=30):
    if query_params:
        url = f'{url}?{urllib.parse.urlencode(query_params)}'
    req_headers = {'User-Agent': 'OracleLayer/0.1', 'Accept': 'application/json'}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read().decode()

def main():
    # Get ALL markets from all categories with a large limit
    all_markets = []

    for cat in ['fed-rate-decisions', 'cpi-inflation', 'rate-decisions']:
        status, body = http_get(
            'https://gamma-api.polymarket.com/markets',
            query_params={'category': cat, 'limit': 500}
        )
        if status == 200:
            markets = json.loads(body)
            for m in markets:
                # Check various resolution indicators
                is_closed = m.get('closed') == True
                has_closed_at = m.get('closedAt') is not None
                has_resolved_at = m.get('resolvedAt') is not None
                has_outcome = m.get('outcome') is not None
                has_outcome_prices = m.get('outcomePrices') is not None
                end_date_passed = False
                if m.get('endDate'):
                    try:
                        end_date = datetime.fromisoformat(m['endDate'].replace('Z', '+00:00'))
                        if end_date < datetime.now():
                            end_date_passed = True
                    except:
                        pass
                
                if is_closed or has_closed_at or has_resolved_at or has_outcome or end_date_passed:
                    m['category'] = cat
                    all_markets.append(m)

    print(f'Total markets with resolution indicators: {len(all_markets)}')

    # Check their resolution data
    for m in all_markets[:20]:
        print(f'  - {m.get("question", "N/A")[:80]}')
        print(f'    conditionId: {m.get("conditionId", "N/A")}')
        print(f'    closed: {m.get("closed", "N/A")}')
        print(f'    closedAt: {m.get("closedAt", "N/A")}')
        print(f'    resolvedAt: {m.get("resolvedAt", "N/A")}')
        print(f'    endDate: {m.get("endDate", "N/A")}')
        print(f'    outcome: {m.get("outcome", "N/A")}')
        print(f'    outcomePrices: {m.get("outcomePrices", "N/A")}')
        print()

    # Save to file
    with open('/home/openclaw/.openclaw/workspace/oracle-layer/closed_markets.json', 'w') as f:
        json.dump(all_markets, f, indent=2, default=str)
    print(f'Saved {len(all_markets)} markets with resolution indicators to closed_markets.json')

if __name__ == '__main__':
    import urllib.request, urllib.parse, json
    from pathlib import Path
    from datetime import datetime, timedelta

    env_path = Path('/home/openclaw/.openclaw/workspace/oracle-layer/.env')
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ[k] = v

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