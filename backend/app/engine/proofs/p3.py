"""P3: clearing account rollforward proof.

Validates the actual general ledger clearing account 1310 (MoR Clearing — Dodo):
    opening (0.00) + sum(debits_1310) - sum(credits_1310) == 0.00
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.app.contracts import ProofResult, RunContext
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import JournalEntry, JournalLine, Payout, SettlementEvent

ZERO = Decimal("0.00")
CLEARING_ACCOUNT_CODE = "1310"

CATEGORIES = {
    "payment": "charges",
    "refund": "refunds",
    "processing_fee": "fees",
    "platform_fee": "fees",
    "tax_remitted": "tax_remitted",
    "fx_adjustment": "fx_adjustment",
}


def _categorize(event_type: str) -> str:
    if event_type in CATEGORIES:
        return CATEGORIES[event_type]
    if event_type.startswith("dispute_"):
        return "disputes"
    if event_type.startswith("reserve_"):
        return "reserve_movements"
    return "other"


def _to_finite_decimal(val: Any) -> Decimal:
    if val is None:
        return ZERO
    d = Decimal(str(val))
    if not d.is_finite():
        raise ValueError(f"Non-finite decimal: {val}")
    return d


@dataclass
class P3:
    """Clearing account rollforward: closing balance on 1310 must be $0.00."""

    id: str = "P3"
    blocking: bool = True

    def evaluate(self, ctx: RunContext, session: Session | None = None) -> ProofResult:
        if session is not None:
            return self._evaluate(session, ctx)
        engine = create_engine(get_db_url())
        with Session(engine) as owned_session:
            return self._evaluate(owned_session, ctx)

    def _evaluate(self, session: Session, ctx: RunContext) -> ProofResult:
        # 1. Query journal lines posted to the clearing account (1310)
        clearing_lines = list(
            session.scalars(
                select(JournalLine)
                .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                .where(
                    JournalEntry.run_id == ctx.run_id,
                    JournalLine.account_code == CLEARING_ACCOUNT_CODE,
                )
            )
        )

        entry_count = session.scalar(
            select(func.count(JournalEntry.id)).where(JournalEntry.run_id == ctx.run_id)
        ) or 0

        # Query settlement events and payouts for context / detail breakdown
        events = list(
            session.scalars(
                select(SettlementEvent).where(SettlementEvent.run_id == ctx.run_id)
            )
        )
        payouts = list(
            session.scalars(
                select(Payout).where(Payout.run_id == ctx.run_id)
            )
        )

        breakdown: dict[str, Decimal] = {}
        for event in events:
            category = _categorize(str(event.event_type))
            amount = _to_finite_decimal(event.amount_payout)
            breakdown[category] = breakdown.get(category, ZERO) + amount

        events_total = sum(breakdown.values(), ZERO)
        payout_out = sum((_to_finite_decimal(p.net) for p in payouts), ZERO)
        source_residual = events_total - payout_out

        opening_balance = ZERO

        # If entries exist but no lines on 1310, or no entries at all while events exist
        if entry_count == 0 and (len(events) > 0 or len(payouts) > 0):
            delta = abs(source_residual) if source_residual != ZERO else Decimal("1.00")
            return ProofResult(
                id=self.id,
                passed=False,
                expected=ZERO,
                actual=delta,
                delta=delta,
                detail={
                    "opening_balance": str(opening_balance),
                    "error": "No journal entries posted for run",
                    "closing_balance": str(delta),
                    "source_events_total": str(events_total),
                    "payout_out": str(payout_out),
                    "source_residual": str(source_residual),
                    **{k: str(v) for k, v in breakdown.items()},
                },
            )

        # Group clearing lines by currency
        lines_by_curr: dict[str, list[JournalLine]] = {}
        for line in clearing_lines:
            curr = str(line.currency) if line.currency is not None else "UNKNOWN"
            lines_by_curr.setdefault(curr, []).append(line)

        max_delta = ZERO
        total_dr = ZERO
        total_cr = ZERO
        closing_balance = ZERO
        currency_breakdown: dict[str, Any] = {}

        if not clearing_lines and (len(events) > 0 or len(payouts) > 0):
            max_delta = abs(source_residual) if source_residual != ZERO else Decimal("1.00")
            closing_balance = max_delta
        else:
            for curr, cur_lines in lines_by_curr.items():
                c_dr = sum((_to_finite_decimal(line.debit) for line in cur_lines), ZERO)
                c_cr = sum((_to_finite_decimal(line.credit) for line in cur_lines), ZERO)
                total_dr += c_dr
                total_cr += c_cr
                c_closing = opening_balance + c_dr - c_cr
                c_delta = abs(c_closing)
                if c_delta > max_delta:
                    max_delta = c_delta
                closing_balance += c_closing
                currency_breakdown[curr] = {
                    "debits": str(c_dr),
                    "credits": str(c_cr),
                    "closing": str(c_closing),
                    "delta": str(c_delta),
                }

        expected = ZERO
        passed = (max_delta == ZERO) and (entry_count > 0 or len(events) == 0)

        return ProofResult(
            id=self.id,
            passed=passed,
            expected=expected,
            actual=closing_balance,
            delta=max_delta,
            detail={
                "opening_balance": str(opening_balance),
                "debits_1310": str(total_dr),
                "credits_1310": str(total_cr),
                "closing_balance": str(closing_balance),
                "source_events_total": str(events_total),
                "payout_out": str(payout_out),
                "source_residual": str(source_residual),
                "currencies": currency_breakdown,
                **{k: str(v) for k, v in breakdown.items()},
            },
        )

