# TieOut — Chart of Accounts & Posting Map

Design artifact. Written pre-T+0. No executable code.

Scope: a SaaS company selling through a merchant of record (Dodo). Deliberately small —
17 accounts is enough to model every settlement event and no more. Resist adding accounts
during the build; every new account multiplies classifier error surface.

## Accounts

| Code | Account | Type | Normal | Notes |
|---|---|---|---|---|
| 1010 | Cash — Operating Bank | Asset | Dr | Where payouts land |
| 1200 | Accounts Receivable | Asset | Dr | Invoiced, not yet settled |
| **1310** | **MoR Clearing — Dodo** | **Asset** | **Dr** | **THE account. Must prove to residual-only.** |
| 1320 | MoR Reserve Receivable | Asset | Dr | Rolling reserve withheld by MoR |
| 1330 | MoR In-Transit | Asset | Dr | Payout initiated, not yet deposited |
| 2100 | Sales Tax / VAT Payable — MoR remitted | Liability | Cr | MoR remits on our behalf |
| 2200 | Refunds Payable | Liability | Cr | Approved, not yet settled |
| 2400 | Deferred Revenue | Liability | Cr | Subscription not yet earned |
| 4010 | Subscription Revenue | Revenue | Cr | |
| 4020 | One-Time Product Revenue | Revenue | Cr | |
| 4900 | Refunds & Allowances | Contra-revenue | Dr | Never net against 4010 |
| 5100 | Payment Processing Fees | Expense | Dr | Per-transaction |
| 5110 | MoR Platform Fees | Expense | Dr | Percentage / platform |
| 6810 | Chargeback & Dispute Losses | Expense | Dr | Lost dispute principal |
| 6820 | Dispute Fees | Expense | Dr | Non-refundable, even on a win |
| 7410 | Realized FX Gain / (Loss) | Other | Dr/Cr | Settlement rate vs booked rate |
| **7490** | **Rounding Adjustment** | **Other** | **Dr/Cr** | **CAPPED — see control below** |

## The plug-account control (say this to judges)

7490 exists because Dodo pro-rates ledger entries into the payout currency, which produces
genuine sub-cent residuals. Without a cap, an agent could "plug" any imbalance here and
declare victory — the exact failure mode that makes finance teams distrust automation.

**Hard caps, enforced deterministically, not by the model:**

- ≤ **$1.00** per payout
- ≤ **$25.00** per period, aggregate
- Any breach raises `POLICY_VIOLATION` and **blocks the close**. It is never auto-resolved.

The agent is structurally incapable of hiding a real imbalance in the rounding account.

## Event type → posting map

Dodo `breakup-details` event types map as follows. The Classifier assigns the event type;
the posting itself is table-driven and deterministic.

| Dodo event type | Debit | Credit |
|---|---|---|
| `payment` | 1310 MoR Clearing | 4010/4020 Revenue + 2100 Tax Payable |
| `refund` | 4900 Refunds & Allowances + 2100 Tax Payable | 1310 MoR Clearing |
| `processing_fee` | 5100 Processing Fees | 1310 MoR Clearing |
| `platform_fee` | 5110 MoR Platform Fees | 1310 MoR Clearing |
| `dispute_opened` | 6810 Dispute Losses | 1310 MoR Clearing |
| `dispute_won` (reversal) | 1310 MoR Clearing | 6810 Dispute Losses |
| `dispute_fee` | 6820 Dispute Fees | 1310 MoR Clearing |
| `tax_remitted` | 2100 Tax Payable | 1310 MoR Clearing |
| `reserve_held` | 1320 Reserve Receivable | 1310 MoR Clearing |
| `reserve_released` | 1310 MoR Clearing | 1320 Reserve Receivable |
| `fx_adjustment` | 7410 FX Gain/(Loss) | 1310 MoR Clearing |
| `payout` | 1330 MoR In-Transit | 1310 MoR Clearing |
| bank deposit observed | 1010 Cash | 1330 MoR In-Transit |
| pro-rating residual | 7490 Rounding *(capped)* | 1310 MoR Clearing |

Deliberate choices worth defending:

- **Revenue is booked gross, tax as a liability.** Booking the net payout as revenue
  understates revenue and hides processor cost — the single most common error in this
  workflow.
- **Refunds go to contra-revenue (4900), never netted against 4010.** Netting destroys the
  gross-revenue disclosure and is an audit finding.
- **Dispute fee is separate from dispute loss.** The fee is not returned even when the
  dispute is won, so they have different economics and must be separately visible.
- **Payout routes through 1330 In-Transit, not straight to cash.** This is what makes the
  bank tie-out (proof P4) a real control rather than an assumption.

## Materiality thresholds

Aligned to audit convention, scaled to the synthetic entity (assume ~$2.4M annual revenue):

| Threshold | Value | Governs |
|---|---|---|
| Auto-resolve ceiling | $250.00 | Agent may resolve autonomously below this |
| Escalation floor | $250.00 | At or above: human ruling required |
| Period aggregate trigger | $2,500.00 | Aggregate unexplained forces escalation regardless of individual size |
| Rounding cap (per payout) | $1.00 | Hard block |
| Rounding cap (per period) | $25.00 | Hard block |

Materiality is checked on **absolute value**, and an exception that is individually
immaterial still escalates if its archetype is unrecognized — novelty overrides size.
