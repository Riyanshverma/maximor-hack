"""P5: Revenue completeness proof obligation.

Recognized revenue (credits to 4010/4020 net of debits to 4900 contra-revenue)
must equal invoiced subtotal (pre-tax, net of contra) for the period.
Taxes (2100) and dispute fees (6820) are strictly excluded from revenue.
"""
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session

from backend.app.contracts import ProofResult, RunContext
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import Invoice, JournalEntry, JournalLine

ZERO = Decimal("0.00")
REVENUE_ACCOUNT_CODES = {"4010", "4020"}
CONTRA_REVENUE_ACCOUNT_CODES = {"4900"}


def _to_finite_decimal(val: Any) -> Decimal:
    if val is None:
        return ZERO
    d = Decimal(str(val))
    if not d.is_finite():
        raise ValueError(f"Non-finite decimal: {val}")
    return d


class P5RevenueCompleteness:
    """Proof obligation: recognized revenue matches invoiced net-of-contra."""

    id = "P5"
    blocking = True

    def evaluate(
        self,
        ctx: RunContext,
        session: Session | None = None,
        engine: Optional[Engine] = None,
    ) -> ProofResult:
        if session is not None:
            return self._evaluate(session, ctx)
        engine = engine or create_engine(get_db_url(), echo=False)
        with Session(engine) as owned_session:
            return self._evaluate(owned_session, ctx)

    def _evaluate(self, session: Session, ctx: RunContext) -> ProofResult:
        invoices = list(
            session.scalars(
                select(Invoice).where(Invoice.run_id == ctx.run_id)
            )
        )
        target_accounts = REVENUE_ACCOUNT_CODES | CONTRA_REVENUE_ACCOUNT_CODES
        lines = list(
            session.scalars(
                select(JournalLine)
                .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                .where(
                    JournalEntry.run_id == ctx.run_id,
                    JournalLine.account_code.in_(target_accounts),
                )
            )
        )

        invoices_by_curr: dict[str, Decimal] = {}
        for inv in invoices:
            curr = str(inv.currency) if inv.currency is not None else "USD"
            subtotal = _to_finite_decimal(inv.subtotal)
            invoices_by_curr[curr] = invoices_by_curr.get(curr, ZERO) + subtotal

        # Track revenue and contra by currency
        rev_cr_by_curr: dict[str, Decimal] = {}
        rev_dr_by_curr: dict[str, Decimal] = {}
        contra_dr_by_curr: dict[str, Decimal] = {}
        contra_cr_by_curr: dict[str, Decimal] = {}

        for line in lines:
            curr = str(line.currency) if line.currency is not None else "USD"
            acct = str(line.account_code)
            dr = _to_finite_decimal(line.debit)
            cr = _to_finite_decimal(line.credit)

            if acct in REVENUE_ACCOUNT_CODES:
                rev_cr_by_curr[curr] = rev_cr_by_curr.get(curr, ZERO) + cr
                rev_dr_by_curr[curr] = rev_dr_by_curr.get(curr, ZERO) + dr
            elif acct in CONTRA_REVENUE_ACCOUNT_CODES:
                contra_dr_by_curr[curr] = contra_dr_by_curr.get(curr, ZERO) + dr
                contra_cr_by_curr[curr] = contra_cr_by_curr.get(curr, ZERO) + cr

        all_currs = sorted(
            set(invoices_by_curr.keys())
            | set(rev_cr_by_curr.keys())
            | set(contra_dr_by_curr.keys())
        )

        max_delta = ZERO
        total_invoiced = ZERO
        total_recognized = ZERO
        total_rev_cr = ZERO
        total_contra_dr = ZERO
        currencies_detail: dict[str, Any] = {}

        for curr in all_currs:
            inv_subtotal = invoices_by_curr.get(curr, ZERO)
            c_rev_cr = rev_cr_by_curr.get(curr, ZERO)
            c_rev_dr = rev_dr_by_curr.get(curr, ZERO)
            c_contra_dr = contra_dr_by_curr.get(curr, ZERO)
            c_contra_cr = contra_cr_by_curr.get(curr, ZERO)

            c_recognized = (c_rev_cr - c_rev_dr) - (c_contra_dr - c_contra_cr)
            c_delta = abs(inv_subtotal - c_recognized)

            total_invoiced += inv_subtotal
            total_recognized += c_recognized
            total_rev_cr += c_rev_cr
            total_contra_dr += c_contra_dr

            if c_delta > max_delta:
                max_delta = c_delta

            currencies_detail[curr] = {
                "invoiced_subtotal": str(inv_subtotal),
                "recognized_revenue": str(c_recognized),
                "revenue_credits_4010_4020": str(c_rev_cr),
                "contra_debits_4900": str(c_contra_dr),
                "delta": str(c_delta),
            }

        return ProofResult(
            id=self.id,
            passed=max_delta == ZERO,
            expected=total_invoiced,
            actual=total_recognized,
            delta=max_delta,
            detail={
                "invoice_count": len(invoices),
                "invoiced_subtotal": str(total_invoiced),
                "recognized_revenue": str(total_recognized),
                "revenue_credits_4010_4020": str(total_rev_cr),
                "contra_debits_4900": str(total_contra_dr),
                "currencies": currencies_detail,
            },
        )

