"""Wallet skill measurement — the product that survives the research.

What the research showed (2026-09-25, 599 resolved markets, 61k trades):

    skilled-wallet consensus : 98.6%
    market favourite (free)  : 100.0%
    EDGE                     : -1.4%

    contested markets (0.30-0.70 price) in test set: 0 of 115

So "smart money consensus predicts outcomes" is dead. The market price
already contains the information, and it is free. Any product that sells
"our signal beats the market" is selling a losing trade.

What is NOT dead: wallet skill is real and measurable. Wallets with 100%
hit rates across 15 independently resolved markets are not noise, and
that knowledge is not something a customer can get by looking at a price.

This module therefore measures SKILL, market-agnostically, and refuses to
call anyone skilled on a thin sample. It deliberately does not predict
outcomes; the honest deliverable is a ranked, evidenced set of wallets.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

# A wallet must have resolved this many markets before it can be called
# skilled. Five is where a 100% hit rate is trivially achievable by luck:
# the chance a random wallet hits 5/5 is 1/32.
MIN_MARKETS_SKILLED = 20
MIN_MARKETS_RANKED = 8

# Market makers are a different population. They hold both sides for a
# reason and are not directional predictors, so scoring them on ROI mixes
# two incompatible strategies. They are classified, never ranked together
# with directional traders.
MM_TRADES_PER_DAY = 50
MM_TWO_SIDED_SHARE = 0.5
MM_MEDIAN_DWELL_S = 300


def expected_edge_per_trade(hit_rate: float, entry_price: float) -> float:
    """Expected return per share, from hit rate and price paid.

        win  -> +(1 - price) / price
        loss -> -1.0

    This is the single most important number on the leaderboard. On a binary
    market a 90% hit rate bought at 0.90 is *break-even*, not skill, because
    0.9 x 11.1% - 0.1 x 100% = 0. Ranked by hit rate alone, a leaderboard
    would be a list of people who learned to buy certainty.
    """
    if entry_price <= 0 or entry_price >= 1:
        return 0.0
    return hit_rate * ((1.0 - entry_price) / entry_price) - (1.0 - hit_rate)


def wilson_interval(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Used instead of the normal approximation because small samples are
    exactly the regime where the naive interval is most wrong, and small
    samples are all we have for most wallets.
    """
    if n == 0:
        return (0.0, 1.0)
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, centre - margin), min(1.0, centre + margin))


@dataclass
class WalletEvidence:
    """Per-wallet raw observations, prior to scoring."""

    wallet: str
    markets: int = 0
    wins: int = 0
    staked_usd: float = 0.0
    pnl_usd: float = 0.0
    roi_by_market: list[float] = field(default_factory=list)
    trades: int = 0
    first_seen: str | None = None
    last_seen: str | None = None
    both_sides_markets: int = 0
    # category -> markets traded, so the profile can prove it is agnostic
    categories: dict[str, int] = field(default_factory=dict)
    # average price actually paid, and how many observations backed it
    entry_price_sum: float = 0.0
    entry_price_n: int = 0

    @property
    def hit_rate(self) -> float:
        return self.wins / self.markets if self.markets else 0.0

    @property
    def roi(self) -> float:
        return self.pnl_usd / self.staked_usd if self.staked_usd else 0.0

    @property
    def avg_entry_price(self) -> float:
        return self.entry_price_sum / self.entry_price_n if self.entry_price_n else 0.0


@dataclass
class WalletSkillProfile:
    """A scored wallet. This is the deliverable."""

    wallet: str
    rank: int = 0
    markets: int = 0
    hit_rate: float = 0.0
    hit_rate_lo: float = 0.0
    hit_rate_hi: float = 0.0
    roi: float = 0.0
    roi_median: float = 0.0
    roi_dispersion: float = 0.0
    avg_entry_price: float = 0.0
    edge_per_trade: float = 0.0
    skill_score: float = 0.0
    confidence: float = 0.0
    is_market_maker: bool = False
    categories: int = 0
    staked_usd: float = 0.0
    last_active: str | None = None
    eligible: bool = False
    ineligible_reason: str | None = None
    # True when the hit rate is bought at a price that leaves ~no edge.
    hit_rate_is_expensive: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_line(self) -> str:
        flag = "MM " if self.is_market_maker else "   "
        band = f"[{self.hit_rate_lo:.0%}-{self.hit_rate_hi:.0%}]"
        warn = "  PRICE-BUYING" if self.hit_rate_is_expensive else ""
        return (
            f"{self.rank:>3}. {flag}{self.wallet[:14]}…  "
            f"n={self.markets:<4} hit={self.hit_rate:>5.1%} {band}  "
            f"ROI={self.roi:>+7.2%}  entry={self.avg_entry_price:.3f}  "
            f"edge/trade={self.edge_per_trade:>+6.2%}  score={self.skill_score:.3f}"
            f"{warn}"
        )


