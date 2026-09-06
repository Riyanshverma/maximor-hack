# TieOut — Implementation Progress

**Status as of 2026-09-06:** Phases 1–3 complete (11 PRs merged). Frozen contract, provable data flow, and six blocking proofs ready. Phase 4 begins with seven MVP exception handlers.

---

## Phase 1 — Freeze the contract (DONE)

### Database Schema
`backend/app/models/schema.py` defines the following tables:
- **close_run** — tracks period, status, rules_enabled flag, seed for reproducibility, metrics
- **settlement_event** — canonical form from Dodo breakup-details (event_type, payout_id, amount_native, amount_payout, fx_rate, raw JSONB payload)
- **payout** — gross, fees, net, currency, bank_line_id reference
- **bank_line** — posted_at, amount, currency, matched_payout_id reference
- **invoice** — customer_id, issued_at, subtotal, tax, total, line_items JSONB
- **gl_account** — chart of accounts (code, name, type, normal_side, is_restricted)
- **journal_entry** — status (draft|posted|reversed), created_by (agent|human|rule), source_exception_id, rule_id
- **journal_line** — debit/credit pair, account_code, settlement_event_id link, CHECK constraint (exactly one of debit/credit is non-zero)
- **exception** — type, severity, status (open|auto_resolved|escalated|human_resolved), evidence/hypotheses/proposed_remedy JSONB, matched_rule_id, ground_truth_key
- **rule** — name, version, predicate/action JSONB, rationale, source_ruling_id, active flag, times_applied counter
- **proof_result** — id, passed, expected/actual/delta for audit trail

### Contracts Frozen
`backend/app/contracts.py` defines two immutable protocols:

**ExceptionHandler** — each handler implements:
- `detect(ctx: RunContext) → list[ExceptionDraft]` — deterministic detection only
- `gather(exc, ctx) → dict` — deterministic evidence collection
- `hypothesize(exc, evidence) → list[dict]` — may use LLM for structure only
- `propose(exc, hypothesis) → dict | None` — LLM proposes remedy; amounts from tools only
- `compile_rule(exc, ruling) → dict | None` — Judgment Compiler compiles human rulings into reusable rules

**ProofObligation** — each proof implements:
- `evaluate(ctx: RunContext) → ProofResult` — pure function, no LLM, no network, no mocking

### API Stubs
`backend/app/main.py` and `backend/app/api/__init__.py` establish FastAPI stubs for future phases.

### CI Pipeline
`.github/workflows/ci.yml` (triggered on push to main and PRs):
- **Backend:** Python 3.12, PostgreSQL 16 service container
  - Install dependencies via `uv sync --all-extras`
  - Lint with `ruff check backend/`
  - Type check with `pyright backend/app` (basic mode)
  - Run tests with `pytest backend/tests/ -v` (DATABASE_URL points to test Postgres)
- **Frontend:** Bun package manager
  - Install with `bun install` (working-directory: ./frontend)
  - Build with `bun run build`
  - Run tests with `bun test` (skipped if no tests exist)

### Dependencies Confirmed
- **Backend:** `pyproject.toml`
  - Runtime: FastAPI ≥0.104.0, Uvicorn ≥0.30.0, SQLAlchemy ≥2.0.0, Alembic ≥1.13.0, Pydantic ≥2.5.0
  - Dev: pytest ≥7.4.0, pytest-asyncio ≥0.23.0, httpx ≥0.25.0, ruff ≥0.4.0, pyright ≥1.1.0
  - Package manager: `uv` (astral-sh)
- **Frontend:** `package.json` (bun)
  - Next.js 15 scaffold at `frontend/app/`

### Test Coverage
`backend/tests/test_contracts.py` validates the frozen protocols; `backend/tests/test_schema.py` confirms database table creation.

### Merged PRs
- **#3:** Phase 1 — Freeze contracts (schema + protocols + API stubs)
- **#2:** Docs refactor with sponsor models
- **#1:** TieOut README

---

## Phase 2 — Data flowing (DONE)

### Dodo Integration
`backend/app/ingest/dodo.py` — production-ready Dodo API integration. Fetches payouts and breakup-details; canonicalizes into `SettlementEvent` objects.

### Test Data Generator
`backend/app/ingest/generator.py` — deterministic generator with seeded randomness. Implements `PlantedException` class to document known exception types in test data (period, expected_resolution, ground_truth_key). Manifest published in generator module docstring: all planted exceptions listed with periods (August, September) and expected resolutions for metric validation.

### Data Loader
`backend/app/ingest/loader.py` — establishes database connection via `get_db_url()` and provides engine/session patterns used by all downstream components.

### Test Coverage
`backend/tests/test_generator.py` validates deterministic seeding and planted-exception manifest; fixtures trigger known exception types for Phase 4+ handler testing.

### Merged PRs
- **#4:** Phase 2 — Dodo integration and deterministic test data generator

---

## Phase 3 — Six proofs + Matcher (DONE)

