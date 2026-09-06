# TieOut — Implementation Progress

**Status as of 2026-09-06:** Phases 1–3 fully implemented, verified, and audited (101 tests passing across 12 test files). Frozen contracts, deterministic data flow, bidirectional matcher, live PostgreSQL integration, and six blocking proof obligations ready. Phase 4 begins with seven MVP exception handlers.

---

## Phase 1 — Freeze the contract (DONE)

### Database Schema & Migrations
`backend/app/models/schema.py` defines the following tables:
- **close_run** — tracks period, status, rules_enabled flag, seed for reproducibility, metrics
- **settlement_event** — canonical form from Dodo breakup-details (event_type, payout_id, amount_native, amount_payout, fx_rate, raw JSONB payload)
- **payout** — gross, fees, net, currency, bank_line_id reference
- **bank_line** — posted_at, amount, currency, matched_payout_id reference
- **invoice** — customer_id, issued_at, subtotal, tax, total, line_items JSONB
- **gl_account** — 17 standard accounts from `docs/01-chart-of-accounts.md` (code, name, type, normal_side, is_restricted)
- **journal_entry** — status (draft|posted|reversed), created_by (agent|human|rule), source_exception_id, rule_id
- **journal_line** — debit/credit pair, account_code, settlement_event_id link, CHECK constraint (exactly one of debit/credit is non-zero)
- **exception** — type, severity, status (open|auto_resolved|escalated|human_resolved), evidence/hypotheses/proposed_remedy JSONB, matched_rule_id, ground_truth_key
- **rule** — name, version, predicate/action JSONB, rationale, source_ruling_id, active flag, times_applied counter
- **proof_result** — id, passed, expected/actual/delta for audit trail
- **audit_event** — append-only audit trail with SQLAlchemy event listener guarding against updates or deletions
- **exception.ground_truth_key** — write-once SQLAlchemy event listener guarding against mutating ground truth keys

Alembic migration (`001_initial_schema.py`) includes dialect guards for PostgreSQL vs. SQLite, resolves circular foreign keys between `payout` and `bank_line`, and ensures clean `alembic upgrade head` execution.

### Contracts Frozen
`backend/app/contracts.py` defines two immutable protocols:

**ExceptionHandler** — each handler implements:
- `detect(ctx: RunContext) → list[ExceptionDraft]` — deterministic detection only
- `gather(exc, ctx) → dict` — deterministic evidence collection
- `hypothesize(exc, evidence) → list[dict]` — may use LLM for structure only
- `propose(exc, hypothesis) → dict | None` — LLM proposes remedy; amounts from tools only
- `compile_rule(exc, ruling) → dict | None` — Judgment Compiler compiles human rulings into reusable rules

**ProofObligation** — each proof implements:
- `evaluate(ctx: RunContext) → ProofResult` — pure function, no LLM, no network, no mocking; returns `Decimal` metrics serialized as strings in details.

### API Endpoints
`backend/app/main.py` provides FastAPI endpoints:
- `POST /runs` accepts JSON `CreateRunRequest` with regex-validated period format (`^\d{4}-(?:0[1-9]|1[0-2])$`)
- `GET /runs/{run_id}` with 404 on non-existent runs
- `GET /runs/{run_id}/proofs` triggers matcher and evaluates all six proofs (P1–P6) with strict string-serialized money values
- `POST /exceptions/{exc_id}/resolve` accepts JSON `ResolveExceptionRequest` enforcing non-empty rationale

### Dependencies Confirmed
- **Backend:** `pyproject.toml`
  - Runtime: FastAPI, Uvicorn, SQLAlchemy 2.0, Alembic, Pydantic, psycopg2-binary, httpx
  - Dev: pytest, pytest-asyncio, ruff, pyright
  - Package manager: `uv` (astral-sh)
- **Frontend:** `package.json` (bun/npm)
  - Next.js 15 scaffold at `frontend/app/`

---

## Phase 2 — Data flowing (DONE)

### Dodo Integration
`backend/app/ingest/dodo.py` — production-ready Dodo API integration. Fetches payouts and breakup-details; canonicalizes into `SettlementEvent` objects.

### Test Data Generator
`backend/app/ingest/generator.py` — deterministic generator with seeded randomness:
- Decorated with `__test__ = False` to prevent pytest collection confusion
- Generates 17 chart of accounts matching `docs/01-chart-of-accounts.md`
- Generates deterministic SHA-256 IDs, UTC datetimes, and balanced clean journal entries
- Implements `PlantedException` documenting known exception types across August and September runs

### Data Loader
`backend/app/ingest/loader.py`:
- `get_db_url()` provides connection fallback (probes local port 55432, then default 5432)
- Idempotent cleanup in reverse dependency order
- Dependency-tiered insertion (`CloseRun` -> `Payout` -> `BankLine` -> `SettlementEvent` -> `Invoice` -> `JournalEntry` -> `JournalLine`) with separate flushes to respect PostgreSQL foreign key constraints
- Transactional execution with automatic rollback on error

---

## Phase 3 — Six proofs + Matcher (DONE)

All proofs are pure functions (`evaluate(ctx: RunContext, session: Session | None = None) → ProofResult`), blocking (`blocking=True`), with no LLM, no network, no mocking, rejecting non-finite Decimals and serializing money as decimal strings.

### P1: Debit/Credit Balance
`backend/app/engine/proofs/p1.py` — proves balance per entry AND per currency (`sum(debits) == sum(credits)`). Rejects mixed-currency entries and off-by-one-cent imbalances.

