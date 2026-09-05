# TieOut — Demo Script

Design artifact. Written pre-T+0. No executable code.

Target: **2:45**. Hard ceiling 3:00. Every UI decision in the build serves a beat below; if
a screen doesn't appear here, it is not MVP.

## The one-sentence open

> "TieOut is a close agent that refuses to post anything it cannot prove."

Say it before anything is on screen. It is the sentence we want repeated in the judges' room.

---

## Beat sheet

### 0:00–0:18 — The problem, shown not told
On screen: a single Dodo payout, `$9,412.33`, next to a 40-row breakup table.

> "This is one payout from a merchant of record. Before finance can close, someone has to
> break it back into charges, fees, remitted taxes, refunds and disputes, post each to the
> right account, and prove the clearing account is empty. 56% of payments teams still do
> this in a spreadsheet. 94% of them miss deadlines."

### 0:18–0:48 — The agent runs
Click **Close August**. SSE feed streams live. Counters climb.

> "It pulls the settlement events from Dodo, decomposes the payouts, and drafts the journal
> entries. No arithmetic here is done by a language model — the model classifies and
> explains, the engine computes."

Land on: `142 events · 61 auto-cleared · 12 exceptions`.

### 0:48–1:12 — **The moment.** The close is refused.
Proof panel turns red:

```
P3  CLEARING ACCOUNT ROLLFORWARD        FAILED
    expected  0.00        actual  4,812.50        delta  4,812.50
```

> "It will not close the period. Six proof obligations run on every close, and a failure
> blocks it — not a warning, a block. This is the difference between an agent you can trust
> with the ledger and one you can't."

*Pause here. This is the beat that wins the room. Do not rush it.*

### 1:12–1:42 — Autonomous investigation
Open the exception. Show hypotheses forming, evidence tool calls resolving, root cause landing.

```
EXC-0031  DISPUTE_LIFECYCLE_INCOMPLETE + FX_VARIANCE
  H1  duplicate charge                     ruled out — order IDs distinct
  H2  fee/FX components never split        CONFIRMED
  evidence  dispute DSP_9931 · fee 6820 $15.00 · FX 7410 $37.50 · charge PAY_4471
  proposed  split entry, 3 lines
  amount    $4,812.50  >  materiality $250.00   ->  ESCALATE
```

> "It found the cause: a dispute whose fee and FX components were never split out. It knows
> the fix. It escalates anyway — because $4,812.50 is above materiality. Autonomy is bounded
> by materiality, not by how confident the model feels."

### 1:42–2:05 — Human rules once, and it is compiled
Controller approves with a one-line rationale. Then:

```
RULE COMPILED   dispute_fee_fx_split  v1
  from ruling by Controller · "split dispute fee to 6820, FX to 7410"
  predicate  event_type=dispute_* AND fee_component IS NOT NULL
```

Proofs re-run. `P3 PASSED · clearing account $0.00`. Period closes. Audit package generates.

> "The controller ruled once. That judgment is now a versioned rule with provenance back to
> the person who made it."

### 2:05–2:32 — The payoff, with a control
Run September. Then show three bars side by side:

```
Run 1  August      no rules            automation  __%
Run 2  September   rules from Run 1    automation  __%
Run 2  September   rules DISABLED      automation  __%   <- control
```

> "September's automation rate went up. But a number going up proves nothing on its own — so
> we ran September again with learning switched off. The gap between those two bars is the
> measured effect of the rules. And it still escalated two things it had never seen."

*(Fill the blanks with real measured numbers. If the gap is small, say so — a small honest
gap beats a large invented one, and judges test for this.)*

### 2:32–2:45 — Proof of engineering
Three fast cards: Neatlogs trace of a real failure and its fix · AO fleet screenshot with
session count · metrics scorecard.

> "We hit a real bug: the investigator asserted an FX rate it never retrieved. Here's the
> trace, here's the fix — a deterministic FX tool and a rule that models never compute
> amounts. And we built 25 independent components in 30 hours by freezing three interfaces
> in hour two and running an AO fleet across separate branches."

---

## Rules for the recording

- **Record the fallback at H29**, before anything else in the final hour. A live demo that
  fails with no fallback is a lost hackathon.
- Run the whole thing **once with the network off** during rehearsal. Local Postgres is
  seeded precisely so this works.
- Temperature 0 everywhere. Replay flag ready.
- Never say a number that isn't on screen.
- Do not narrate the architecture. Judges infer competence from the blocked close and the
  control run, not from a box diagram.

## The three questions to have answers ready for

1. *"Couldn't a rules engine do this?"* → The decomposition is under-determined; a $9,412.33
   payout has many arithmetically valid explanations. We use judgment to *manufacture* the
   deterministic rules — that's the Judgment Compiler.
2. *"How do I know the metrics are real?"* → The generator plants exceptions with a
   ground-truth manifest, stored in a column no agent or prompt can read. We report
   precision and recall against it, and we publish the manifest.
3. *"What stops it hiding an imbalance?"* → The rounding account is capped at $1 per payout
   and $25 per period, enforced deterministically. A breach is a policy violation that
   blocks the close and is never auto-resolved.
