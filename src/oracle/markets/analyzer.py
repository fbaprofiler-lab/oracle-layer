"""
Oracle Layer — Market Microstructure Analyzer
Analyzes Polymarket markets for liquidity, smart-money flow, mispricing signals
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from collections import defaultdict
import pandas as pd
import numpy as np

from ..sources.polymarket import PolymarketSource
from ..sources.base import DataPoint


@dataclass
class MarketMetrics:
    """Computed metrics for a single market."""
    condition_id: str
    question: str
    category: str
    outcomes: List[Dict[str, Any]]

    # Liquidity
    volume_24h: float = 0.0
    open_interest: float = 0.0
    bid_ask_spread_bps: Optional[float] = None
    depth_usd: float = 0.0

    # Price action
    current_prices: Dict[str, float] = field(default_factory=dict)
    price_change_1h: Dict[str, float] = field(default_factory=dict)
    price_change_24h: Dict[str, float] = field(default_factory=dict)

    # Smart money
    smart_money_net_flow: Dict[str, float] = field(default_factory=dict)
    smart_money_wallets: List[str] = field(default_factory=list)
    wallet_concentration: float = 0.0  # Herfindahl index

    # Signals
    mispricing_score: float = 0.0  # 0-1, higher = more likely mispriced
    momentum_signal: str = "neutral"  # bullish, bearish, neutral
    regime: str = "normal"  # normal, volatile, illiquid, manipulated


class MarketAnalyzer:
    """Analyzes Polymarket markets for actionable signals."""

    def __init__(self, polymarket: PolymarketSource):
        self.polymarket = polymarket
        self.smart_wallet_cache: Dict[str, Dict] = {}
        self.cache_ttl = timedelta(hours=1)

    async def analyze_market(self, condition_id: str) -> MarketMetrics:
        """Full analysis of a single market."""
        # Get market details
        details = await self.polymarket.get_market_details(condition_id)
        if not details:
            raise ValueError(f"Market not found: {condition_id}")

        # Get recent trades
        trades = await self.polymarket.get_market_trades(condition_id, limit=500)

        # Compute metrics
        metrics = MarketMetrics(
            condition_id=condition_id,
            question=details.get("question", ""),
            category=details.get("category", "unknown"),
            outcomes=details.get("outcomes", []),
        )

        # Analyze trades
        await self._analyze_trades(metrics, trades)
        await self._analyze_smart_money(metrics, trades)
        await self._detect_mispricing(metrics)
        await self._detect_momentum(metrics)

        return metrics

    async def _analyze_trades(self, metrics: MarketMetrics, trades: List[Dict]):
        """Basic trade analysis."""
        if not trades:
            return

        # Volume
        metrics.volume_24h = sum(float(t.get("size", 0)) for t in trades)

        # Price changes per outcome
        outcome_prices = defaultdict(list)
        for t in trades:
            outcome = t.get("outcome", "")
            price = float(t.get("price", 0))
            if outcome and price:
                outcome_prices[outcome].append(price)

        for outcome, prices in outcome_prices.items():
            if prices:
                metrics.current_prices[outcome] = prices[0]  # Most recent
                if len(prices) >= 2:
                    metrics.price_change_1h[outcome] = (prices[0] - prices[-1]) / prices[-1]

    async def _analyze_smart_money(self, metrics: MarketMetrics, trades: List[Dict]):
        """Identify and track smart money wallets."""
        # Group trades by wallet
        wallet_trades = defaultdict(list)
        for t in trades:
            wallet = t.get("user", "")
            if wallet:
                wallet_trades[wallet].append(t)

        # Score wallets (simplified - would use full wallet analysis in production)
        smart_wallets = []
        for wallet, w_trades in wallet_trades.items():
            if len(w_trades) < 5:
                continue

            # Check if wallet is in cache
            if wallet in self.smart_wallet_cache:
                cached = self.smart_wallet_cache[wallet]
                if datetime.now() - cached["analyzed_at"] < self.cache_ttl:
                    if cached["is_smart"]:
                        smart_wallets.append(wallet)
                    continue

            # Quick heuristic: consistent winners, reasonable size, not MM
            volumes = [float(t.get("size", 0)) for t in w_trades]
            avg_volume = np.mean(volumes)
            if avg_volume < 100:  # Too small
                continue

            # Check win rate (simplified - would need resolution data)
            # For now, flag wallets with consistent directional bets
            outcomes = [t.get("outcome", "") for t in w_trades]
            if len(set(outcomes)) == 1 and len(w_trades) >= 10:
                smart_wallets.append(wallet)

            # Cache result
            self.smart_wallet_cache[wallet] = {
                "is_smart": wallet in smart_wallets,
                "analyzed_at": datetime.now(),
            }

        metrics.smart_money_wallets = smart_wallets

        # Compute smart money net flow per outcome
        for wallet in smart_wallets:
            for t in wallet_trades[wallet]:
                outcome = t.get("outcome", "")
                size = float(t.get("size", 0))
                side = t.get("side", "")
                flow = size if side == "BUY" else -size
                metrics.smart_money_net_flow[outcome] = metrics.smart_money_net_flow.get(outcome, 0) + flow

    async def _detect_mispricing(self, metrics: MarketMetrics):
        """Detect potential mispricing signals."""
        score = 0.0

        # Thin liquidity = higher mispricing potential
        if metrics.volume_24h < 10000:
            score += 0.3
        elif metrics.volume_24h < 50000:
            score += 0.1

        # Large smart money flow against current price
        for outcome, flow in metrics.smart_money_net_flow.items():
            current_price = metrics.current_prices.get(outcome, 0.5)
            if flow > 0 and current_price < 0.4:  # Smart money buying cheap
                score += 0.2
            elif flow < 0 and current_price > 0.6:  # Smart money selling expensive
                score += 0.2

        # High wallet concentration = manipulation risk
        if metrics.wallet_concentration > 0.5:
            score += 0.2

        metrics.mispricing_score = min(score, 1.0)

    async def _detect_momentum(self, metrics: MarketMetrics):
        """Detect price momentum."""
        bullish_count = 0
        bearish_count = 0

        for outcome, change in metrics.price_change_1h.items():
            if change > 0.02:
                bullish_count += 1
            elif change < -0.02:
                bearish_count += 1

        if bullish_count > bearish_count:
            metrics.momentum_signal = "bullish"
        elif bearish_count > bullish_count:
            metrics.momentum_signal = "bearish"
        else:
            metrics.momentum_signal = "neutral"

    async def scan_category(self, category: str, limit: int = 20) -> List[MarketMetrics]:
        """Scan all markets in a category for signals."""
        markets = await self.polymarket.get_active_markets(category=category, limit=limit)
        results = []

        for market in markets:
            condition_id = market.get("conditionId")
            if not condition_id:
                continue
            try:
                metrics = await self.analyze_market(condition_id)
                results.append(metrics)
            except Exception as e:
                print(f"Failed to analyze {condition_id}: {e}")

        # Sort by signal strength
        results.sort(key=lambda m: m.mispricing_score + (0.2 if m.momentum_signal != "neutral" else 0), reverse=True)
        return results

    async def get_top_signals(self, category: str = "fed-rate-decisions", top_k: int = 5) -> List[MarketMetrics]:
        """Get top actionable signals for a category."""
        results = await self.scan_category(category)
        return results[:top_k]


# Convenience function
async def analyze_market(condition_id: str, polymarket: PolymarketSource = None) -> MarketMetrics:
    """Quick analysis of a single market."""
    if polymarket is None:
        polymarket = PolymarketSource()
    analyzer = MarketAnalyzer(polymarket)
    return await analyzer.analyze_market(condition_id)