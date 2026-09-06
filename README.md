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
