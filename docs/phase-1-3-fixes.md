# TieOut — Phase 1–3 Defect Fixes and Verification Document

**Date:** 2026-09-06  
**Audited Baseline Commit:** `af4c7e8021ce04ff945e87ac6b11c15aa30c7936`  
**Target Branch:** `phase-4`  
**Test Coverage:** 101 passed, 0 failed across 12 test modules (unit, contract, and live PostgreSQL integration)

---

## 1. Executive Summary

During the Phase 1–3 verification audit of the TieOut codebase (recorded in `/tmp/maximor-phase3-verification.md` and `/tmp/maximor-phase3-progress.md`), several critical defects were identified across infrastructure, database migration, deterministic data loading, bank matching, and proof obligations P1–P6.

Every verified defect has been systematically corrected on the `phase-4` branch using an incremental, conventional commit strategy (9 discrete commits). All monetary arithmetic strictly enforces Python `Decimal` and `NUMERIC(18, 4)` in PostgreSQL, serialized as strings in JSON/API boundaries.

---

## 2. Commit History (`phase-4`)

| # | Commit | Conventional Title | Scope & Rationale |
|---|---|---|---|
| 1 | `fcd4878` | `fix: dependencies, connection configuration and migration` | Added `psycopg2-binary` and `httpx`; fixed Alembic migration dependency order, circular FKs, and PostgreSQL/SQLite dialect guards. |
| 2 | `ec9ebde` | `fix: deterministic generator/loader and schema integrity` | Added `__test__ = False` to generator; deterministic SHA-256 IDs; UTC dates; 17 GL accounts; append-only and write-once schema event listeners. |
| 3 | `e471e6d` | `fix: matcher and P4 shared bank contract` | Shared bank tie-out contract in `matcher.py` and `p4.py`: symmetric ±3-day window, status filtering, 1:N & N:1 ambiguity resolution, bidirectional FKs. |
| 4 | `9199aab` | `fix: P1/P2 currency and serialization boundaries` | P1 verifies debits == credits per entry **and** per currency; P2 groups components by payout currency; non-finite Decimals rejected; deltas formatted as strings. |
| 5 | `12a9caf` | `fix: replace P3 with actual ledger clearing proof` | Replaced source-event arithmetic stub with actual General Ledger rollforward on account 1310; detects demo script $4,812.50 residual and 7490 mispostings. |
| 6 | `0ad053c` | `fix: P5 recognized-revenue proof` | Compares invoiced subtotal against revenue credits (4010/4020) net of contra-revenue debits (4900); excludes sales tax (2100) and dispute fees (6820). |
| 7 | `bb37c83` | `fix: finalize P6 mapping invariant` | Designated clearing line (1310) logic for multi-line split entries; catches missing, duplicate, and dangling journal line mappings. |
| 8 | `c5cb56d` | `test: add golden PostgreSQL integration and API boundary tests` | Added `test_golden.py` (clean baseline + 6 isolated defect injections against live PostgreSQL); Pydantic JSON request models and 404 routes in `main.py`. |
| 9 | `f7f3fde` | `docs: update Phase 1-3 documentation to match verified behavior` | Updated `docs/progress.md` and `README.md` to reflect verified proof mechanics, 101 tests inventory, and quickstart commands. |

---

## 3. Detailed Breakdown of Implemented Fixes

### Phase 1: Infrastructure, Schema & Migrations

1. **Alembic Initial Migration (`backend/alembic/versions/001_initial_schema.py`)**:
   - **Problem:** Migration failed on PostgreSQL due to circular foreign keys between `payout` and `bank_line` (`bank_line.matched_payout_id` $\leftrightarrow$ `payout.bank_line_id`) and tables created out of topological order.
   - **Fix:** Added dialect guards (`op.get_bind().dialect.name`). Created tables in strict topological order, omitted cyclic FK during initial table creation, and added foreign key constraints via `op.create_foreign_key()` post-creation. Drop order reversed cleanly.
2. **Missing Runtime Dependencies (`pyproject.toml`)**:
   - Added `psycopg2-binary>=2.9.9` (for native PostgreSQL connections) and `httpx>=0.25.0` (for FastAPI test client).
3. **Schema Immutability & Event Listeners (`backend/app/models/schema.py`)**:
   - Added `@event.listens_for(AuditEvent, "before_update")` and `before_delete` raising `ValueError("AuditEvent is append-only: updates and deletions are forbidden")`.
   - Added `@event.listens_for(Exception.ground_truth_key, "set")` raising `ValueError("Exception.ground_truth_key is write-once and cannot be modified")` if an existing key is mutated.
