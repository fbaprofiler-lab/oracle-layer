"""
Oracle Layer — Polymarket Data Source (Market Microstructure & Wallet Intelligence)
"""

import os
import asyncio
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import httpx
import pandas as pd

from .base import DataSource, DataPoint, registry
from ..core.config import settings


class PolymarketSource(DataSource):
    """Polymarket Data API + Gamma API connector for market microstructure and wallet intelligence."""

    DATA_API = "https://data-api.polymarket.com"
    GAMMA_API = "https://gamma-api.polymarket.com"

    # Gamma's /markets endpoint has no `category` field. Passing one is
    # silently ignored and the response is an arbitrary page of whatever
    # sorts first, which is how 93 snapshots of 2028 nomination markets
    # ended up inside the fed/cpi/crypto cohorts. Categories are therefore
    # expressed as Gamma tag ids.
    #
    # Verified against the live /tags endpoint:
    #   21 crypto, 131 interest-rates, 933 federal-government,
    #   101247 macro-graph, 101800 economic-policy, 102000 macro-indicators
    CATEGORY_TAGS: Dict[str, List[int]] = {
        "crypto": [21],
        "crypto-prices": [21],
        "interest-rates": [131],
        "fed-rate-decisions": [131, 101800],
        "cpi-inflation": [102000, 101247],
        "federal-government": [933],
        "politics": [933],
    }

    # Tag ids are coarse and international: tag 131 returns Bank of India and
    # Bank of Russia decisions, and 102000 returns Japan CPI. The charter wedge
    # is US macro, so a tag hit is only a *candidate* -- the question text must
    # also match. Verified on 2026-09-25: tags alone returned 0 US-Fed markets
    # in a 120-day window, while the keyword pass found 22.
    CATEGORY_PATTERNS: Dict[str, str] = {
        "fed-rate-decisions": (
            r"\bFed\b|Federal Reserve|FOMC|Fed rate|Fed cut|Fed rate cut"
        ),
        # 'CPI' alone matches Japan/UK/Eurozone prints. The wedge is the US
        # series, so require a US qualifier on CPI and allow unqualified
        # 'inflation' only when it also names US/Treasury.
        "cpi-inflation": (
            r"(?:\bUS\b|\bU\.S\.|American|United States)[^?]{0,40}(?:\bCPI\b|inflation)"
            r"|(?:\bCPI\b|inflation)[^?]{0,40}(?:\bUS\b|\bU\.S\.|American|United States)"
        ),
        "crypto-prices": (
            r"Bitcoin|Ethereum|\bBTC\b|\bETH\b|crypto"
        ),
    }

    # Categories whose tag ids do not reliably carry the US wedge. For these
    # we search the whole active window and rely on the keyword pattern, since
    # tag 21 (crypto) returns token-launch and presale markets rather than
    # price levels, and 102000/101247 return Japan CPI.
    CATEGORY_SCAN_ALL: set = {"crypto-prices", "cpi-inflation"}

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__("polymarket", config)
        self.api_key = config.get("api_key") or settings.polymarket_api_key or os.getenv("POLYMARKET_API_KEY")
        self.client = httpx.AsyncClient(timeout=30.0, headers={"User-Agent": "OracleLayer/0.1"})

    @property
    def available_series(self) -> List[str]:
        return ["markets", "wallets", "trades", "orderbook", "events"]

    async def health_check(self) -> bool:
        try:
            response = await self.client.get(f"{self.GAMMA_API}/events", params={"limit": 1})
            return response.status_code == 200
        except Exception:
            return False

    # ─── Market Data ───

    async def get_active_markets(
        self,
        category: Optional[str] = None,
        limit: int = 100,
        *,
        end_date_min: Optional[str] = None,
        end_date_max: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Active, open markets, optionally filtered by wedge category.

        An unknown category raises instead of silently widening the query.
        The previous behaviour -- ignore the filter and return anything -- is
        precisely the failure this replaces, and it produced a cohort full
        of markets that could not resolve for years.

        end_date_min/max are applied server-side so a resolution window can
        be enforced without paging the entire market list.
        """
        base: Dict[str, Any] = {"limit": limit, "active": "true", "closed": "false"}
        if end_date_min:
            base["end_date_min"] = end_date_min
        if end_date_max:
            base["end_date_max"] = end_date_max
        # Nearest-resolution-first. Sorting ascending surfaces markets that
        # expired months ago but are still flagged active, which is how a
        # Dec-2025 crypto market reached a cohort snapshot in Sep-2026.
        base["order"] = "endDate"
        base["ascending"] = "false"

        if not category:
            response = await self.client.get(f"{self.GAMMA_API}/markets", params=base)
            response.raise_for_status()
            return response.json()

        try:
            tag_ids = self.CATEGORY_TAGS[category.lower()]
        except KeyError:
            raise ValueError(
                f"unknown category {category!r}; expected one of "
                f"{sorted(self.CATEGORY_TAGS)}"
            ) from None

        # One request per tag: Gamma's tag_id is single-valued, and a comma
        # list silently degrades to an unfiltered page.
        markets: List[Dict[str, Any]] = []
        seen = set()

        if category.lower() in self.CATEGORY_SCAN_ALL:
            # Tags don't carry the US wedge for this category, and a single
            # page ordered by endDate is dominated by whatever resolves
            # soonest (politics/sports). Page deep enough to reach the macro
            # markets, deduping as we go.
            #
            # Depth matters: at 600 markets the US crypto cohort came back
            # empty, at 2000 it returns 69. Polymarket lists well over 2,000
            # active markets, and endDate ordering puts the macro series at
            # the far end of the list.
            candidates = []
            for offset in range(0, 2000, 100):
                response = await self.client.get(
                    f"{self.GAMMA_API}/markets",
                    params={**base, "offset": offset},
                )
                response.raise_for_status()
                page = response.json()
                if not page:
                    break
                candidates.extend(page)
            # Keep the nearest N by end date so the cohort favours markets
            # that will actually resolve and produce outcomes soonest.
            candidates.sort(key=lambda m: (m.get("endDate") or ""))
        else:
            candidates = []
            for tag_id in tag_ids:
                response = await self.client.get(
                    f"{self.GAMMA_API}/markets", params={**base, "tag_id": tag_id}
                )
                response.raise_for_status()
                candidates.extend(response.json())

        for market in candidates:
            key = market.get("conditionId") or market.get("id")
            if key is not None and key in seen:
                continue
            seen.add(key)
            markets.append(market)

        pattern = self.CATEGORY_PATTERNS.get(category.lower())
        if not pattern:
            return markets
        matched = [m for m in markets if re.search(pattern, m.get("question") or "", re.I)]
        # Falling back to the tag results would silently re-admit the
        # wrong-domain markets this filter exists to exclude, so return
        # nothing and let the caller see an empty cohort as a real signal.
        return matched

    async def get_market_details(self, condition_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed market info by condition ID.

        Gamma names this parameter `condition_ids` (plural). Passing the
        singular `condition_id` is silently ignored and returns an arbitrary
        page of 20 unrelated markets, which is how every forward snapshot
        collected on 2026-09-25 was populated with the same market
        ("Xi Jinping out before 2027?") while carrying 51 distinct ids.
        """
        response = await self.client.get(
            f"{self.GAMMA_API}/markets", params={"condition_ids": condition_id}
        )
        response.raise_for_status()
        markets = response.json()
        if not markets:
            return None
        for market in markets:
            if market.get("conditionId") == condition_id:
                return market
        # Deliberately no `markets[0]` fallback. Returning a market that does
        # not match the requested id attaches real-looking features to the
        # wrong market, which is far worse than returning nothing.
        return None

    async def get_market_trades(self, condition_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent trades for a market."""
        response = await self.client.get(f"{self.DATA_API}/trades", params={"market": condition_id, "limit": limit})
        response.raise_for_status()
        return response.json()

    async def get_orderbook(self, condition_id: str) -> Optional[Dict[str, Any]]:
        """Get current orderbook for a market (if available)."""
        # Polymarket may not expose public orderbook via Data API
        # This is a placeholder for future enhancement
        return None

    # ─── Wallet Intelligence ───

    async def get_wallet_trades(self, wallet: str, limit: int = 150) -> List[Dict[str, Any]]:
        """Get recent trades for a wallet."""
        response = await self.client.get(f"{self.DATA_API}/trades", params={"user": wallet, "limit": limit})
        response.raise_for_status()
        return response.json()

    async def analyze_wallet(self, wallet: str, limit: int = 150) -> Dict[str, Any]:
        """Analyze a wallet using the same logic as wallets-discover.py."""
        trades = await self.get_wallet_trades(wallet, limit)
        if not trades:
            return {"wallet": wallet, "trades": 0, "error": "no trades"}

        # Basic stats
        timestamps = [t.get("timestamp", 0) for t in trades]
        notionals = [float(t.get("size", 0)) for t in trades]
        sides = [t.get("side", "") for t in trades]

        # Group by market
        by_market = {}
        for t in trades:
            cid = t.get("conditionId")
            if cid:
                by_market.setdefault(cid, []).append(t)

        # MM heuristics
        span_days = max(1, (max(timestamps) - min(timestamps)) / 86400)
        trades_per_day = len(trades) / span_days

        twosided = sum(1 for ms in by_market.values() if {x.get("side") for x in ms} == {"BUY", "SELL"})
        twosided_share = twosided / max(1, len(by_market))

        dwells = [(max(x.get("timestamp", 0) for x in ms) - min(x.get("timestamp", 0) for x in ms)) for ms in by_market.values()]
        median_dwell = int(pd.Series(dwells).median()) if dwells else 0

        mm_flags = []
        if trades_per_day > 50:
            mm_flags.append(f"freq {trades_per_day:.1f}/day")
        if twosided_share > 0.5:
            mm_flags.append(f"two-sided {twosided_share:.0%}")
        if median_dwell < 300:
            mm_flags.append(f"dwell {median_dwell}s")

        # Independence clusters
        clusters = {(cid, t.get("side"), int(t.get("timestamp", 0) // 86400)) for cid, ms in by_market.items() for t in ms}

        return {
            "wallet": wallet,
            "trades": len(trades),
            "markets": len(by_market),
            "clusters": len(clusters),
            "trades_per_day": round(trades_per_day, 1),
            "twosided_share": round(twosided_share, 2),
            "median_dwell_s": median_dwell,
            "mm_flags": mm_flags,
            "is_likely_mm": len(mm_flags) >= 2,
            "last_active": datetime.fromtimestamp(max(timestamps)).isoformat() if timestamps else None,
        }

    async def discover_wallets(self, category: str = "fed-rate-decisions", max_candidates: int = 30) -> List[Dict[str, Any]]:
        """Discover wallet candidates from leaderboard for a category."""
        # This would use the leaderboard API to find top wallets
        # Then analyze each one
        # Placeholder - implementation depends on Polymarket leaderboard structure
        return []

    async def fetch_series(self, series_id: str, **kwargs) -> List[DataPoint]:
        """Not used for Polymarket - use specific methods instead."""
        return []

    async def fetch_multiple(self, series_ids: List[str], **kwargs) -> Dict[str, List[DataPoint]]:
        return {}

    async def close(self):
        await self.client.aclose()


# Register the source
polymarket_source = PolymarketSource({"api_key": settings.polymarket_api_key})
registry.register(polymarket_source)