### P2: Payout Components Sum
`backend/app/engine/proofs/p2.py` — sums component settlement events grouped by payout currency and verifies the total equals `payout.net`. Rejects currency mismatches and off-by-one-cent discrepancies.

### P3: Clearing Account Rollforward
`backend/app/engine/proofs/p3.py` — evaluates the actual General Ledger rollforward on clearing account `1310`:
$$\text{Opening Balance (0.00)} + \sum \text{debits}_{1310} - \sum \text{credits}_{1310} = \text{Closing Balance (0.00)}$$
**Headline proof from demo script:** Detects the deliberate $4,812.50 residual and catches wrong-account mispostings (such as crediting 7490 instead of 1310).

### P4: Bank Tieout & Matcher
- `backend/app/engine/matcher.py`:
  - Matches payouts to bank lines with exact amount (+/-$0.00) and currency check
  - Symmetric ±3-day date window (`BANK_MATCH_DATE_WINDOW = timedelta(days=3)`)
  - Filters for settled payouts (`status in ("paid", "completed")`)
  - Resolves 1:N and N:1 ambiguities (leaves ambiguous records unmatched)
  - Persists bidirectional foreign keys (`bank_line.matched_payout_id` and `payout.bank_line_id`)
- `backend/app/engine/proofs/p4.py`:
  - Verifies that every settled payout has exactly one matched bank line conforming to the shared matcher contract.

### P5: Revenue Completeness
`backend/app/engine/proofs/p5.py` — verifies that recognized revenue on accounts `4010` and `4020` net of contra-revenue account `4900` equals invoiced `subtotal` per currency:
- Excludes sales tax collected (`2100`)
- Excludes dispute fees (`6820` expense)
- Catches tax mispostings to 4010 and revenue timing mismatches.

### P6: No Orphans Mapping Invariant
`backend/app/engine/proofs/p6.py` — proves that every `SettlementEvent` maps to its designated clearing journal line (`1310`), properly handling multi-line split entries without false duplicate errors and catching missing or dangling mappings.

### Golden Integration Test Suite
`backend/tests/test_golden.py` — end-to-end integration tests on real PostgreSQL and SQLite:
1. `test_golden_clean_baseline_all_proofs_pass` — full pipeline with matcher and proofs P1–P6 passes with 0 delta
2. `test_golden_isolated_defect_p1_imbalance` — isolated one-cent journal imbalance fails P1
3. `test_golden_isolated_defect_p2_component_mismatch` — component mismatch fails P2
4. `test_golden_isolated_defect_p3_clearing_misposting` — misposting payout credit to 7490 fails P3
5. `test_golden_isolated_defect_p4_bank_window` — deposit outside 3-day window fails P4
6. `test_golden_isolated_defect_p5_tax_miscredited_to_revenue` — tax misposting fails P5
7. `test_golden_isolated_defect_p6_missing_mapping` — unmapped event fails P6

### Complete Test Inventory (101 tests passing)
- `test_golden.py` (7 tests) — Golden PostgreSQL/SQLite integration baseline & defect injections
- `test_api.py` (16 tests) — FastAPI contracts, JSON validation, SSE, error handling
- `test_contracts.py` (11 tests) — Abstract protocol definitions & run context
- `test_generator.py` (16 tests) — Seeded determinism, planted exceptions manifest, loader idempotency
- `test_schema.py` (7 tests) — Alembic migration, ORM metadata, immutability listeners
- `test_matcher.py` (8 tests) — Payout decomposition, 1:1 matching, ambiguity resolution, bidirectional FKs
- `test_p1.py` (5 tests) — P1 multi-currency balance & decimal precision
- `test_p2.py` (5 tests) — P2 component sums & currency grouping
- `test_p3.py` (7 tests) — P3 clearing rollforward, demo $4,812.50 residual, 7490 misposting
- `test_p4.py` (8 tests) — P4 bank tieout, 3-day window, status filtering
- `test_p5_revenue_completeness.py` (6 tests) — P5 revenue net of contra, tax/fee exclusions
- `test_p6_no_orphans.py` (5 tests) — P6 designated clearing line & split entry handling

---

## Phase 4 — Exception handlers (NOT STARTED)

### Scope
Implement seven MVP exception handlers from `docs/02-exception-taxonomy.md` (marked `priority="must"`). Each handler ships with:
1. A fixture that triggers the handler and exercises its detect → gather → hypothesize → propose flow
2. A near-miss fixture that deliberately should NOT trigger

### The Seven MVP Exception Handlers (types 1, 2, 3, 6, 11, 12, 13)

From `docs/02-exception-taxonomy.md`:

| # | Type | Purpose |
|---|------|---------|
| 1 | **AMOUNT_MISMATCH** | Sum of breakup-details entries ≠ payout.net (catches pro-rating errors) |
| 2 | **FX_VARIANCE** | Effective FX rate outside expected band for payment method/geography |
| 3 | **DISPUTE_LIFECYCLE_INCOMPLETE** | Dispute without matching resolution (caught before close) |
| 6 | **TIMING_CUTOFF** | Event occurred just before period end; settlement posted just after (standard lag detection) |
| 11 | **BANK_UNMATCHED** | Settled payout has no exact-amount (+/-$0.00), in-window (±3-day) bank deposit match |
| 12 | **LOW_CONFIDENCE_CLASSIFICATION** | Ambiguous entry classified with confidence score < 0.85 (LLM judgment uncertain) |
| 13 | **POLICY_VIOLATION** | Charge to a restricted GL account (e.g., suspended customer, compliance holds) |

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
