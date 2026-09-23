"""
Oracle Layer — Polymarket Data Source (Market Microstructure & Wallet Intelligence)
"""

import os
import asyncio
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

    async def get_active_markets(self, category: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get active markets, optionally filtered by category."""
        params = {"limit": limit, "active": "true", "closed": "false"}
        if category:
            params["category"] = category
        response = await self.client.get(f"{self.GAMMA_API}/markets", params=params)
        response.raise_for_status()
        return response.json()

    async def get_market_details(self, condition_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed market info by condition ID."""
        response = await self.client.get(f"{self.GAMMA_API}/markets", params={"condition_id": condition_id})
        response.raise_for_status()
        markets = response.json()
        return markets[0] if markets else None

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