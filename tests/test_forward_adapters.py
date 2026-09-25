import asyncio
import unittest
from types import SimpleNamespace

from oracle.calibration.forward_adapters import ForwardFeatureCollector, LayaForwardJudgment


class FakePolymarket:
    async def get_market_details(self, condition_id):
        return {"question": "Will X pass?", "category": "test", "outcomes": ["Yes", "No"]}

    async def get_market_trades(self, condition_id, limit=100):
        return [
            {"outcome": "Yes", "price": "0.61", "size": "80", "side": "BUY", "user": "w1"},
            {"outcome": "No", "price": "0.39", "size": "30", "side": "SELL", "user": "w1"},
        ]


class FakeLaya:
    async def judge(self, input_data):
        return SimpleNamespace(
            probability=0.62,
            confidence=0.71,
            routing_info={"model": "typed-decisions"},
        )


class ForwardAdapterTests(unittest.TestCase):
    def test_feature_collector_does_not_read_outcomes(self):
        collector = ForwardFeatureCollector(FakePolymarket())
        features = asyncio.run(collector({"conditionId": "0x1", "question": "Q"}))
        self.assertEqual(features["latest_market_price"], 0.61)
        self.assertEqual(features["market"]["condition_id"], "0x1")
        self.assertNotIn("actual_outcome", features)
        self.assertIn("smart_money_net_flow", features)
        self.assertIn("macro_context", features)

    def test_laya_judgment_returns_backend_and_calibrated_outputs(self):
        judgment = LayaForwardJudgment(FakeLaya())
        probability, confidence, backend = asyncio.run(judgment("Q", {
            "market": {"condition_id": "0x1"},
            "macro_context": {},
        }))
        self.assertEqual((probability, confidence), (0.62, 0.71))
        self.assertEqual(backend, "laya:typed-decisions")


if __name__ == "__main__":
    unittest.main()
