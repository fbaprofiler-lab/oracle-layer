"""Tests for wallet skill measurement.

The central claim these tests defend: on a binary market, hit rate is not
skill. A wallet that wins 99% of its trades by paying 0.996 per share is
losing roughly 0.6% per trade, and a leaderboard ranked on hit rate would
crown it as the best trader on the platform.

This is the methodological core of the product, so the tests are adversarial:
they try to make the wrong wallet win, and fail if it does.
"""

import pytest

from oracle.calibration.wallet_skill import (
    MIN_MARKETS_SKILLED,
    WalletEvidence,
    WalletSkillEngine,
    expected_edge_per_trade,
    render_report,
    wilson_interval,
)


class TestExpectedEdge:
    """edge = hit * (1-p)/p - (1-hit)"""

    def test_coin_flip_at_even_price_is_zero(self):
        assert expected_edge_per_trade(0.50, 0.50) == 0.0

    def test_buying_favourite_at_its_own_price_is_break_even(self):
        # 90% hit rate at 0.90 is exactly break-even, not skill.
        assert expected_edge_per_trade(0.90, 0.90) == pytest.approx(0.0)

    def test_certainty_buyer_loses_money(self):
        # 99% hit at 0.996 pays 0.4c per winner and loses 100c on the 1 in 100.
        assert expected_edge_per_trade(0.99, 0.996) < 0

    def test_high_hit_rate_at_high_price_can_be_value_destroying(self):
        assert expected_edge_per_trade(0.80, 0.95) < 0

    def test_lower_hit_rate_at_lower_price_can_have_more_edge(self):
        modest = expected_edge_per_trade(0.58, 0.45)
        boastful = expected_edge_per_trade(0.90, 0.90)
        assert modest > boastful

    def test_rejects_impossible_prices(self):
        assert expected_edge_per_trade(0.6, 0.0) == 0.0
        assert expected_edge_per_trade(0.6, 1.0) == 0.0


class TestWilsonInterval:
    def test_large_sample_excludes_coin_flip(self):
        lo, hi = wilson_interval(20, 20)
        assert lo > 0.5
        assert hi == pytest.approx(1.0)

    def test_tiny_sample_admits_we_cannot_tell(self):
        lo, hi = wilson_interval(1, 1)
        assert lo <= 0.5 <= hi

    def test_zero_sample_is_uninformative(self):
        assert wilson_interval(0, 0) == (0.0, 1.0)


def _evidence(eng, wallet, n, wins, entry, category="mixed", start=1):
    ev = {}
    for i in range(n):
        won = i < wins
        # consistent with paying `entry`: winner pays 1.0, loser pays 0
        pnl = (1.0 - entry) if won else -entry
        eng.add_market(
            ev, wallet=wallet, category=category, won=won,
            pnl_usd=pnl, staked_usd=1.0, entry_price=entry,
            at=f"2026-01-{((start + i) % 28) + 1:02d}",
        )
    return ev


class TestRanking:
    def test_real_edge_outranks_certainty_buyer(self):
        eng = WalletSkillEngine()
        edge = _evidence(eng, "0xEDGE", n=40, wins=23, entry=0.45)[ "0xEDGE" ]
        cert = _evidence(eng, "0xCERT", n=40, wins=39, entry=0.996)["0xCERT"]

        p_edge = eng.score(edge)
        p_cert = eng.score(cert)
        assert p_edge.skill_score > p_cert.skill_score
        assert p_cert.hit_rate_is_expensive
        assert not p_edge.hit_rate_is_expensive

    def test_price_buyers_sorted_below_genuine_edge(self):
        eng = WalletSkillEngine()
        ev = {}
        ev.update(_evidence(eng, "0xEDGE", n=40, wins=23, entry=0.45))
        ev.update(_evidence(eng, "0xCERT", n=40, wins=39, entry=0.996))
        ranked = eng.rank(ev)
        assert ranked[0].wallet == "0xEDGE"
        assert ranked[-1].wallet == "0xCERT"

    def test_thin_sample_cannot_be_eligible(self):
        eng = WalletSkillEngine()
        ev = _evidence(eng, "0xLUCKY", n=5, wins=5, entry=0.30)
        p = eng.rank(ev)[0]
        assert not p.eligible
        assert "resolved markets" in (p.ineligible_reason or "")

    def test_zero_edge_wallet_scores_zero(self):
        eng = WalletSkillEngine()
        ev = _evidence(eng, "0xFAIR", n=40, wins=20, entry=0.50)
        assert eng.rank(ev)[0].skill_score == 0.0

    def test_larger_sample_scores_higher_at_equal_performance(self):
        eng = WalletSkillEngine()
        small = _evidence(eng, "0xS", n=25, wins=15, entry=0.45)["0xS"]
        large = _evidence(eng, "0xL", n=80, wins=48, entry=0.45)["0xL"]
        assert eng.score(large).skill_score > eng.score(small).skill_score

    def test_category_spread_is_tracked_for_market_agnosticism(self):
        eng = WalletSkillEngine()
        ev = {}
        for i in range(30):
            cat = ["fed", "crypto", "politics", "sports"][i % 4]
            won = i < 18
            eng.add_market(
                ev, wallet="0xMULTI", category=cat, won=won,
                pnl_usd=0.55 if won else -0.45, staked_usd=1.0, entry_price=0.45,
                at=f"2026-02-{i + 1:02d}",
            )
        p = eng.rank(ev)[0]
        assert p.categories == 4

    def test_untraded_market_does_not_count(self):
        # A wallet that never traded a market gets no evidence row at all,
        # rather than a zero-market row that would clutter the board and
        # imply we evaluated someone we know nothing about.
        eng = WalletSkillEngine()
        ev = {}
        eng.add_market(ev, wallet="0xW", category="c", won=True,
                       pnl_usd=1, staked_usd=1, traded=False)
        assert ev == {}
        assert eng.rank(ev) == []


class TestReport:
    def test_refuses_to_publish_an_empty_leaderboard_as_success(self):
        eng = WalletSkillEngine()
        ev = _evidence(eng, "0xTHIN", n=3, wins=3, entry=0.40)
        out = render_report(eng.rank(ev))
        assert "no wallet met the sample requirement" in out.lower()

    def test_lists_eligible_wallets(self):
        eng = WalletSkillEngine()
        ev = _evidence(eng, "0xOK", n=30, wins=18, entry=0.45)
        out = render_report(eng.rank(ev))
        assert "0xOK" in out
