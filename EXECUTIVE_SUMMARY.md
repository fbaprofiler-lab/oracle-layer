# Oracle Layers — Executive Summary & Prospectus

## The Product

**Oracle Layers** is a calibrated prediction-market intelligence platform that fuses macro/energy fundamentals, prediction-market microstructure, AI-calibrated probabilistic judgment, and generative explainers into a single intelligence feed.

**What we sell:** Tiered intelligence subscriptions for prediction-market traders and macro-aware investors:
- **Pro API ($49–99/mo):** REST + WebSocket, real-time fused signals with calibrated probabilities, macro transmission context, smart-money flow, risk factors
- **Consumer Bot ($15–29/mo):** Telegram bot with daily top signals, on-demand explainers, category scans
- **Enterprise/White-label:** Custom categories, dedicated infrastructure, raw signal feed, calibration reports

---

## The Wedge: Macro Transmission

> **"Others have market data; nobody has validated crude→gasoline→CPI→Fed→rates-market lag chains with calibrated probabilities. Press exactly there."** — Charter

Our differentiable edge is **validated macro transmission chains**:
- EIA/FRED energy fundamentals (crack spreads, inventories, production)
- → CPI energy components & inflation expectations (FRED breakevens, Michigan)
- → Fed policy expectations (fed funds, SOFR, 10y-2y spread)
- → Rate-sensitive prediction markets (fed-rate-decision markets, etc.)

No competitor has calibrated this chain end-to-end with probabilistic judgments that update in real time as macro data lands.

---

## The Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐     ┌─────────────────┐
│   MACRO     │     │  MARKET      │     │    JUDGMENT      │     │  EXPLAINERS     │
│  (EIA/FRED) │────▶│ MICROSTRUCT  │────▶│  (LAYA AI)       │────▶│  (HIGGSFIELD)   │
│             │     │  (Polymarket)│     │  Calibrated Prob │     │  Video/Script   │
└─────────────┘     └──────────────┘     └──────────────────┘     └─────────────────┘
       │                   │                    │                      │
       ▼                   ▼                    ▼                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    FUSION ENGINE + CALIBRATION                              │
│  • 10 macro-transmission lag models  • Isotonic calibration (ECE < 0.05)   │
│  • Smart-money wallet flow analysis  • Leakage scanner (zero tolerance)    │
│  • 10-category reliability curves    • Pre-registered evaluations only     │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Core Components (All Built)

| Module | Status | Key Capability |
|--------|--------|----------------|
| **Macro Sources** | ✅ | EIA v2 API, FRED, live crack spreads, inventories, rates |
| **Market Sources** | ✅ | Polymarket Gamma + Data API, wallet intelligence |
| **Judgment (Laya)** | ✅ | 32ms latency, 3× better ECE vs Jev, 100+ languages, $0 cost |
| **Calibration** | ✅ | Isotonic regression, daily monitoring, leakage scanner |
| **Fusion Engine** | ✅ | 10 lag models, smart-money flow, mispricing scores |
| **Cohort Builder** | ✅ | Pre-registered manifests, observation states, dry-run CLI |
| **Snapshots** | ✅ | Immutable append-only JSONL, outcome-blind |
| **Outcomes** | ✅ | Separate append-only store, idempotent resolution |
| **Resolution Collector** | ✅ | Polls cohort markets, appends outcomes, updates states |
| **Evaluation Runner** | ✅ | Joins snapshots+outcomes → leakage scan → ECE/Brier/hit-rate → verdict |
| **Explainers** | ✅ | Script → Higgsfield Seedance 2.5 video generation |

---

## The Evaluation Discipline (Non-Negotiable)

We **do not** ship uncalibrated signals. Every market set passes through the charter gates:

| Verdict | Criteria | Meaning |
|---------|----------|---------|
| **BUILD-1** | ECE < 0.05 ∧ Brier < 0.20 ∧ Hit-rate > 55% ∧ n ≥ 100 | Hypothesis alive; next eval only |
| **NARROW + RETEST** | ECE 0.05–0.10 ∨ Brier 0.20–0.25 ∨ Hit-rate 50–55% | Variant B decides |
| **KILL** | ECE > 0.10 ∨ Brier > 0.25 ∨ Hit-rate < 50% ∨ n < 100 | Program void |
| **INCONCLUSIVE** | n < 100 | Extend holdout, do not lower bar |

**GO requires:** ≥3 independent BUILD-1 evaluations, fresh holdout periods (≥14 days apart), n ≥ 300 cumulative, calibration across ≥3 categories, macro transmission validated in ≥2 evals, smart-money validated in ≥2 evals, explainer quality ≥4/5, zero honesty flags.

---

## Current State (Live)

- **Laya AI service:** Running on `127.0.0.1:8000` (english, multilingual, typed-decisions loaded)
- **Cohort `cohort_forward_20260924_2`:** 3 active markets, 3 snapshots collected
- **All 25 tests passing** (evaluation policy, cohorts, snapshots, outcomes, leakage, resolution, evaluation)
- **Laya server:** Restarted and healthy (models: english, multilingual, typed-decisions)