All proofs are pure functions (`evaluate(ctx: RunContext) → ProofResult`), blocking (`blocking=True`), with no LLM, no network, no mocking. Each has a clean-pass test and a deliberate failure test.

### P1: Debit/Credit Balance
`backend/app/engine/proofs/p1.py` — sums all debit lines and credit lines from journal entries; must net to $0.00 for the period to close. Test: clean period passes; off-by-one-cent case fails as expected.

### P2: Payout Components Sum
`backend/app/engine/proofs/p2.py` — sums a payout's component settlement events (in payout currency) and verifies the total equals `payout.net`. Catches broken payout decomposition. Test: clean period passes; sum-mismatch fixture fails.

### P3: Clearing Account Rollforward
`backend/app/engine/proofs/p3.py` — sums signed `SettlementEvent.amount_payout` per run into categories (charges, fees, refunds, disputes, tax_remitted, reserve_movements, fx_adjustment) and nets against total `Payout.net`. Residual must equal $0.00. **The headline proof from `docs/04-demo-script.md`:** a deliberate $4,812.50 residual mirrors the demo script's blocking moment. Test: clean period passes; $4,812.50 delta case fails.

### P4: Bank Tieout
`backend/app/engine/proofs/p4.py` — every settled payout must tie out to exactly one matching bank deposit. Bank deposits typically post within a week of payout settlement. Catches unmatched payouts and timing misalignment. Test: clean period passes; unmatched payout fixture fails.

### P5: Revenue Completeness
`backend/app/engine/proofs/p5.py` — validates that all recognized revenue events have been journalized with corresponding GL accounts. Ensures no revenue leakage. Test: clean period passes; missing journal entry fixture fails.

### P6: No Orphans
`backend/app/engine/proofs/p6.py` — refund whose original charge is not in scope (refund with payment_id not present in current or prior loaded period). Detects orphaned refunds. Test: clean period passes; orphaned-refund fixture fails.

### Payout Decomposition Matcher
`backend/app/engine/matcher.py` — decomposes payout header into component settlement events and matches them to bank lines. Routes ambiguous entries to the Classifier (LLM) for account assignment.

### Test Coverage
- **test_p1.py** — P1 proofs (clean + off-by-one-cent failure)
- **test_p2.py** — P2 proofs (clean + sum-mismatch failure)
- **test_p3.py** — P3 proofs (clean + $4,812.50 delta failure from demo script)
- **test_p4.py** — P4 proofs (clean + unmatched payout failure)
- **test_p5_revenue_completeness.py** — P5 proofs (clean + missing journal entry failure)
- **test_p6_no_orphans.py** — P6 proofs (clean + orphaned refund failure)
- **test_matcher.py** — Payout decomposition and bank line matching
- **test_api.py** — FastAPI endpoint stubs and orchestration flow

All 39 tests passing (as of latest CI run).

### Merged PRs
- **#6:** P1 debit/credit balance proof obligation
- **#7:** P2 payout components sum proof obligation
- **#8:** Phase 3 matcher and bank tieout (payout decomposition)
- **#9:** P4 bank tieout proof obligation
- **#10:** P5 revenue completeness proof obligation
- **#11:** P3 clearing account rollforward proof (headline proof from demo script)
- **#5:** P6 no-orphans proof obligation

---

## Phase 4 — Exception handlers (NOT STARTED)

### Scope
Implement seven MVP exception handlers from `docs/02-exception-taxonomy.md` (marked `priority="must"`). Each handler ships with:
1. A fixture that triggers the handler and exercises its detect → gather → hypothesize → propose flow
2. A near-miss fixture that deliberately should NOT trigger

### The Seven MVP Exception Handlers

| Type | Detect | Evidence | Auto If | Escalate If |
|------|--------|----------|---------|------------|
| **AMOUNT_MISMATCH** | Sum of breakup-details ≠ payout.net | entry list, payout header, per-entry FX rate | delta ≤ $1.00, attributable to pro-rating → 7490 | delta > $1.00 or cap consumed |
| **FX_VARIANCE** | Effective FX rate outside expected band | entry rate, historical range, payment method | explainable by method/geography mix | unexplained variance |
| **DISPUTE_LIFECYCLE_INCOMPLETE** | Dispute without matching resolution | dispute entry, linked payment, prior periods | dispute found in prior closed period → reverse | dispute never resolved |
| **DUPLICATE_CHARGE** | Same customer, same amount, same date, within 24h | charge entries, customer, timestamp, amount | duplicate detected, merge to single entry, net refund → 7899 | cannot merge (conflicting GL post) |
| **MISSING_INVOICE** | Charge with no matching invoice found | charge, customer_id, invoice lookup, prior periods | found in prior period → cross-period note | not found anywhere |
| **TIMING_CUTOFF** | Event occurred just before period end; settlement posted just after | event timestamp, settlement timestamp, period boundary | timing explainable by standard lag → post with note | lag exceeds SLA |
| **POLICY_VIOLATION** | Charge to a restricted GL account (e.g. suspended customer) | charge, GL account, restriction flag | human approval required (no auto) | escalate to compliance |

