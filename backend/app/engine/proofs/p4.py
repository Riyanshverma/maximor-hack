"""P4: every settled payout must tie out to exactly one matching bank deposit."""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.contracts import ProofResult, RunContext
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import BankLine, Payout

# Bank deposits typically post within a week of the payout settling.
MATCH_WINDOW = timedelta(days=7)


class P4BankTieOut:
    """Every completed payout must match exactly one bank deposit, same amount, within window."""

    id = "P4"
    blocking = True

    def evaluate(self, ctx: RunContext) -> ProofResult:
        engine = create_engine(get_db_url())
        with Session(engine) as session:
            payouts = session.scalars(
                select(Payout).where(Payout.run_id == ctx.run_id, Payout.status == "completed")
            ).all()
            bank_lines = session.scalars(
                select(BankLine).where(BankLine.run_id == ctx.run_id)
            ).all()

        lines_by_payout: dict[str, list[BankLine]] = {}
        for line in bank_lines:
            if line.matched_payout_id is not None:
                lines_by_payout.setdefault(str(line.matched_payout_id), []).append(line)

        failures = []
        for payout in payouts:
            matches = lines_by_payout.get(str(payout.id), [])
            if len(matches) != 1:
                failures.append({
                    "payout_id": payout.id,
                    "reason": f"expected exactly 1 matched bank line, found {len(matches)}",
                })
                continue

            line = matches[0]
            if Decimal(str(line.amount)) != Decimal(str(payout.net)):
                failures.append({
                    "payout_id": payout.id,
                    "reason": (
                        f"amount mismatch: payout.net={payout.net}, "
                        f"bank_line.amount={line.amount}"
                    ),
                })
                continue

            if payout.settled_at is None:
                failures.append({
                    "payout_id": payout.id,
                    "reason": "payout has no settled_at, cannot verify date window",
                })
                continue

            settled_at = cast(datetime, payout.settled_at)
            posted_at = cast(datetime, line.posted_at)
            window_end = settled_at + MATCH_WINDOW
            if not (settled_at <= posted_at <= window_end):
                failures.append({
                    "payout_id": payout.id,
                    "reason": (
                        f"bank_line posted_at {posted_at} outside window "
                        f"[{settled_at}, {window_end}]"
                    ),
                })

        unmatched = Decimal(len(failures))
        return ProofResult(
            id=self.id,
            passed=unmatched == Decimal("0.00"),
            expected=Decimal("0.00"),
            actual=unmatched,
            delta=unmatched,
            detail={"failures": failures},
        )
