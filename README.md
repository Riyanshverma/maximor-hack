# TieOut

TieOut is a close agent for merchant-of-record settlement payouts. It turns each payout from a single lump sum into auditable journal entries for revenue, taxes, refunds, fees, disputes, reserves, FX, and cash movement—so finance teams can close with evidence instead of spreadsheet archaeology.

## The problem

Merchant-of-record payouts bundle many settlement events together. Decomposing those events, posting them to the right accounts, and proving that the MoR clearing account is fully reconciled is tedious and error-prone. A plausible-looking balance is not enough for a close: every residual needs a deterministic explanation.

## What it does

- Ingests and normalizes settlement, payout, bank, and invoice data.
- Decomposes payouts into balanced, table-driven journal entries using explicit currencies and decimal-safe money handling.
- Runs six deterministic proof obligations on every close. If the MoR clearing account is not proven empty, TieOut blocks the close rather than posting or silently plugging the difference.
- Detects typed exceptions and sends evidence to an LLM Investigator, which forms hypotheses and proposes remedies without computing amounts or editing the ledger.
- Routes exceptions through deterministic policy: low-risk, proven cases may auto-resolve; material, novel, low-confidence, restricted, or cap-breaching cases go to a human.
- Compiles a human ruling and required rationale into a versioned, reusable rule with provenance for future runs.

## Architecture

Deterministic state-machine spine — **Ingest → Normalize → Match → Compose → Prove → Package** — with narrow LLM call-outs for classification and investigation; every proposed remedy returns to the proof engine before it can post or close.

## Tech stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic
- **Data:** PostgreSQL (local Docker), `Decimal` / `NUMERIC(18,4)`; money serialized as strings
- **Agents:** Anthropic Messages API (Haiku classification, Opus investigation)
- **Frontend:** Next.js 15, Tailwind CSS, shadcn/ui, Recharts
- **Runtime and observability:** Server-Sent Events, Neatlogs SDK
- **Settlement source:** Dodo Payments test mode

## Design documents

See [`docs/`](docs/) for the chart of accounts, exception taxonomy, data model and contracts, demo script, and implementation plan.

## The Six Proof Obligations (P1–P6)

TieOut enforces six deterministic, blocking proof obligations on every close run before books can close:

1. **P1: Debit/Credit Balance** (`p1.py`) — Proves that every journal entry balances debits against credits per currency (`sum(debits) == sum(credits)`). Mixed-currency balancing is strictly rejected.
2. **P2: Payout Components Sum** (`p2.py`) — Verifies that component settlement events grouped by payout currency sum exactly to `payout.net`. Discrepancies block the close.
3. **P3: Clearing Account Rollforward** (`p3.py`) — Evaluates the actual General Ledger rollforward on clearing account `1310`:
   $$\text{Opening (0.00)} + \sum \text{debits}_{1310} - \sum \text{credits}_{1310} = 0.00$$
   Detects demo scenario mispostings ($4,812.50 residual) and wrong-account mispostings (e.g. crediting 7490).
4. **P4: Bank Tie-Out** (`p4.py`) — Confirms that every settled payout (`paid` or `completed`) matches exactly one bank deposit within a symmetric ±3-day window (`BANK_MATCH_DATE_WINDOW = timedelta(days=3)`), with bidirectional foreign key links.
5. **P5: Revenue Completeness** (`p5.py`) — Compares invoiced subtotal to credits on accounts `4010` and `4020` net of contra-revenue account `4900`. Sales tax (`2100`) and dispute fees (`6820`) are excluded from recognized revenue.
6. **P6: No Orphans Mapping Invariant** (`p6.py`) — Ensures every settlement event maps to its designated clearing line (`1310`) in journal entries, supporting multi-line split entries without false positives and catching unmapped or dangling records.

All monetary values are tracked using `Decimal` (`NUMERIC(18, 4)`) and serialized as strings in JSON/API payloads to eliminate floating-point imprecision.

## Verification & Quickstart

### Backend

```bash
# Install dependencies
uv sync --all-extras

# Run database migrations (supports PostgreSQL and SQLite)
uv run alembic upgrade head

# Run full test suite (101 unit + golden integration tests)
uv run pytest -v

# Run linting and type checking
uv run ruff check .
uv run pyright
```

### Frontend

```bash
cd frontend
npm install
npm run build
```
