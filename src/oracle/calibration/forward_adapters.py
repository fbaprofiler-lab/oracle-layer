"""Production adapter wiring for forward collection.

The adapters are deliberately constructed from existing source clients. They
perform only pre-outcome work: active-market data, macro observations, wallet
flow, and a judgment. Resolution/outcome lookup is intentionally absent.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping

from oracle.judgment.laya_client import (
    LayaClient,
    LayaDecisionType,
    LayaInput,
)


class ForwardFeatureCollector:
    """Collect the immutable feature snapshot used by forward judgment."""

    def __init__(self, polymarket: Any, eia: Any | None = None, fred: Any | None = None):
        self.polymarket = polymarket
        self.eia = eia
        self.fred = fred

    async def __call__(self, market: Mapping[str, Any]) -> dict[str, Any]:
        condition_id = str(market.get("conditionId", ""))
        details = await self.polymarket.get_market_details(condition_id)
        trades = await self.polymarket.get_market_trades(condition_id, limit=100)
        macro = await self._macro_snapshot()
        return {
            "market": {
                "condition_id": condition_id,
                "question": details.get("question") or market.get("question", ""),
                "category": details.get("category") or market.get("category", "unknown"),
                "outcomes": details.get("outcomes", []),
                "current_prices": self._current_prices(trades),
            },
            "latest_market_price": self._yes_price(trades),
            "macro_context": macro,
            "smart_money_net_flow": self._smart_money_flow(trades),
            "source_collected_at": datetime.now(timezone.utc).isoformat(),
            "feature_schema_version": "forward-1",
        }

    async def _macro_snapshot(self) -> dict[str, Any]:
        if self.eia is None and self.fred is None:
            return {"source": "disabled", "collected_at": datetime.now(timezone.utc).isoformat()}
        result: dict[str, Any] = {"source": "eia_fred", "collected_at": datetime.now(timezone.utc).isoformat()}
        for source, series in ((self.eia, ["gasoline_us", "diesel_us", "crude_stocks"]), (self.fred, ["wti", "dxy", "fed_funds", "breakeven_5y5y"])):
            if source is None:
                continue
            try:
                data = await source.fetch_multiple(series, limit=1)
                result[source.name] = {
                    key: [point.to_dict() for point in points[:1]]
                    for key, points in data.items()
                }
            except Exception as exc:
                result[source.name] = {"error": str(exc)}
        return result

    @staticmethod
    def _yes_price(trades: list[dict[str, Any]]) -> float | None:
        for trade in trades:
            if str(trade.get("outcome", "")).lower() == "yes":
                try:
                    return float(trade.get("price"))
                except (TypeError, ValueError):
                    continue
        return None

    @classmethod
    def _current_prices(cls, trades: list[dict[str, Any]]) -> dict[str, float]:
        prices: dict[str, float] = {}
        for trade in trades:
            outcome = str(trade.get("outcome", ""))
            try:
                if outcome:
                    prices[outcome] = float(trade.get("price"))
            except (TypeError, ValueError):
                continue
        return prices

    @staticmethod
    def _smart_money_flow(trades: list[dict[str, Any]]) -> dict[str, float]:
        # Conservative pre-registered proxy: directional flow, not wallet quality.
        by_wallet: dict[str, list[dict[str, Any]]] = {}
        for trade in trades:
            user = str(trade.get("user", ""))
            if user:
                by_wallet.setdefault(user, []).append(trade)
        flow: dict[str, float] = {}
        for wallet_trades in by_wallet.values():
            buys = sum(float(t.get("size", 0)) for t in wallet_trades if t.get("side") == "BUY")
            sells = sum(float(t.get("size", 0)) for t in wallet_trades if t.get("side") == "SELL")
            if buys + sells < 100 or buys / (buys + sells) < 0.7:
                continue
            for trade in wallet_trades:
                outcome = str(trade.get("outcome", ""))
                if outcome:
                    amount = float(trade.get("size", 0))
                    flow[outcome] = flow.get(outcome, 0.0) + (amount if trade.get("side") == "BUY" else -amount)
        return flow


class LayaForwardJudgment:
    """Adapt a Laya client to the collector's judgment callback."""

    def __init__(self, client: LayaClient):
        self.client = client

    async def __call__(self, question: str, features: Mapping[str, Any]) -> tuple[float, float, str]:
        result = await self.client.judge(LayaInput(
            decision_type=LayaDecisionType.MARKET_MOVE,
            market_id=str(features["market"]["condition_id"]),
            question=question,
            features=dict(features),
            context={"macro_context": features.get("macro_context", {})},
        ))
        backend = "laya"
        if result.routing_info.get("model"):
            backend += ":" + str(result.routing_info["model"])
        return float(result.probability), float(result.confidence), backend