### Implementation Pattern
Each handler is a module under `backend/app/engine/handlers/` (e.g., `amount_mismatch.py`). Each implements the `ExceptionHandler` protocol:
```python
class AmountMismatchHandler:
    type = "AMOUNT_MISMATCH"
    build_priority = 1  # must (1–7)
    
    def detect(self, ctx: RunContext) -> list[ExceptionDraft]: ...
    def gather(self, exc, ctx) -> dict: ...
    def hypothesize(self, exc, evidence) -> list[dict]: ...
    def propose(self, exc, hypothesis) -> dict | None: ...
    def compile_rule(self, exc, ruling) -> dict | None: ...
```

All handler logic is **pure and deterministic** until `propose`. Test fixtures use seeded test data from Phase 2 generator.

### Definition of Done
- All seven MVP handlers pass their trigger and near-miss fixtures
- Seven PRs merged (one handler per PR)
- CI green (ruff, pyright, pytest)

---

## Phase 5 — Wire end to end (NOT STARTED)

**Hours 16–20**

Scope:
- **Investigator agent** — LLM-driven hypothesis generation and evidence gathering for detected exceptions
- **SSE live feed** — server-sent events stream phase transitions (ingest → decompose → prove → investigate → escalate → resolve) to browser
- **Exception queue UI** — frontend screens to view detected exceptions, their evidence, hypotheses, and routing decisions

**Definition of done:** `POST /runs` on August dataset streams live phases to browser and lands on blocked close with visible proof failure.

---

## Phase 6 — Close the loop (NOT STARTED)

**Hours 20–24**

Scope:
- **Human approval screen** — show exception, handler evidence, proposed remedy, ask for approval or alternative resolution
- **Judgment Compiler** — compile human ruling into a reusable rule (predicate → action)
- **Rule reuse validation** — re-run period with new rule; verify P3 now passes and period closes

**Definition of done:** resolving an exception with a rationale produces a versioned rule in `GET /rules`; re-running the period shows P3 passing and the period closing.

---

## Phase 7 — Run the experiment (NOT STARTED)

**Hours 24–28**

Scope:
- **Run1/Run2-treatment vs. Run2-control** — split data into treatment (rules enabled) and control (no rules)
- **Automation-rate metrics** — measure % of exceptions auto-resolved without human approval

---

## Phase 8 — Rehearse and record (NOT STARTED)

**Hours 28–32**

Scope:
- **Demo rehearsal** — walk through the settlement close flow, highlight P3 failure, show investigation, show rule compilation, re-run with rule applied
- **Fallback video** — pre-recorded demo (5 min) in case live demo fails
- **Devpost submission** — upload video, README, and GitHub link

---

## Known issues / Notes for next developer

### GitHub & Merging
- **No branch protection** on main; all merges by reviewing diffs directly via GitHub API or manual merge, not AO's native review/merge (which has environment bugs in this setup). Fine to continue.
- **Copilot PR-review quota exhausted** account-wide (cosmetic; review comments still posted manually).

### Architecture Notes
- All six proofs are **blocking** and must pass before any exception handler runs. If any proof fails, the close is blocked and investigation flow begins.
- Exception autonomy is **conjunctive:** auto-resolve only if ALL four hold: (1) passing proof after remedy, (2) amount < $250, (3) classifier confidence ≥ 0.85, (4) matching rule or known archetype. Any one failing → escalate.
- Test fixtures are **seeded and deterministic** (from Phase 2 generator). Reuse them in Phase 4 handler tests; add new fixtures only for new exception types.

### Code Structure
- Proofs live in `backend/app/engine/proofs/` (p1.py–p6.py)
- Matcher in `backend/app/engine/matcher.py`
- Handlers will live in `backend/app/engine/handlers/` (to be created in Phase 4)
- Tests in `backend/tests/` (mirror the source structure: test_p1.py, test_p2.py, etc.)

### Next Steps (Phase 4 Checklist)
- [ ] Create `backend/app/engine/handlers/` directory
- [ ] Implement AMOUNT_MISMATCH handler (priority 1)
- [ ] Implement FX_VARIANCE handler (priority 2)
- [ ] Implement DISPUTE_LIFECYCLE_INCOMPLETE handler (priority 3)
- [ ] Implement DUPLICATE_CHARGE handler (priority 4)
- [ ] Implement MISSING_INVOICE handler (priority 5)
- [ ] Implement TIMING_CUTOFF handler (priority 6)
- [ ] Implement POLICY_VIOLATION handler (priority 7)
- [ ] Each handler: trigger fixture + near-miss fixture + tests
- [ ] All 39 existing tests still passing + new handler tests
- [ ] Ruff, pyright, pytest all clean

---

**Last updated:** 2026-09-06  
**By:** Claude Code (AO implementation worker)  
**Contact:** n.gupta@dynamicorestrategies.co.in
