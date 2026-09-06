"""P2: a payout's net amount must equal the sum of its settlement event components."""
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.contracts import ProofResult, RunContext
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import Payout, SettlementEvent

ZERO = Decimal("0.00")


def _to_finite_decimal(val: Any) -> Decimal:
    if val is None:
        return ZERO
    d = Decimal(str(val))
    if not d.is_finite():
        raise ValueError(f"Non-finite decimal: {val}")
    return d


class P2PayoutComponentsSum:
    """Sum of a payout's component settlement events (in payout currency) must equal payout.net."""

    id = "P2"
    blocking = True

    def evaluate(self, ctx: RunContext, session: Session | None = None) -> ProofResult:
        if session is not None:
            return self._evaluate(session, ctx)
        engine = create_engine(get_db_url())
        with Session(engine) as owned_session:
            return self._evaluate(owned_session, ctx)

    def _evaluate(self, session: Session, ctx: RunContext) -> ProofResult:
        payouts = list(
            session.scalars(
                select(Payout).where(Payout.run_id == ctx.run_id)
            )
        )
        events = list(
            session.scalars(
                select(SettlementEvent)
                .where(
                    SettlementEvent.run_id == ctx.run_id,
                    SettlementEvent.payout_id.isnot(None),
                )
            )
        )

        components_by_payout_curr: dict[tuple[str, str], Decimal] = {}
        currencies_by_payout: dict[str, set[str]] = {}

        for event in events:
            pid = str(event.payout_id)
            curr = str(event.currency_payout) if event.currency_payout is not None else "UNKNOWN"
            amt = _to_finite_decimal(event.amount_payout)
            components_by_payout_curr[(pid, curr)] = (
                components_by_payout_curr.get((pid, curr), ZERO) + amt
            )
            currencies_by_payout.setdefault(pid, set()).add(curr)

        total_expected = ZERO
        total_actual = ZERO
        failures = []

        for payout in payouts:
            pid = str(payout.id)
            payout_curr = str(payout.currency)
            expected = _to_finite_decimal(payout.net)
            actual = components_by_payout_curr.get((pid, payout_curr), ZERO)
            delta = actual - expected

            total_expected += expected
            total_actual += actual

            event_currs = currencies_by_payout.get(pid, set())
            mismatched_currs = event_currs - {payout_curr}

            if delta != ZERO or mismatched_currs:
                reason = "components sum != payout net"
                if mismatched_currs:
                    reason = (
                        f"currency mismatch: payout currency is {payout_curr}, but components "
                        f"include currencies: {sorted(mismatched_currs)}"
                    )
                failures.append(
                    {
                        "payout_id": payout.id,
                        "currency": payout_curr,
                        "expected": str(expected),
                        "actual": str(actual),
                        "delta": str(delta),
                        "reason": reason,
                    }
                )

        largest_delta = max(
            (abs(_to_finite_decimal(f["delta"])) for f in failures),
            default=ZERO,
        )
        if failures and largest_delta == ZERO:
            largest_delta = Decimal("1.00")

        return ProofResult(
            id="P2",
            passed=not failures,
            expected=total_expected,
            actual=total_actual,
            delta=largest_delta,
            detail={"payouts_checked": len(payouts), "failures": failures},
        )