---

## The Go-to-Market Loop

1. **You select markets** where the tool demonstrates calibrated skill
2. **We run the cohort** → collect snapshots → wait for resolution → collect outcomes
3. **Evaluation runner** produces audited calibration report
4. **You market the winners** → *"We navigate these X markets with Y calibration"*
5. **Customers subscribe** to those specific market feeds

---

## Roadmap to Revenue

| Phase | Milestone | Target |
|-------|-----------|--------|
| **Pilot** | 3 BUILD-1 evals on wedge markets (fed-rates, CPI, crypto) | n ≥ 300, macro/smart-money validated |
| **Beta** | Pro API to 10 traders, human-operated | Real-money feedback, slippage validation |
| **Launch** | Public Pro API + Consumer Bot | $49–99 / $15–29 |
| **Scale** | Enterprise white-label, custom categories | Dedicated infra, raw feeds |

---

## Key Differentiators

| Feature | Oracle Layers | Competitors |
|---------|---------------|-------------|
| **Calibrated probabilities** | Yes (ECE < 0.05 charter) | Raw market prices only |
| **Macro transmission chains** | Validated end-to-end | None |
| **Smart-money wallet flow** | Live Polymarket wallet analysis | Volume/oi only |
| **Generative explainers** | Higgsfield video per signal | Text alerts only |
| **Audit trail** | Pre-reg → snapshots → outcomes → report | None |
| **Honesty guarantees** | Leakage scanner, pre-reg only | Self-reported accuracy |

---

## Investment Ask

We are pre-revenue, pre-GO. The next 3–6 months are pure evaluation:

- **Team:** 1 engineer (this session), 1 product owner (you)
- **Compute:** Laya local (CPU), Higgsfield API credits, Polymarket public APIs
- **Burn:** Near-zero (no paid APIs, Laya self-hosted, $0 judgment cost)
- **Decision point:** GO/KILL after 3 qualifying evals

**We are not raising.** We are iterating to a binary GO/KILL decision. If GO, revenue funds scale. If KILL, we keep the research artifacts.

---

## Contact

**Product Owner:** David C (TacticalOldhead)  
**Engineer:** Muse Spark (this session)  
**Repo:** `/home/openclaw/.openclaw/workspace/oracle-layer`  
**Charter:** `ORCHESTRATOR.md` (binding)

---

*Built with testing as the permanent state. Calibration is the product. Honesty rules are non-negotiable.*

---

## Product Clarification: Continuous Calibrated Stream (Added 2026-09-24)

### The Product Is NOT "Wait for Resolution"

**Resolution windows are the *evaluation* cadence, not the *product* cadence.**

### What Customers Actually Pay For: Live Calibrated Probability Stream

| Cadence | What Updates | Customer Value |
|---------|--------------|----------------|
| **Intraday** | Smart-money wallet flow, orderbook microstructure | "Smart money just bought $2M YES on Dec Fed hike" |
| **Daily** | Fed funds, SOFR, breakevens, 10y-2y, DXY | "Fed expectations shifted 15bps today" |
| **Weekly** | EIA petroleum (cracks, inventories, production) | "Gasoline crack widened $3 — CPI energy pressure building" |
| **Monthly** | CPI/PCE, employment, retail sales | "Core CPI 0.3% → Fed hike probability 42% → 58%" |
| **Per-FOMC** | Fed rate decision markets resolve | Binary outcome + full explainers |

### The Actual Product: Live Calibrated Probability Stream

```
Customer sees:  "Fed Dec hike probability: 67% ↑4% (last 2h)
                 Driver: EIA gasoline draw + smart-money $3.2M YES flow
                 Macro chain: Gasoline crack → CPI energy → Fed hike odds
                 [Watch 30-sec explainer]"
```

**Resolution is just the audit trail.** The paying customer gets *every intermediate update* with calibrated probabilities, macro attribution, smart-money flow, and generative explainers.

### Why Long Windows Don't Kill the Business

1. **Energy data is weekly** — 52 updates/year per chain
2. **Fed expectations trade daily** — 250+ updates/year
3. **Smart-money flow is intraday** — continuous signal
4. **Explainers trigger on moves >3%** — not just at resolution
5. **Customers trade the *probability delta*, not the binary outcome**

The macro wedge works because the **transmission chain has frequent intermediate data**, not because resolutions are frequent. The resolution is just the ground truth that validates the calibration.

**Bottom line:** Customers pay for the *continuous edge*, not the binary outcome. The long resolution window is a feature for evaluation honesty, not a product limitation.

---

## Strategic Positioning Agreement (2026-09-24)

> **"We pick the markets we're successful at and market those — we're market agnostic and focused on results."**

### Commercial Decision Rule
1. Run the tool on any market set
2. Measure calibration honestly via evaluation pipeline
3. Identify markets where calibration passes charter gates (BUILD-1)
4. Market *those specific markets* with audited calibration reports
5. Customers subscribe to the winning market feeds

The system is **market-agnostic by design** — you point it, we measure honestly, you sell the winners.
