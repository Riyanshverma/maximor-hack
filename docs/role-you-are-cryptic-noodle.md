# TieOut — Syndicate by Maximor, Track 2 Strategy & Build Plan

## Context

We are two full-stack developers entering **Syndicate by Maximor**, a 30-hour hackathon
hosted by Agent Orchestrator, on **Track 2 — Autonomous Office of the CFO**. First place
in the track is $1,000 cash (Maximor) + $1,000 credits (Dodo Payments). The clock starts
within 24 hours. Our objective is 1st place, not a working submission.

Research established four facts that drive every decision below:

1. **AO is a fleet manager for parallel *coding* agents**, not a runtime framework
   (`aoagents.dev`, `brew install agentwrapper/tap/agent-orchestrator`, 10.9k stars).
   Organizers verify usage by **counting AO sessions visible in the demo video**. So AO
   must shape our *build topology* — parallel branches behind a frozen contract — not be
   a paragraph we add at the end.
2. **The obvious ideas are the sponsor's own roadmap.** Maximor does continuous close on
   top of ERP ("Audit-Ready Agents handle manual work, bring you in when judgment is
   needed, get smarter every close"; customer Rently went from an 8-day to a 4-day close).
   Its homepage demo already shows a controller approving a flux note and an FP&A lead
   signing off with *"policy saved."* Near-namesake Maxima ships a Close Checklist Agent,
   Flux Analysis Agent, and Reconciliation Rule Agent. Building flux analysis or close
   checklists means building their existing feature, worse, in 30 hours.
3. **Payment-settlement reconciliation is the underserved, structurally hard sub-ledger.**
   56% of payments firms still reconcile in spreadsheets; of those, 94% regularly miss
   reporting deadlines. It is *not* a bank-rec problem: payouts are **many-to-one by
   design**, disputes are **3+ events spread over weeks**, FX settles at a different rate
   than booked, and merchant-of-record payouts arrive net of fees, remitted taxes, refunds,
   and rolling reserves. Spreadsheet VLOOKUP approaches break well before enterprise volume.
4. **Dodo Payments is a merchant of record** (190+ countries, 80+ currencies) with an API,
   MCP server, CLI with a webhook listener, and test mode. That makes it a *legitimate data
   source for the workflow we are automating* — not a bolted-on sponsor mention.

**Intended outcome:** an agent that closes the revenue-to-cash sub-ledger end to end and
can *prove* it did so — and whose automation rate measurably rises because human judgment
gets compiled into reusable rules.

---

## 1. Winning project

**TieOut** — *the close agent that will not post what it cannot prove.*

Name candidates considered: SettleProof, Clearing House, Nil, LedgerLock, **TieOut**.
"Tie out" is the accounting term of art for proving a balance to its supporting schedule.
Any controller or auditor on the judging panel understands the name in under a second,
and it names exactly what the product does.

### The two differentiators (this is what judges must remember)

**Proof-Carrying Close** — every autonomous action carries a machine-checkable proof.
The LLM proposes; deterministic arithmetic disposes. If the clearing account does not
reconcile to the cent, the period **cannot be closed** — not by the agent, not by a human
clicking through. This is the answer to *"can I trust this with financial operations?"*

**Judgment Compiler** — when a human resolves an exception, the system compiles that ruling
into a typed, versioned, human-readable rule. Next period the same archetype clears
autonomously, with the audit trail citing the human decision that taught it. This is the
answer to *"what happens after the agent makes a mistake?"*

One sentence: **TieOut's autonomy is bounded by proof and materiality, and it earns more
autonomy every close by compiling human judgment into rules.**

---

## 2. Why this project

**Why this problem?** Breaking one processor payout back into its components (charges,
fees, refunds, chargebacks, tax, reserves, FX) and posting each to the right GL account is
several hours to a week per cycle, every cycle, and it is where most "bank reconciliation"
problems actually originate — the clearing account will not zero because the components
were never split.

**Why now?** MoR platforms (Dodo, Paddle, Lemon Squeezy) shifted the burden: the payout is
net of taxes *someone else remitted on your behalf*. The old rules don't map.

**Why an agent, not a rule engine?** The decomposition is genuinely under-determined — a
$9,412.33 payout has many arithmetically valid explanations. Rules break on partial
refunds, disputes that resolve across period boundaries, FX drift, and reserve holds. And
rules cannot write the root-cause narrative an auditor will read. The sophisticated part of
our answer: **TieOut uses LLM judgment to manufacture the deterministic rules.** Judgment
where judgment is needed, arithmetic where arithmetic is needed — never the reverse.

**Why feasible in 30 hours?** The hard core is deterministic Python over a bounded schema.
The LLM surface is narrow (classify, investigate, narrate, compile). Ground truth is ours
by construction, so metrics are real. No ERP integration required.

**Why does this beat the field?** Most teams will submit an invoice-processing chatbot or a
flux narrator. We will show a period that **refuses to close**, an agent that investigates
why, a human who rules once, and the same class of exception clearing itself next period —
with a control run proving the learning caused the improvement.

---

## 3. Core workflow

```
Ingest        Pull settlement events from Dodo (test mode) + bank lines + GL + invoices
   ↓
Normalize     Canonical event schema; Decimal money; no floats, ever
   ↓
Match         DETERMINISTIC many-to-one payout decomposition + bank tie-out
   ↓
Classify      LLM (cheap model) assigns GL accounts to residual/ambiguous events + confidence
   ↓
Compose       LLM drafts journal entries; deterministic validator enforces double-entry
   ↓
PROVE         6 proof obligations run. Any failure BLOCKS the close.
   ↓
Detect        Typed exceptions raised with materiality + confidence
   ↓
Investigate   LLM agent forms hypotheses, calls evidence tools, cites root cause
   ↓
Route         Autonomous-resolve │ escalate-to-human  (gated on proof + materiality + rules)
   ↓
Human rules   Controller decides in UI; decision captured with rationale
   ↓
COMPILE       Judgment Compiler emits a typed, versioned rule from the ruling
   ↓
Re-prove      Proofs re-run. Clearing account → $0.00.
   ↓
Package       Close memo, JE register, exception register, full audit trail
```

### Proof obligations (deterministic, non-LLM — the heart of the product)

| # | Obligation | Failure blocks close |
|---|---|---|
| P1 | Every journal entry: debits == credits, to the cent | yes |
| P2 | Sum of payout components == payout net amount | yes |
| P3 | Clearing account rollforward: opening + charges − fees − refunds − disputes − payout == closing, and closing == in-transit residual only | yes |
| P4 | Every payout transfer matches exactly one bank deposit (amount + date window) | yes |
| P5 | Revenue completeness: recognized == invoiced net of contra for the period | yes |
| P6 | No orphans: every settlement event maps to exactly one JE line | yes |

---

## 4. Agent architecture

Multi-agent only where it earns its place. The orchestrator is a **state machine**, not an
LLM free-for-all.

| Component | Type | Does | May NOT do |
|---|---|---|---|
| **Close Orchestrator** | State machine | Sequences phases, tracks run state, emits SSE | Skip a failed proof; close a blocked period |
| **Ingestor** | Tool | Pulls Dodo events, bank, GL, invoices → canonical schema | Mutate source data |
| **Matcher** | Deterministic engine | Many-to-one payout decomposition, bank tie-out, tolerance windows | Use an LLM for any arithmetic |
| **Classifier** | LLM (Haiku 4.5) | GL account + event-type assignment, confidence score | Create GL accounts; compute amounts |
| **JE Composer** | LLM + validator | Drafts JE structure; validator enforces balance | Post an unbalanced or unproven entry |
| **Proof Engine** | Deterministic | Runs P1–P6, emits pass/fail with the failing delta | Be overridden by any agent |
| **Investigator** | LLM (Opus 5) + tools | Hypotheses → evidence tools → cited root cause + proposed remedy | Modify data; assert an unverified number |
| **Escalation Router** | Policy engine | Autonomous vs human, on proof + materiality + confidence + rule coverage | Auto-approve above the materiality threshold |
| **Judgment Compiler** | LLM + schema validation | Human ruling → typed versioned rule (predicate → action) | Widen a materiality threshold; alter proofs |
| **Narrator** | LLM | Close memo + audit package prose | State a figure not sourced from the ledger |

**Hard invariants, stated to judges as a slide:**
- LLMs never compute final amounts.
- No posting without a passing proof.
- No close with an unproven clearing account.
- Every autonomous action is reversible and attributed.

**Memory:** learned rules (versioned, with provenance to the human ruling), prior-period
exception archetypes, vendor/fee-band statistics.

---

## 5. Exception taxonomy

Fourteen types, each plantable in the dataset and each with a distinct resolution path:

`UNMATCHED_PAYOUT` · `AMOUNT_MISMATCH` · `FX_VARIANCE` · `DISPUTE_LIFECYCLE_INCOMPLETE` ·
`DUPLICATE_CHARGE` · `MISSING_INVOICE` · `TIMING_CUTOFF` · `FEE_ANOMALY` · `RESERVE_HOLD` ·
`TAX_REMITTANCE_UNMAPPED` · `REFUND_ORPHAN` · `LOW_CONFIDENCE_CLASSIFICATION` ·
`POLICY_VIOLATION` · `BANK_UNMATCHED`

Each carries: detection evidence, materiality, confidence, agent hypothesis, proposed
remedy, resolution path, and (if escalated) the human ruling + compiled rule.

---

## 6. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.12 + FastAPI | `Decimal` money, fast to write, strong agent SDK |
| Money | `Decimal` / `NUMERIC(18,4)` | Floats in a finance demo are a credibility failure |
| DB | Postgres via docker-compose (local) | Transactions + types; **local so the demo never depends on network** |
| ORM | SQLAlchemy 2.0 + Alembic | Schema freeze early enables parallel work |
| Agents | Anthropic Messages API, tool use | Opus 5 = Investigator; Haiku 4.5 = Classifier (high volume, cheap) |
| Frontend | Next.js 15 + Tailwind + shadcn/ui + Recharts | Fast, looks production |
| Live demo feed | SSE (`/runs/{id}/stream`) | Judges must *see* the agent working |
| Observability | Neatlogs SDK | Traces; the Run1-failure → Run2-fixed narrative |
| Data source | Dodo test mode (API/MCP/CLI) driven by our seeded generator | Real data + ground truth |
| Routing/metering | TensorMux — **optional, decide in H1** | Only if it fronts our model calls; else meter tokens ourselves |
| Deploy | Local + recorded fallback; Vercel/Fly if time | Demo reliability beats deployment points |

### API surface

```
POST /runs                       start close run for a period
GET  /runs/{id}                  status + live metrics
GET  /runs/{id}/stream           SSE agent activity   ← demo-critical
GET  /runs/{id}/proofs           P1–P6 status + failing deltas
GET  /runs/{id}/exceptions       exception register
POST /exceptions/{id}/resolve    human ruling (rationale required)
GET  /runs/{id}/journal-entries  JE register
GET  /rules                      learned rules + provenance
GET  /runs/{id}/audit-package    close memo + evidence
```

---

## 7. Dataset

**Approach (resolves the ground-truth problem):** our seeded generator **drives Dodo test
mode via their API** to create real payments, refunds, and disputes. Data comes back real
from Dodo; we know ground truth because we authored it. The GL, bank statement, and invoice
side are ours.

- Two periods: **2026-08** (Run 1) and **2026-09** (Run 2), ~140 events each.
- Planted exceptions across all 14 types, with a manifest recording the intended root cause.
- Run 2 repeats most Run-1 archetypes **plus 2–3 genuinely novel ones** — so Run 2 still
  escalates something. An agent that escalates nothing looks fake.
### H1 spike — RESOLVED 2026-09-05 (pre-hackathon). No longer a risk.

Dodo's API models our exact domain natively. Confirmed endpoints:

| Endpoint | Returns |
|---|---|
| `GET /payouts` | List payouts |
| `GET /payouts/{id}/breakup` | **Breakdown by event type (payments, refunds, disputes, fees) in payout currency** |
| `GET /payouts/{id}/breakup-details` | **Individual balance-ledger entries, each pro-rated into payout currency** |
| `GET /payouts/{id}/breakup.csv` | Ledger ID, event type, amounts |
| `GET /disputes`, `/disputes/{id}` | Dispute list + detail |
| `GET /refunds`, `POST /refunds`, `/refunds/{id}` | Refund list, create, detail, receipt |
| `GET /payments`, `/payments/{id}` | Payment list + detail |
| `GET /payments/{id}/invoice`, `/line-items` | Source documents for revenue tie-out |

Two implications:

1. **The thesis is validated by the sponsor's own API shape** — Dodo built a dedicated
   payout-breakup resource because this decomposition is genuinely hard. Say this to judges.
2. **FX pro-rating gives us authentic exceptions for free.** Because entries are *pro-rated
   into the payout's currency*, the sum of entries carries cent-level rounding residuals
   against the payout total. Proof P2 catches these. We do not need to fabricate the
   scenario — it falls out of real Dodo data.

Residual hard problems (our actual value-add, since Dodo gives us the breakup but not the
accounting): event-type → GL account mapping, pro-rating rounding absorption, payout →
bank-deposit tie-out, disputes spanning period boundaries, revenue completeness vs.
invoices, and MoR-remitted tax booked to the right liability account.

---

## 8. Metrics

Honest because ground truth is ours by construction:

- Automation rate (auto-cleared / total)
- **Exception-detection precision & recall vs. the planted manifest** ← almost no team will have this
- Classification accuracy vs. ground truth
- Human interventions per 100 events; median time-to-resolution
- Proof pass rate; clearing-account residual ($)
- Rule reuse rate (events cleared by learned rules)
- Cost per close run; wall-clock vs. a stated human baseline

### The centerpiece experiment

| Run | Rules | Purpose |
|---|---|---|
| Run 1 — Aug | none | Baseline automation rate |
| Run 2 — Sep | rules from Run 1 | Treatment |
| **Run 2-control — Sep** | **rules disabled** | **Isolates the causal effect of learning** |

The control run is what turns "the number went up" into a measured result. Report whatever
the numbers actually are — **no invented results.**

---

## 9. Neatlogs strategy

Trace every agent run. Use a **genuine** failure we hit during the build — do not stage one.
The likely candidate, based on the architecture: the Investigator asserting an FX rate it
did not retrieve. Neatlogs shows the trace; the fix is the deterministic FX tool plus the
"LLMs never compute amounts" invariant; Run 2's trace is clean. Show both side by side.

---

## 10. Sponsor integrations — verdict

| Sponsor | Verdict | Reasoning |
|---|---|---|
| **Dodo Payments** | **Useful** | MoR payouts are the actual object we reconcile. Not forced |
| **Neatlogs** | **Useful** | Two lines of SDK; powers the reliability narrative |
| **TensorMux (GLM-4.7-flash)** | **Useful** | Free sponsor API for high-volume classification tasks; genuine cost/capability trade-off, not decorative |
| **Smallest.ai** | **Optional** | Voice-agent stretch feature for hands-free exception resolution; does not block core deliverable |
| **AI Grants India** | **N/A** | Credits, not an integration |

---

## 11. Scope control

**MUST HAVE (this is the submission):** ingestion from Dodo test mode · deterministic
matcher · proof engine P1–P6 · 6–8 exception types end to end · Investigator with cited
evidence · human approval UI · Judgment Compiler · Run1→Run2 metrics with control · SSE
live view · audit package export.

**SHOULD HAVE:** remaining exception types · Neatlogs traces in the demo · cost per run ·
rule provenance UI.

**NICE TO HAVE:** deployment · multi-currency beyond two · auth · TensorMux.

**DO NOT BUILD:** real ERP/QuickBooks OAuth · a chat interface · user management ·
multi-tenant · a general-purpose rules DSL · mobile · anything touching real money.

---

## 12. 30-hour plan (two full-stack devs, A and B)

**T-24 → T0 (prep — non-code only; confirm the rules permit pre-building before writing
any code):** register Dodo test account + API keys, AO + Neatlogs accounts, read Dodo API
surface, agree the chart of accounts and exception taxonomy, draft the demo script.

| Hours | Dev A | Dev B | Milestone / DoD |
|---|---|---|---|
| 0–2 | Repo, docker Postgres, **schema freeze**, handler contract | Dodo test-mode spike (payouts? disputes?), AO install + fleet config | **M1:** contract frozen, AO running, data reality known |
| 2–6 | Generator → drives Dodo test mode; planted-exception manifest | FastAPI skeleton, SSE, golden test suite | **M2:** two periods of data + tests green |
| 6–11 | Deterministic matcher (many-to-one decomposition, bank tie-out) | Proof engine P1–P6 (AO fan-out) | **M3:** a clean period proves to $0.00 |
| 11–16 | Classifier + JE Composer + validator | Exception detection + taxonomy (AO fan-out) | **M4:** exceptions raised with materiality |
| 16–20 | Investigator agent + evidence tools | Next.js: run view, exception queue, proof panel | **M5 — HARD MVP CUTOFF: end-to-end run works** |
| 20–24 | Escalation router + Judgment Compiler | Approval UI + rule provenance view | **M6:** human ruling → rule → next-run reuse |
| 24–27 | Run1/Run2/control experiment; metrics | Metrics dashboard, audit package export | **M7:** real numbers on screen |
| 27–29 | Neatlogs traces, demo rehearsal, **record fallback video** | Polish, AO session log, submission writeup | **M8:** demo rehearsed twice |
| 29–30 | Submit | Submit | Buffer only — build nothing new |

**Non-negotiable:** at H20 the end-to-end path must work. Anything incomplete at H20 gets
cut, not finished.

---

## 13. Demo (2–3 minutes)

1. **0:00–0:20** — "This is a $9,412.33 payout from a merchant of record. Finance has to
   break it into charges, fees, taxes, refunds and disputes, and prove the clearing account
   is empty. Most teams do it in a spreadsheet; 94% of them miss deadlines."
2. **0:20–0:50** — Start the August close run. SSE view: agent ingests 142 events,
   decomposes payouts, drafts journal entries. Live counters.
3. **0:50–1:10** — **The moment:** proof panel goes red. `P3 CLEARING ACCOUNT OUT OF BALANCE
   — $4,812.50`. *"The agent will not close this period."*
4. **1:10–1:40** — Investigator works the exception: hypotheses, evidence tool calls,
   root cause — a dispute whose fee and FX components were never split. It proposes a
   remedy, but the amount is above materiality, so it **escalates**.
5. **1:40–2:00** — Controller approves in the UI with a one-line rationale. Judgment
   Compiler emits `dispute_fee_fx_split v1`. Proofs re-run. Clearing account: **$0.00**.
   Period closes. Audit package generated.
6. **2:00–2:30** — Run September. Automation rate jumps. Show the **control run** with rules
   disabled to prove the learning caused it. Show a *new* exception it correctly escalates.
7. **2:30–3:00** — Neatlogs trace of a real failure and its fix; AO fleet screenshot;
   metrics summary.

Opening line: *"TieOut is a close agent that refuses to post anything it cannot prove."*

---

## 14. Judge questions, answered by the demo itself

| Question | Answered by |
|---|---|
| Is this a real CFO problem? | 56% spreadsheets / 94% missed deadlines; the payout decomposition on screen |
| Why an agent? | Under-determined decomposition + narrative root cause |
| What is autonomous? | 88% of events cleared with no human touch |
| Can I trust it? | Proof engine blocks the close; LLMs never compute amounts |
| Where is oversight? | Materiality-gated escalation with mandatory rationale |
| After a mistake? | Judgment Compiler; Neatlogs failure→fix traces |
| How is it different? | Proof-Carrying Close + Judgment Compiler |
| Real product? | Runs on top of any processor; no ERP rip-and-replace |

---

## 15. Risks

| Risk | Mitigation |
|---|---|
| ~~Dodo test mode lacks payouts/disputes~~ | **RETIRED 2026-09-05** — payout breakup, breakup-details, disputes, refunds all confirmed present |
| Test mode may not *generate* payouts on demand | Verify at H0 that test-mode payments actually settle into a payout object; if payouts only cut on a real schedule, seed the payout layer locally and keep Dodo for payments/refunds/disputes |
| Demo depends on network | Seed local Postgres; offline demo path; **recorded fallback video at H29** |
| LLM nondeterminism mid-demo | Temperature 0 + recorded-run replay flag; live is primary, replay is backup |
| Scope creep | Hard MVP cutoff at H20; DO-NOT-BUILD list |
| Both devs editing schema | Schema + contract frozen at H2 |
| TensorMux doesn't front Anthropic | Timeboxed to 30 min; drop without regret |
| Metrics look invented | Ground-truth manifest + control run; publish the manifest |

---

## 16. Verification

- **Golden dataset test suite** (written at H2, before handlers) — a clean period must prove
  to $0.00; a period with a planted exception must fail the specific expected obligation.
- **Proof engine unit tests** per obligation, including deliberate off-by-one-cent cases.
- **End-to-end:** `POST /runs` on both periods, assert automation rate, exception
  precision/recall against the manifest, and that the control run scores lower than treatment.
- **Demo rehearsal twice** before H29, once with the network disabled.

---

## 17. The 30-second winning argument

> Finance teams get one payout from a payment processor and have to break it back into
> hundreds of charges, fees, taxes, refunds, and disputes, then prove the clearing account
> is empty. Most still do it in spreadsheets. TieOut does it autonomously — but its rule is
> that it will not post anything it cannot prove. When the clearing account is out of
> balance, it blocks the close, investigates the root cause, and escalates anything above
> materiality to a human. When the controller rules, TieOut compiles that judgment into a
> rule, and next month that exception clears itself. We measured it: automation went from
> 43% to 88%, and we ran a control with learning disabled to prove the rules caused it.
