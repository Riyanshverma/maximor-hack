# TieOut — Exception Taxonomy

Design artifact. Written pre-T+0. No executable code.

Fourteen types. Each is independently implementable behind the handler contract in
`03-data-model-and-contracts.md`, which is what makes them safe to fan out to parallel AO
agents.

## Handler shape (every type implements this)

```
detect(run_ctx)      -> list[Exception]      deterministic; no LLM
gather(exception)    -> Evidence             deterministic tool calls
hypothesize(ev)      -> list[Hypothesis]     LLM (Investigator)
propose(hypothesis)  -> Remedy | None        LLM proposes structure, validator checks math
route(remedy)        -> AUTO | ESCALATE      policy engine; never the LLM
compile(ruling)      -> Rule | None          Judgment Compiler, on human ruling only
```

Autonomy is granted only when **all four** hold: a passing proof after the remedy,
|amount| < $250, classifier confidence ≥ 0.85, and a matching rule or known archetype.
Any one failing → escalate. This conjunction is the product.

---

## The fourteen

### 1. `AMOUNT_MISMATCH`
Sum of `breakup-details` entries ≠ payout net amount.
**Detect:** `abs(Σ entries − payout.net) > 0`. **Evidence:** entry list, payout header, per-entry FX rate.
**Auto if:** delta ≤ $1.00 and attributable to pro-rating → post to 7490 within cap.
**Escalate if:** delta > $1.00, or cap already consumed. **Rule shape:** none (structural).

### 2. `FX_VARIANCE`
Settlement FX rate differs from the rate booked at invoice.
**Detect:** `abs(rate_settled − rate_booked)/rate_booked > 0.005`. **Evidence:** both rates, source invoice, entry.
**Auto if:** variance < $250 → post 7410. **Escalate if:** ≥ $250 or rate source ambiguous.
**Rule shape:** `fx_variance_threshold(currency, band) → post 7410`.
> This is the exception most likely to expose an LLM computing its own FX rate. The
> deterministic FX tool is mandatory; see the Neatlogs narrative in the plan.

### 3. `DISPUTE_LIFECYCLE_INCOMPLETE`
Dispute opened in period, unresolved at period end.
**Detect:** `dispute.status ∈ {opened, under_review}` and `opened_at` in period.
**Evidence:** dispute timeline, original charge, fee entries.
**Auto if:** never — an open dispute is a judgment call on loss provisioning.
**Escalate:** always, with a proposed provision. **Rule shape:** `dispute_provision_policy(status, age_days) → provision %`.

### 4. `DUPLICATE_CHARGE`
Same order/invoice ID settled twice.
**Detect:** `group_by(order_id) having count(payment) > 1` within a 30-day window.
**Evidence:** both payments, customer, invoice, timestamps.
**Auto if:** never — a duplicate is either a refund obligation or a legitimate re-purchase.
**Escalate:** always. **Rule shape:** `duplicate_window(product_type, days) → legitimate | duplicate`.

### 5. `MISSING_INVOICE`
Settled payment with no source document.
**Detect:** payment present, `GET /payments/{id}/invoice` empty or unlinked in GL.
**Evidence:** payment, customer, line items, product.
**Auto if:** line items resolve the product and amount matches a price book entry.
**Escalate if:** amount is non-standard. **Rule shape:** `synthesize_invoice(product_id) → revenue account`.

### 6. `TIMING_CUTOFF`
Payout spans the period boundary.
**Detect:** `payout.created_at` and `payout.settled_at` fall in different periods.
**Evidence:** payout dates, bank deposit date, constituent entries.
**Auto if:** always resolvable — split via 1330 In-Transit; the accrual is mechanical.
**Escalate if:** the split would move material revenue across the boundary.
**Rule shape:** `cutoff_policy(days_tolerance) → in-transit split`.

### 7. `FEE_ANOMALY`
Effective fee rate outside the expected band.
**Detect:** `fee / gross` outside [historical mean ± 3σ] or outside contractual band.
**Evidence:** fee entries, gross, historical rate distribution, payment method, country.
**Auto if:** explainable by method/geography mix (e.g. an expensive local method).
**Escalate if:** unexplained. **Rule shape:** `fee_band(method, country) → expected range`.

