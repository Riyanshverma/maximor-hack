"""P3: clearing account rollforward proof.

opening (0.00) + charges - fees - refunds - disputes +/- tax/reserve/fx - payout_out
must net to a closing balance of 0.00. Settlement event amounts are already signed
(charges positive, deductions negative), so the rollforward reduces to:
    sum(settlement_event.amount_payout) - sum(payout.net) == 0.00
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import cast

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.contracts import ProofResult, RunContext
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import Payout, SettlementEvent

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


@dataclass
class P3:
    """Clearing account rollforward: closing balance must be $0.00."""

    id: str = "P3"
    blocking: bool = True

    def evaluate(self, ctx: RunContext) -> ProofResult:
        engine = create_engine(get_db_url())
        with Session(engine) as session:
            events = session.scalars(
                select(SettlementEvent).where(SettlementEvent.run_id == ctx.run_id)
            ).all()
            payouts = session.scalars(
                select(Payout).where(Payout.run_id == ctx.run_id)
            ).all()

        breakdown: dict[str, Decimal] = {}
        for event in events:
            category = _categorize(cast(str, event.event_type))
            amount = cast(Decimal, event.amount_payout)
            breakdown[category] = breakdown.get(category, Decimal("0.00")) + amount

        events_total = sum(breakdown.values(), Decimal("0.00"))
        payout_out = sum((cast(Decimal, p.net) for p in payouts), Decimal("0.00"))
        closing_balance = events_total - payout_out

        expected = Decimal("0.00")
        delta = abs(closing_balance - expected)

        return ProofResult(
            id=self.id,
            passed=closing_balance == expected,
            expected=expected,
            actual=closing_balance,
            delta=delta,
            detail={
                "opening_balance": str(Decimal("0.00")),
                **{k: str(v) for k, v in breakdown.items()},
                "payout_out": str(payout_out),
                "closing_balance": str(closing_balance),
            },
        )