4. **Standard Chart of Accounts**:
   - Standardized 17 GL accounts defined in `docs/01-chart-of-accounts.md` (including 1010, 1310, 1330, 2100, 4010, 4020, 4900, 6810, 6820, 7490, 8010).

---

### Phase 2: Deterministic Ingestion & Loader

1. **Test Data Generator (`backend/app/ingest/generator.py`)**:
   - Added `__test__ = False` to `TestDataGenerator` to prevent pytest from attempting to collect the class as a test suite.
   - Replaced non-deterministic `uuid.uuid4()` with deterministic SHA-256 hash generation (`_next_hex(tag)`) seeded from `self.seed`.
   - Guaranteed UTC timestamps across all generated entities.
   - Generated clean, balanced journal entries across accounts 1310 (Clearing), 4010 (SaaS Revenue), 1330 (In-Transit), and 1010 (Operating Cash).
2. **Transactional Data Loader (`backend/app/ingest/loader.py`)**:
   - **Problem:** Bulk inserts failed under PostgreSQL foreign key constraints because SQLAlchemy's topological table sorter could not resolve cyclic relationships during a single `session.flush()`.
   - **Fix:** Implemented tiered insertion with intermediate flushes by dependency order:
     1. `GLAccount` (merged)
     2. `CloseRun`
     3. `Payout`
     4. `BankLine`
     5. `SettlementEvent`
     6. `Invoice`
     7. `JournalEntry`
     8. `JournalLine`
   - Added automatic rollback on exceptions and idempotent cleanup breaking circular foreign keys before deletion.
   - Added connection fallback in `get_db_url()`: checks `DATABASE_URL`, probes local port 55432, and defaults to standard port 5432.

---

### Phase 3: Matcher and Proof Obligations P1–P6

#### Bank Line Matcher (`backend/app/engine/matcher.py`) & P4 (`backend/app/engine/proofs/p4.py`)
- **Shared Contract:**
  - Exact amount match (`bank_line.amount == payout.net`, zero tolerance).
  - Exact currency match (`bank_line.currency == payout.currency`).
  - Symmetric ±3-day window: `abs(bank_line.posted_at - payout.settled_at) <= timedelta(days=3)`.
  - Payout status filtering: only payouts with status `"paid"` or `"completed"` are eligible for matching.
  - Ambiguity resolution: requires exactly one candidate bank line for a payout (resolves 1:N) and exactly one candidate payout for that bank line (resolves N:1). Ambiguous matches are left unmapped.
  - Persists bidirectional foreign keys: `bank_line.matched_payout_id = payout.id` and `payout.bank_line_id = bank_line.id`.
- **P4 Invariant:** Evaluates that every settled payout has exactly one matched bank line satisfying this contract.

#### P1: Debit/Credit Balance (`backend/app/engine/proofs/p1.py`)
- Verifies that debits equal credits for every journal entry and across every currency:
  $$\sum \text{debits} - \sum \text{credits} = 0.00$$
- Strictly forbids cross-currency offset (an entry cannot balance USD debits with EUR credits).
- Rejects non-finite Decimal values (`NaN`, `sNaN`, `Infinity`).
- Details format all monetary amounts as explicit decimal strings.

#### P2: Payout Components Sum (`backend/app/engine/proofs/p2.py`)
- Groups component settlement events by payout currency and verifies:
  $$\sum \text{event.amount\_payout} = \text{payout.net}$$
- Catches currency mismatches and off-by-one-cent component calculation errors.
- Serializes breakdown and deltas as decimal strings.

#### P3: Clearing Account Rollforward (`backend/app/engine/proofs/p3.py`)
- **Complete Refactor:** Replaced heuristic arithmetic of raw settlement events with actual General Ledger rollforward on clearing account `1310`:
  $$\text{Opening Balance (0.00)} + \sum \text{debits}_{1310} - \sum \text{credits}_{1310} = \text{Closing Balance (0.00)}$$
- Verifies the headline demo case: detects the deliberate $4,812.50 residual when unposted settlement events or mispostings occur.
- Fails when payout transfers are miscredited to other accounts (such as suspense account `7490` instead of clearing account `1310`), leaving account 1310 un-cleared.

#### P5: Revenue Completeness (`backend/app/engine/proofs/p5.py`)
- Validates recognized revenue against invoiced subtotal per currency:
  $$\sum \text{credits}_{(4010, 4020)} - \sum \text{debits}_{4900} = \sum \text{invoice.subtotal}$$
