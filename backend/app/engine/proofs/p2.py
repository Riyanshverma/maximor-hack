"""P2: a payout's net amount must equal the sum of its settlement event components."""
from decimal import Decimal
from typing import cast

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.contracts import ProofResult, RunContext
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import Payout, SettlementEvent


class P2PayoutComponentsSum:
    """Sum of a payout's component settlement events (in payout currency) must equal payout.net."""

    id = "P2"
    blocking = True

    def evaluate(self, ctx: RunContext) -> ProofResult:
        engine = create_engine(get_db_url())
        with Session(engine) as session:
            payouts = session.query(Payout).filter(Payout.run_id == ctx.run_id).all()
            events = (
                session.query(SettlementEvent)
                .filter(SettlementEvent.run_id == ctx.run_id)
                .filter(SettlementEvent.payout_id.isnot(None))
                .all()
            )

        components_by_payout: dict[str, Decimal] = {}
        for event in events:
            payout_id = cast(str, event.payout_id)
            amount = cast(Decimal, event.amount_payout)
            components_by_payout[payout_id] = (
                components_by_payout.get(payout_id, Decimal("0")) + amount
            )

        total_expected = Decimal("0")
        total_actual = Decimal("0")
        failures = []
        for payout in payouts:
            expected = cast(Decimal, payout.net)
            actual = components_by_payout.get(cast(str, payout.id), Decimal("0"))
            delta = actual - expected
            total_expected += expected
            total_actual += actual
            if delta != 0:
                failures.append(
                    {
                        "payout_id": payout.id,
                        "expected": expected,
                        "actual": actual,
                        "delta": delta,
                    }
                )

        largest_delta = max((abs(f["delta"]) for f in failures), default=Decimal("0"))

        return ProofResult(
            id="P2",
            passed=not failures,
            expected=total_expected,
            actual=total_actual,
            delta=largest_delta,
            detail={"payouts_checked": len(payouts), "failures": failures},
        )
