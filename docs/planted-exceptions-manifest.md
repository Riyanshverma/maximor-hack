# TieOut — Planted Exceptions Manifest

**Generated:** Phase 2 test data generation  
**Seed:** 42 (deterministic, reproducible)

This manifest documents every exception intentionally planted into the August and September test datasets. It serves as ground truth for metrics validation — the `ground_truth_key` field is write-once and readable only by the metrics endpoint.

---

## August 2026 — Run 1 (Baseline: Many Manual Interventions Expected)

### 1. AMOUNT_MISMATCH (August)

**Ground truth key:** `gt_AMOUNT_MISMATCH_2026-08`

**Payout:** po_xxxxx (gross $1,000.00, fees $50.00, net $950.00)

**Settlement events:**
- payment: $500.01
- payment: $250.00
- payment: $200.00
- **Sum:** $950.01 (exceeds net by $0.01)

**Expected resolution:** Auto-resolve to rounding account 7490

**Rationale:** Sub-cent mismatch from pro-rating. Within $1.00 cap. Should post to 7490.

---

### 2. FX_VARIANCE (August)

**Ground truth key:** `gt_FX_VARIANCE_2026-08`

**Payout:** po_yyyyy (gross $2,000.00, fees $100.00, net $1,900.00)

**Settlement event:**
- payment: $1,900.00 native, settled at FX 1.08 (vs. booked FX 1.05)

**Impact:** $(1,900 × 0.08) / 1.05 = ~$145 variance (hypothetical invoice booking)

**Expected resolution:** Escalate (exceeds $250 threshold? or requires investigation)

**Rationale:** FX rate variance detected. Deterministic FX tool mandatory; no LLM computes rates.

---

### 3. BANK_UNMATCHED (August)

**Ground truth key:** `gt_BANK_UNMATCHED_2026-08`

**Payout:** po_zzzz (gross $1,500.00, fees $75.00, net $1,425.00)

**Settlement event:**
- payment: $1,425.00

**Bank deposit:** None (deliberately omitted within 3-day window)

**Expected resolution:** Escalate (no matching deposit)

**Rationale:** Payout marked completed, but no bank line found. Blocks reconciliation.

---

## September 2026 — Run 2 (Treatment: Learned Rules Applied)

### 4. DISPUTE_LIFECYCLE_INCOMPLETE (September)

**Ground truth key:** `gt_DISPUTE_LIFECYCLE_INCOMPLETE_2026-09`

**Payout:** po_aaaa (gross $5,000.00, fees $200.00, net $4,800.00)

**Settlement events:**
- payment: $4,900.00
- dispute_opened: -$100.00 (status: open at period end)

**Expected resolution:** Escalate (always for open disputes)

**Rationale:** Dispute opened on 2026-09-15, unresolved. Requires loss provision decision.

---

### 5. FEE_ANOMALY (September)

**Ground truth key:** `gt_FEE_ANOMALY_2026-09`

**Payout:** po_bbbb (gross $10,000.00, fees $600.00, net $9,400.00)

**Effective fee rate:** 6% (gross basis) — outside 2–4% historical band

**Settlement events:**
- payment: $9,400.00
- processing_fee: -$300.00
- platform_fee: -$300.00

**Expected resolution:** Escalate (unexplained anomaly)

**Rationale:** Fee band breach. No known country/method mismatch explains it.

---

### 6. TIMING_CUTOFF (September)

**Ground truth key:** `gt_TIMING_CUTOFF_2026-09`

**Payout:** po_cccc (created 2026-09-28, settled 2026-10-01)

**Settlement event:**
- payment: $2,900.00

**Expected resolution:** Auto-resolve via 1330 In-Transit split

**Rationale:** Payout spans period boundary. Split is mechanical; no material revenue shift.

---

### 7. LOW_CONFIDENCE_CLASSIFICATION (September)

**Ground truth key:** `gt_LOW_CONFIDENCE_CLASSIFICATION_2026-09`

**Payout:** po_dddd (gross $800.00, fees $40.00, net $760.00)

**Settlement event:**
- payment: $760.00 (GL account confidence: 0.72, below 0.85 threshold)

**Expected resolution:** Escalate (always for low confidence)

**Rationale:** Classifier output below confidence threshold. Requires human precedent or decision.

---

## Summary

| Exception Type | August | September | Total | Auto | Escalate |
|---|:---:|:---:|:---:|:---:|:---:|
| AMOUNT_MISMATCH | ✓ | | 1 | 1 | 0 |
| FX_VARIANCE | ✓ | | 1 | 0 | 1 |
| BANK_UNMATCHED | ✓ | | 1 | 0 | 1 |
| DISPUTE_LIFECYCLE_INCOMPLETE | | ✓ | 1 | 0 | 1 |
| FEE_ANOMALY | | ✓ | 1 | 0 | 1 |
| TIMING_CUTOFF | | ✓ | 1 | 1 | 0 |
| LOW_CONFIDENCE_CLASSIFICATION | | ✓ | 1 | 0 | 1 |
| **Totals** | **3** | **4** | **7** | **2** | **5** |

---

## Metrics Validation

The metrics endpoint (`GET /runs/{id}/metrics`) will compute:
- **Automation rate:** (auto-resolved + matching rules) / total
- **Precision:** correctly detected / detected
- **Recall:** correctly detected / planted

For Run 1 (Aug): baseline, many escalations expected (handlers being built)  
For Run 2 (Sep, treatment): learned rules from Aug should reduce escalations  
For Run 2 (Sep, control): rules disabled — should still escalate at least on HIGH violations

**Key invariant:** `exception.ground_truth_key` is write-once by generator, read only by metrics — agents never see it.