class WalletSkillEngine:
    """Ranks wallets by demonstrated, market-agnostic skill."""

    def __init__(self, min_markets: int = MIN_MARKETS_SKILLED) -> None:
        self.min_markets = min_markets

    # -- evidence accumulation -----------------------------------------

    def add_market(
        self,
        evidence: dict[str, WalletEvidence],
        *,
        wallet: str,
        category: str,
        won: bool,
        pnl_usd: float,
        staked_usd: float,
        traded: bool = True,
        at: str | None = None,
        entry_price: float | None = None,
    ) -> None:
        """Record one wallet's result on one resolved market.

        A wallet is only counted as having played a market if it actually
        traded it; otherwise every wallet on the platform looks skilled for
        markets it merely observed.

        entry_price is the average price the wallet paid. It is essential,
        not cosmetic: see _expected_edge_per_trade. Hit rate without price
        is a vanity metric on a binary market.
        """
        if not traded:
            return
        e = evidence.setdefault(wallet, WalletEvidence(wallet=wallet))
        e.markets += 1
        e.wins += 1 if won else 0
        e.staked_usd += staked_usd
        e.pnl_usd += pnl_usd
        if staked_usd > 0:
            e.roi_by_market.append(pnl_usd / staked_usd)
        if entry_price:
            e.entry_price_sum += entry_price
            e.entry_price_n += 1
        if category:
            e.categories[category] = e.categories.get(category, 0) + 1
        if at:
            e.first_seen = min(e.first_seen or at, at)
            e.last_seen = max(e.last_seen or at, at)

    # -- scoring --------------------------------------------------------

    def score(self, e: WalletEvidence) -> WalletSkillProfile:
        p = WalletSkillProfile(
            wallet=e.wallet,
            markets=e.markets,
            hit_rate=e.hit_rate,
            roi=e.roi,
            staked_usd=e.staked_usd,
            categories=len(e.categories),
            last_active=e.last_seen,
        )
        p.hit_rate_lo, p.hit_rate_hi = wilson_interval(e.wins, e.markets)
        if e.roi_by_market:
            s = sorted(e.roi_by_market)
            med = s[len(s) // 2]
            p.roi_median = med
            p.roi_dispersion = sum(abs(v - med) for v in s) / len(s)
        p.avg_entry_price = e.avg_entry_price
        p.edge_per_trade = expected_edge_per_trade(p.hit_rate, p.avg_entry_price)
        # A 99% hit rate bought at 0.996 is not skill, it is a 0.4 cent
        # annuity. Flag it so the leaderboard cannot be read as a hit-rate
        # ranking when it is really a price ranking.
        p.hit_rate_is_expensive = bool(
            p.avg_entry_price and p.edge_per_trade < 0.01
        )
        p.is_market_maker = self._looks_like_mm(e)
        p.confidence = self._confidence(e.markets, p.hit_rate_lo, p.hit_rate_hi)
        p.skill_score = self._score(p)

        if p.is_market_maker:
            p.eligible, p.ineligible_reason = False, "market maker, not directional"
        elif e.markets < self.min_markets:
            p.eligible = False
            p.ineligible_reason = (
                f"{e.markets} resolved markets < {self.min_markets} required"
            )
        else:
            p.eligible = True
        return p

    @staticmethod
    def _confidence(markets: int, lo: float, hi: float) -> float:
        """How much the hit rate is pinned down, 0-1.

        Confidence is about sample size, not performance: a wallet with a
        wide interval is not known to be skilled, it is known to be unmeasured.
        """
        if markets == 0:
            return 0.0
        width = hi - lo
        return max(0.0, min(1.0, (1.0 - width) * math.log1p(markets) / math.log(51)))

    @staticmethod
    def _score(p: WalletSkillProfile) -> float:
        """Score on real edge per trade, discounted by uncertainty and sample.

        Hit rate is deliberately NOT the primary term. A wallet that wins 99%
        of 100 markets by paying 0.996 has no edge; a wallet winning 58% at
        0.45 does. Leading with hit rate is how a leaderboard becomes a list
        of people who buy expensive certainty.
        """
        if p.markets == 0:
            return 0.0
        edge = p.edge_per_trade
        if edge <= 0:
            return 0.0
        # Wilson lower bound on hit rate: only credit edge that survives the
        # plausible-worst-case reading of the sample.
        robustness = p.hit_rate_lo
        edge_term = math.tanh(max(edge, 0.0) * 10)   # ~ +/-10% edge saturates
        size_term = math.log1p(p.markets) / math.log(101)
        steadiness = 1.0 / (1.0 + p.roi_dispersion * 10)
        return (
            robustness * 0.30
            + edge_term * 0.40
            + size_term * 0.20
            + steadiness * 0.10
        )

    @staticmethod
    def _looks_like_mm(e: WalletEvidence) -> bool:
        """Heuristic: high-frequency two-sided flow on the same market."""
        if e.markets < 5 or e.trades < 50:
            return False
        two_sided = e.both_sides_markets / e.markets
        return two_sided >= MM_TWO_SIDED_SHARE

    def rank(self, evidence: Mapping[str, WalletEvidence]) -> list[WalletSkillProfile]:
        profiles = [self.score(e) for e in evidence.values()]
        # Price-buying wallets are ranked, but never above a wallet that
        # earns real edge; a 99% hit rate at 0.996 is a service, not an edge.
        profiles.sort(
            key=lambda p: (p.hit_rate_is_expensive, -p.skill_score, -p.markets)
        )
        for i, p in enumerate(profiles, 1):
            p.rank = i
        return profiles


# -- research harness ----------------------------------------------------

def render_report(
    profiles: Sequence[WalletSkillProfile],
    *,
    headline_only: bool = False,
) -> str:
    eligible = [p for p in profiles if p.eligible]
    lines = [
        f"ranked wallets: {len(profiles)}   eligible: {len(eligible)}",
        "",
    ]
    for p in eligible[:25]:
        lines.append(p.to_line())
    if not eligible:
        lines.append(
            "no wallet met the sample requirement. That is the honest result: "
            "an under-sampled leaderboard is worse than none."
        )
    return "\n".join(lines)


def save_report(profiles: Sequence[WalletSkillProfile], path: str) -> str:
    with open(path, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "min_markets_required": MIN_MARKETS_SKILLED,
                "wallets": [p.as_dict() for p in profiles],
            },
            f,
            indent=2,
        )
    return path
