# Oracle Layer — Real-Time Calibrated Prediction Market Intelligence with Generative Explanations

## Vision

The first system that fuses **macro/energy ground truth** → **prediction market microstructure** → **calibrated probabilistic judgment** → **generative explanations** into a single real-time intelligence feed.

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│  MACRO/ENERGY   │    │  PREDICTION     │    │  JEV/TYPE SAFE  │    │  HIGGSFIELD     │
│  PIPELINE       │───▶│  MARKET         │───▶│  JUDGMENT       │───▶│  EXPLAINERS     │
│  (EIA/FRED/GPR/ │    │  MICROSTRUCTURE │    │  (Calibrated    │    │  (30s video per │
│   NOAA/SPR)     │    │  (Wallet        │    │   P(up/down) +  │    │   market move)  │
│                 │    │   clusters,     │    │   rationale)    │    │                 │
└─────────────────┘    │   liquidity,    │    └─────────────────┘    └─────────────────┘
                       │   flow, order   │           │                    │
                       │   book depth)   │           ▼                    ▼
                       └─────────────────┘    ┌─────────────────┐    ┌─────────────────┐
                                              │  FUSION ENGINE  │    │  DISTRIBUTION   │
                                              │  (Orchestration)│    │  (API + App)    │
                                              │                 │    │                 │
                                              │ • Causal macro  │    │ • WebSocket API │
                                              │   → market with │    │ • Telegram bot  │
                                              │   lag models    │    │ • Web dashboard │
                                              │ • Smart-money   │    │ • Generative    │
                                              │   wallet signals│    │   explainers    │
                                              │ • Jev outputs   │    └─────────────────┘
                                              └─────────────────┘
```

## Core Components

| Module | Purpose | Status |
|--------|---------|--------|
| `oracle.sources` | Pluggable macro data connectors (EIA, FRED, NOAA, JODI, OPEC, OFAC, SPR) | 🔄 Building |
| `oracle.markets` | Polymarket adapters (order book, wallet clusters, liquidity, smart-money flow) | 📋 Planned |
| `oracle.judgment` | Jev/TypeSafe schemas + calibration pipeline for market-move prediction | 📋 Planned |
| `oracle.explainers` | Higgsfield generative pipeline: Jev rationale → video script → Seedance 2.5 | 📋 Planned |
| `oracle.distribution` | WebSocket API, Telegram bot, web dashboard, generative explainer delivery | 📋 Planned |

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
cp .env.example .env
# Edit .env with your API keys

# Run macro pipeline
python -m oracle.sources.run_all --date 2026-09-20

# Run market microstructure analysis
python -m oracle.markets.analyze --category "fed-rate-decisions"

# Run Jev calibration spike
python -m oracle.judgment.calibrate --lookback-days 180

# Generate explainer for a market move
python -m oracle.explainers.generate --market-id "0x..." --move-pct 5.2
```

## Configuration

All configuration via environment variables (see `.env.example`):
- **EIA_API_KEY** — EIA Open Data API key
- **FRED_API_KEY** — St. Louis Fed API key
- **POLYMARKET_API_KEY** — Optional, for higher rate limits
- **TYPE SAFE_API_KEY** — Jev API access
- **HIGGSFIELD_API_KEY** — Higgsfield generation
- **TELEGRAM_BOT_TOKEN** — Consumer bot
- **DATABASE_URL** — Postgres/TimescaleDB for time-series storage

## Development

```bash
# Run tests
pytest tests/

# Type check
mypy src/

# Format
ruff format src/
```

## Documentation

- [Architecture Decision Records](docs/adr/)
- [Jev Schema Definitions](docs/jev-schemas/)
- [Higgsfield Explainer Templates](docs/explainer-templates/)
- [API Specification](docs/api-spec.md)