### 8. `RESERVE_HOLD`
MoR withheld a rolling reserve without an obvious basis.
**Detect:** `reserve_held` entry present with no matching prior release schedule.
**Evidence:** reserve entries, historical reserve %, payout volume.
**Auto if:** matches the established reserve percentage → post 1320.
**Escalate if:** percentage changed. **Rule shape:** `reserve_rate(pct, effective_from) → post 1320`.

### 9. `TAX_REMITTANCE_UNMAPPED`
MoR-remitted tax with no mapped liability account.
**Detect:** `tax_remitted` entry whose jurisdiction is absent from the tax map.
**Evidence:** entry, jurisdiction, customer country, tax rate.
**Auto if:** jurisdiction already in map. **Escalate if:** new jurisdiction — this is a nexus question.
**Rule shape:** `tax_jurisdiction_map(country) → 2100 sub-account`.

### 10. `REFUND_ORPHAN`
Refund whose original charge is not in scope.
**Detect:** refund with `payment_id` not present in the current or prior loaded period.
**Evidence:** refund, referenced payment ID, prior-period lookup.
**Auto if:** original charge found in a prior closed period → post to 4900 with a cross-period note.
**Escalate if:** original charge not found anywhere. **Rule shape:** `orphan_lookback(months) → resolve | escalate`.

### 11. `BANK_UNMATCHED`
Payout with no corresponding bank deposit.
**Detect:** `payout.status = paid` and no bank line within `amount ± $0.00`, `date ± 3 days`.
**Evidence:** payout, candidate bank lines, date window.
**Auto if:** a unique candidate exists inside the window with an exact amount.
**Escalate if:** zero or multiple candidates. **Rule shape:** `bank_match_window(days) → match tolerance`.
> Amount tolerance is deliberately **zero**. A payout either matches the deposit to the
> cent or it does not. Fuzzy amount matching is how reconciliation tools lose credibility.

### 12. `LOW_CONFIDENCE_CLASSIFICATION`
Classifier below threshold on GL account assignment.
**Detect:** `confidence < 0.85`. **Evidence:** entry, top-3 candidate accounts with scores, similar prior entries.
**Auto if:** never — that is what the threshold means.
**Escalate:** always. **Rule shape:** `classification_precedent(event_signature) → account`.

### 13. `POLICY_VIOLATION`
A proposed entry breaches a control.
**Detect:** rounding cap breached, restricted account touched, or a single entry > period aggregate trigger.
**Evidence:** proposed entry, violated rule, cap consumption to date.
**Auto if:** **never, under any circumstance.** Blocks the close.
**Escalate:** always, flagged critical. **Rule shape:** none — policy is not learnable by the agent.

### 14. `UNMATCHED_PAYOUT`
Payout that cannot be decomposed at all.
**Detect:** `breakup-details` returns empty or unparseable for a payout with non-zero net.
**Evidence:** payout header, raw API response, CSV fallback.
**Auto if:** CSV fallback parses successfully.
**Escalate if:** both endpoints fail. **Rule shape:** none (infrastructure).

---

## Coverage map for the demo

| Demo beat | Types exercised |
|---|---|
| Clean auto-clearing | 1 (sub-cent), 6, 8, 10 |
| The blocking moment | 3 + 2 combined — dispute whose fee and FX were never split |
| Escalation | 3, 4, 12 |
| Learning payoff in Run 2 | 2, 7, 9 (rules compiled from Run 1) |
| Correctly still escalates | 13 and one novel archetype |

**Run 2 must still escalate something.** An agent that escalates nothing reads as staged,
and a judge who suspects staging discounts everything else on screen.

## Build priority

Ship in this order; cut from the bottom if the schedule slips.

1. **Must (MVP):** 1, 2, 3, 6, 11, 12, 13 — these carry every demo beat
2. **Should:** 4, 5, 7, 9
3. **Nice:** 8, 10, 14
