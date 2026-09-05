# TieOut — Data Model & Interface Contracts

Design artifact. Written pre-T+0. No executable code.

**This document is the contract that gets frozen at M1 (H2).** Once frozen, AO agents work
on separate branches against it without coordinating. Changing it after H2 requires both
devs to agree and costs a merge storm — treat it as expensive on purpose.

## Money rule (non-negotiable)

All monetary values: Python `Decimal`, Postgres `NUMERIC(18,4)`. **No floats anywhere, at
any layer, including JSON serialization** — serialize as string. A float in a finance demo
is a credibility failure a judge will spot instantly.

Currency is always explicit. No implicit USD. Every monetary column is paired with a
`currency CHAR(3)` and, where converted, an `fx_rate NUMERIC(18,8)` plus `fx_source`.

---

## Schema

```
close_run
  id, period (e.g. '2026-08'), status, started_at, finished_at,
  rules_enabled BOOL,          -- false for the control run
  seed INT,                    -- reproducibility
  metrics JSONB

settlement_event               -- canonical form of a Dodo breakup-details entry
  id, run_id, source ('dodo'|'seed'), external_id,
  event_type,                  -- payment|refund|processing_fee|platform_fee|dispute_*|
                               -- tax_remitted|reserve_*|fx_adjustment|payout
  payout_id, order_id, customer_id, occurred_at,
  amount_native NUMERIC(18,4), currency_native CHAR(3),
  amount_payout NUMERIC(18,4), currency_payout CHAR(3),   -- Dodo's pro-rated value
  fx_rate NUMERIC(18,8), fx_source,
  raw JSONB                    -- always keep the untouched API payload for audit

payout
  id, run_id, external_id, status, created_at, settled_at,
  gross NUMERIC(18,4), fees NUMERIC(18,4), net NUMERIC(18,4), currency,
  bank_line_id NULL

bank_line
  id, run_id, posted_at, amount NUMERIC(18,4), currency, description, matched_payout_id NULL

invoice
  id, run_id, external_id, customer_id, issued_at,
  subtotal, tax, total, currency, line_items JSONB

gl_account
  code, name, type, normal_side, is_restricted BOOL

journal_entry
  id, run_id, period, memo, posted_at, status ('draft'|'posted'|'reversed'),
  source_exception_id NULL, created_by ('agent'|'human'|'rule'), rule_id NULL

journal_line
  id, entry_id, account_code, debit NUMERIC(18,4), credit NUMERIC(18,4),
  currency, settlement_event_id NULL
  -- CHECK: exactly one of debit/credit is non-zero

exception
  id, run_id, type,             -- the 14 from 02-exception-taxonomy.md
  severity, status ('open'|'auto_resolved'|'escalated'|'human_resolved'),
  amount NUMERIC(18,4), currency, confidence NUMERIC(4,3),
  evidence JSONB, hypotheses JSONB, proposed_remedy JSONB,
  detected_by, matched_rule_id NULL,
  ground_truth_key NULL         -- links to the planted manifest; metrics only, never read by agents

human_ruling
  id, exception_id, decision, rationale TEXT NOT NULL, decided_by, decided_at

rule
  id, name, version INT, predicate JSONB, action JSONB,
  rationale TEXT,               -- human-readable, shown in the UI
  source_ruling_id,             -- provenance: which human decision taught this
  active BOOL, times_applied INT

proof_result
  id, run_id, obligation ('P1'..'P6'), passed BOOL,
  expected NUMERIC(18,4), actual NUMERIC(18,4), delta NUMERIC(18,4),
  detail JSONB, evaluated_at

audit_event                     -- append-only; never updated or deleted
  id, run_id, actor ('agent'|'human'|'rule'|'system'), action,
  subject_type, subject_id, payload JSONB, at
```

**`ground_truth_key` is write-once by the generator and readable only by the metrics
module.** No agent, prompt, or tool may query it. State this to judges — it is the
difference between a measurement and a demo.

---

## Handler contract (the AO fan-out boundary)

```python
class ExceptionHandler(Protocol):
    type: str                    # e.g. "FX_VARIANCE"
    build_priority: int          # 1=MVP, 2=should, 3=nice

    def detect(self, ctx: RunContext) -> list[ExceptionDraft]: ...
    def gather(self, exc: Exception, ctx: RunContext) -> Evidence: ...
    def hypothesize(self, exc: Exception, ev: Evidence) -> list[Hypothesis]: ...
    def propose(self, exc: Exception, h: Hypothesis) -> Remedy | None: ...
    def compile_rule(self, exc: Exception, ruling: HumanRuling) -> RuleDraft | None: ...
```