- Excludes sales tax collected (credited to liability account `2100`).
- Excludes dispute / chargeback fees (debited to expense account `6820`).
- Flags tax mispostings (e.g. crediting sales tax directly to 4010) and one-cent revenue omissions.

#### P6: No Orphans Mapping Invariant (`backend/app/engine/proofs/p6.py`)
- Verifies that every `SettlementEvent` is mapped to its designated clearing journal line (`1310`).
- Correctly accommodates multi-line split entries (e.g., clearing debit with split revenue and tax credits) by targeting the clearing leg without throwing false duplicate mapping errors.
- Flags unmapped events, duplicate linkages, and dangling journal lines referencing non-existent events.

---

### API Boundaries & JSON Payload Validation (`backend/app/main.py`)

- **JSON Body Validation:** Replaced query parameters with Pydantic request models:
  - `CreateRunRequest`: validates period against `^\d{4}-(?:0[1-9]|1[0-2])$`.
  - `ResolveExceptionRequest`: enforces non-empty, non-whitespace `rationale`.
- **HTTP 404 Errors:** Endpoints return 404 when requested runs or exceptions do not exist.
- **Proof Execution:** `GET /runs/{run_id}/proofs` runs `match_bank_lines(session, run_id)` and evaluates P1–P6 against the database session, returning strictly string-serialized money values (`expected`, `actual`, `delta`).

---

### Golden Integration Test Suite (`backend/tests/test_golden.py`)

Added an integration test suite testing the full pipeline against live PostgreSQL:
1. `test_golden_clean_baseline_all_proofs_pass`: Full run through data loader, matcher, and proofs P1–P6 passing with 0 delta.
2. `test_golden_isolated_defect_p1_imbalance`: Tampering with journal line debit (+0.01) triggers P1 failure while other obligations hold.
3. `test_golden_isolated_defect_p2_component_mismatch`: Tampering with settlement event amount (+15.00) triggers P2 failure.
4. `test_golden_isolated_defect_p3_clearing_misposting`: Reposting payout credit to account 7490 triggers P3 failure with residual $4,750.00 while P1 entry balance passes.
5. `test_golden_isolated_defect_p4_bank_window`: Setting bank deposit date to 5 days after settlement triggers P4 failure.
6. `test_golden_isolated_defect_p5_tax_miscredited_to_revenue`: Crediting $50 tax to account 4010 triggers P5 failure.
7. `test_golden_isolated_defect_p6_missing_mapping`: Disconnecting settlement event from journal line triggers P6 failure.

---

## 4. Verification Evidence

### Pytest (101 passed)
```
backend/tests/test_api.py ................                               [ 15%]
backend/tests/test_contracts.py ...........                              [ 26%]
backend/tests/test_generator.py ................                         [ 42%]
backend/tests/test_golden.py .......                                     [ 49%]
backend/tests/test_matcher.py ........                                   [ 57%]
backend/tests/test_p1.py .....                                           [ 62%]
backend/tests/test_p2.py .....                                           [ 67%]
backend/tests/test_p3.py .......                                         [ 74%]
backend/tests/test_p4.py ........                                        [ 82%]
backend/tests/test_p5_revenue_completeness.py ......                     [ 88%]
backend/tests/test_p6_no_orphans.py .....                                [ 93%]
backend/tests/test_schema.py .......                                     [100%]

======================= 101 passed, 60 warnings in 3.17s =======================
```

### Ruff Linting
```
$ uv run ruff check .
All checks passed!
```

### Pyright Type Checking
```
$ uv run pyright
0 errors, 0 warnings, 0 informations
```

### Frontend Production Build
```
$ npm run build
   ▲ Next.js 15.5.25
   Creating an optimized production build ...
 ✓ Compiled successfully in 2.2s
   Linting and checking validity of types     ✓ Linting and checking validity of types
   Collecting page data     ✓ Collecting page data
 ✓ Generating static pages (4/4)
   Collecting build traces     ✓ Collecting build traces
   Finalizing page optimization     ✓ Finalizing page optimization
```

---

## 5. Summary of Maintained Invariants

- **Zero Floating-Point Representation:** All amounts are parsed, summed, and asserted using Python `Decimal` and PostgreSQL `NUMERIC(18, 4)`.
- **String Money Serialization:** Proof deltas, actuals, expecteds, and API responses serialize money as strings.
- **Repository Cleanliness:** Main repository worktree at `/home/dhruv/Project/hackathon/maximor-hack` and user-owned `.gitignore` modification (`.codegraph`) remain untouched.
