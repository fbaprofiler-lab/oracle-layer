# Lessons Learned: Cohort Collection Issues

**Date:** 2026-09-25  
**Status:** Documented  
**Commit:** 2611871

---

## Problem Summary

All 93 markets across 5 cohorts were the **exact same 30 political markets** — long-term 2028 Democratic nomination + Xi Jinping markets. The category filter (`category: fed-rate-decisions`, `category: cpi-inflation`, `category: crypto-prices`) had no effect.

---

## Root Cause Analysis

### 1. Gamma API Category Filtering Doesn't Work

The Polymarket Gamma API `/markets` endpoint accepts a `category` parameter but **ignores it**. Querying with `category=fed-rate-decisions` returns the same markets as `category=crypto-prices`.

**Evidence:**
```
# All three queries return identical markets
GET /markets?category=fed-rate-decisions → 50 political markets
GET /markets?category=cpi-inflation → 50 political markets  
GET /markets?category=crypto-prices → 50 political markets
```

### 2. API Default Ordering Puts Long-Term Markets First

The default `order` parameter returns long-term political markets first. Markets with near-term end dates (sports, weather, crypto) exist but are deeper in the result set.

**Evidence:**
- First page (default order): Xi Jinping (2027-01-01), 2028 Dem nominees (2028-11-08)
- Later pages: Sports, weather, crypto markets with end dates 2026-09-25/26/27

### 3. No end_date Capture in Snapshots or Manifests

The `forward_collector.py` and `cohorts.py` didn't extract or store `endDate`/`endDateIso` from market data. This meant there was no way to filter markets by resolution date.

---

## Fixes Applied

### forward_snapshot.py
- Added `OPTIONAL_SNAPSHOT_FIELDS` (`end_date`, `end_date_iso`)
- Added `end_date` and `end_date_iso` parameters to `create_snapshot()`
- These fields are optional and don't fail validation if missing

### forward_collector.py
- Added `MAX_RESOLUTION_DAYS = 30` constant
- Added `_extract_end_date()` — extracts `endDate`/`endDateIso` from market data
- Added `_within_resolution_window()` — checks if market resolves within N days
- Added `filter_markets_by_resolution()` — filters markets by resolution window
- Updated `collect_market_batch()` — filters before collection, reports skipped markets
- Updated `collect_one()` — passes `end_date`/`end_date_iso` to snapshot creation

### cohorts.py
- Added `end_date` field to manifest entries extracted from market data
- Format: date-only string (YYYY-MM-DD)

---

## Remaining Issues

1. **API pagination returns duplicates** — Fetching 500 markets returns only 100 unique markets because pages are duplicated
2. **Category filter broken** — The API `category` parameter is non-functional; must use other methods to find markets by topic
3. **Near-term markets exist but not easily discoverable** — Sports/weather/crypto markets with end dates within days exist but require proper ordering/filtering

---

## Recommendations

| Priority | Action | Effort |
|----------|--------|--------|
| **1** | Use `order=endDate&ascending=true` parameter to get near-term markets first | Low |
| **2** | Fetch 100 markets max (not 500) to avoid duplicate pages | Low |
| **3** | Filter locally by `endDateIso` after fetching | Already done |
| **4** | Consider alternative API endpoint or query method for category filtering | Medium |
| **5** | Add retry/deduplication logic to the collector | Medium |

---

## Key Takeaways

1. **Always inspect API response data directly** — Don't assume filtering parameters work as documented
2. **Capture metadata (end_date) from market objects** — Essential for resolution-based filtering
3. **Test with real API data early** — The cohort collection issue was caught before it caused data corruption
4. **Default ordering matters** — API defaults may not return the most useful data first

---

## Future Work

- Implement market deduplication in the collector
- Add `order=endDate&ascending=true` to the API query
- Build a near-term market discovery mechanism
- Create a verification step that checks cohort diversity before writing manifests
