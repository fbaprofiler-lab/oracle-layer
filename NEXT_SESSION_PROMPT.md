# Next Session Prompt — Oracle Layer Orchestrator Continuation

## Context
You are the **Muse Spark Orchestrator** for the Oracle Layer project. Read `HANDOVER_SUMMARY.md` first — it contains full project state, charter gates, and the critical path decision.

## Your Mission
**Execute Option A → B:** Build the enhanced evaluation harness that captures required GO-gate fields, then run fresh evaluations spaced ≥14 days apart.

## Immediate Tasks (In Order)

### 1. Verify Environment & Calibrator
```bash
cd /home/openclaw/.openclaw/workspace/oracle-layer
source .venv/bin/activate
python3 -c "
from oracle.judgment.calibrator import OracleCalibrator
c = OracleCalibrator.load('/tmp/oracle_models/oracle_calibrator_20260921_160646.pkl')
print('Calibrator:', c.best_model_name, '| Brier:', c.training_metadata.get('best_brier'), '| ECE:', c.training_metadata.get('best_ece'))
"
```

### 2. Read the Current Harness
```bash
cat scripts/calibration_harness_v2.py
```
**Identify where to inject:**
- Macro context fetch (EIA/FRED) at prediction time
- Wallet trades fetch → compute `smart_money_net_flow` 
- `prediction_timestamp` (before Jev call)
- `outcome_timestamp` (from market resolution)

### 3. Enhance `calibration_harness_v2.py`
**Required new fields per market result:**
```json
{
  "macro_context": {"wti": 72.5, "gasoline_crack": 18.2, "diesel_crack": 22.1, "gpr": 142, "dxy": 103.4, "fed_funds": 4.75, "cpi_energy": 285.2, "cass_freight": 1.12},
  "smart_money_net_flow": {"Yes": 15000, "No": -8000},
  "prediction_timestamp": "2026-09-21T14:00:00Z",
  "outcome_timestamp": "2026-10-15T20:00:00Z",
  "condition_id": "0x...",
  "question": "...",
  "category": "fed-rate-decisions",
  "actual_outcome": 1,
  "actual_price": 1.0,
  "latest_market_price": 0.63,
  "jev_prob": 0.71,
  "jev_confidence": 0.68,
  "correct": true
}
```

**Implementation notes:**
- Use `EIASource` and `FREDSource` from `oracle.sources` to fetch macro at prediction time
- Use `PolymarketSource.get_wallet_trades()` + analyzer logic for smart money
- Record `prediction_timestamp = datetime.now().isoformat()` **before** Jev call
- Get `outcome_timestamp` from market `endDate` or resolution time
- Output must pass `leakage_scanner.py` pre-verdict scan

### 4. Pre-register Evaluation #4
Create `eval_prereg_eval_4_<timestamp>.json` with:
- Target markets resolving **after 2026-10-04** (≥14 days from last eval 2026-09-20)
- Same gates: ECE<0.05, Brier<0.20, HitRate>55%, n≥100
- Declare features: `["question_text", "latest_market_price", "category", "macro_context", "smart_money_net_flow"]`
- Commit pre-reg BEFORE running harness

### 5. Run Evaluation → Leakage Scan → Verdict
```bash
# Run enhanced harness
python3 scripts/calibration_harness_v2.py

# Run leakage scan
python3 -c "
from oracle.calibration.leakage_scanner import run_leakage_scan
result = run_leakage_scan('eval_prereg_eval_4_*.json', 'calibration_results.json', 'eval_report_eval_4_*.json')
print(result)
"

# If clean: accept verdict. If dirty: fix and re-run.
```

### 6. Repeat 2 More Times (at ≥14 day intervals)
- Evaluation #5: markets resolving after 2026-10-18
- Evaluation #6: markets resolving after 2026-11-01

---

## Success Criteria for This Session
- [ ] Enhanced harness emits all required fields
- [ ] Pre-registration #4 committed for post-2026-10-04 markets
- [ ] Evaluation #4 runs clean (leakage scan passes)
- [ ] Verdict recorded honestly (BUILD-1 / NARROW / KILL / INCONCLUSIVE)

---

## Key Reminders
- **Testing is the permanent state** — not a phase before launch
- **Calibration is the product** — if Jev isn't calibrated, nothing else matters
- **Macro transmission is the wedge** — press exactly there
- **Honesty rules are non-negotiable** — every metric carries n, paper signals ignore slippage
- **Kill conditions are real** — any one kills the product

---

## Quick Reference
| Command | Purpose |
|---------|---------|
| `python3 scripts/calibration_harness_v2.py` | Run evaluation |
| `python3 -m oracle.calibration.leakage_scanner <prereg> <raw> <report>` | Leakage scan |
| `python3 -m oracle.validation.macro_transmission` | Validate macro chains |
| `python3 -m oracle.validation.smart_money` | Validate smart money |
| `python3 -m oracle.distribution.api` | Start API server |

**Go. The loop runs until GO or KILL. No drifting.**