Rules for anyone (human or agent) implementing a handler:

- `detect` and `gather` are **deterministic** — no LLM calls.
- `propose` may use an LLM for *structure* but every amount must come from a tool result.
- Handlers **never** decide autonomy. `route` lives in the policy engine, not the handler.
- Handlers **never** write to `journal_entry` directly; they return a `Remedy`.
- Each handler ships with fixtures: one triggering case, one near-miss that must *not* trigger.

## Proof engine contract

```python
class ProofObligation(Protocol):
    id: str                      # "P1".."P6"
    blocking: bool               # all six are True
    def evaluate(self, ctx: RunContext) -> ProofResult: ...
```

Pure functions over committed data. No LLM. No network. Must be runnable standalone against
a database snapshot — that property is what makes them trustworthy and independently testable.

## Policy engine

```python
def route(exc, remedy, proofs, rules) -> Literal["AUTO", "ESCALATE"]
```

Returns `AUTO` only if **all** hold, else `ESCALATE`:

1. every blocking proof passes after applying the remedy
2. `abs(exc.amount) < 250.00`
3. `exc.confidence >= 0.85`
4. a matching active rule or known archetype exists
5. the remedy touches no `is_restricted` account
6. rounding cap not breached

Deliberately a conjunction, deliberately boring, deliberately not an LLM.

---

## API contract

Money is serialized as **string**, never number.

```
POST   /runs                      {period, rules_enabled, seed} -> {run_id}
GET    /runs/{id}                 status + metrics
GET    /runs/{id}/stream          SSE: {phase, message, counters, exception_id?}
GET    /runs/{id}/proofs          [{obligation, passed, expected, actual, delta}]
GET    /runs/{id}/exceptions      ?status= filter
GET    /exceptions/{id}           full evidence + hypotheses + proposed remedy
POST   /exceptions/{id}/resolve   {decision, rationale}  -- rationale REQUIRED, non-empty
GET    /runs/{id}/journal-entries
GET    /rules                     + ?run_id= for which fired
GET    /runs/{id}/audit-package   memo + evidence bundle
GET    /runs/{id}/metrics         the scorecard
```

`POST /exceptions/{id}/resolve` **must reject an empty rationale with 422.** The rationale
is the training signal for the Judgment Compiler; an unexplained approval teaches nothing.

## SSE event shape

```json
{"phase":"investigate","message":"Hypothesis 2 of 3: dispute fee booked to clearing, never split",
 "counters":{"processed":118,"auto":97,"escalated":4},"exception_id":"exc_0031"}
```

Phases: `ingest → normalize → match → classify → compose → prove → detect → investigate →
route → await_human → reprove → package`.

---

## Module layout (AO branch boundaries)

Each row is one branch, one agent, one merge.

| Module | Owner | Depends on |
|---|---|---|
| `db/` schema + migrations | Dev A | — |
| `ingest/dodo.py` | Dev A | schema |
| `ingest/generator.py` + manifest | Dev A | schema |
| `engine/matcher.py` | Dev A | schema |
| `engine/proofs/p1..p6.py` | **AO fan-out** | schema |
| `engine/handlers/*.py` (14) | **AO fan-out** | handler contract |
| `engine/policy.py` | Dev B | contract |
| `agents/classifier.py` | Dev A | schema |
| `agents/investigator.py` | Dev A | handler contract |
| `agents/compiler.py` | Dev B | rule schema |
| `api/` FastAPI + SSE | Dev B | schema |
| `web/` Next.js | **AO fan-out** by view | API contract |
| `metrics/` scorecard | Dev B | manifest |

The two fan-out rows are the AO story: 6 proofs + 14 handlers + ~5 views = **25 independent
components behind three frozen interfaces.** That is a real reason to run a fleet, and it is
what we tell the judges.

## Test gate

Nothing merges without the golden-dataset suite green:

- a clean period proves to $0.00 on all six obligations
- each planted exception fails its specific expected obligation and no other
- each handler's near-miss fixture does not trigger
- no float appears in any serialized response (assert on type)
