"""P4: every settled payout must tie out to exactly one matching bank deposit."""
from datetime import datetime
from decimal import Decimal
from typing import cast

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.contracts import ProofResult, RunContext
from backend.app.engine.matcher import (
    BANK_MATCH_DATE_WINDOW,
    BANK_MATCH_DATE_WINDOW_DAYS,
    VALID_PAYOUT_STATUSES,
)
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import BankLine, Payout

MATCH_WINDOW = BANK_MATCH_DATE_WINDOW


class P4BankTieOut:
    """Every completed payout must match exactly one bank deposit, same amount, within window."""

    id = "P4"
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
                select(Payout).where(
                    Payout.run_id == ctx.run_id,
                    Payout.status.in_(VALID_PAYOUT_STATUSES),
                )
            )
        )
        bank_lines = list(
            session.scalars(
                select(BankLine).where(BankLine.run_id == ctx.run_id)
            )
        )

        lines_by_payout: dict[str, list[BankLine]] = {}
        for line in bank_lines:
            if line.matched_payout_id is not None:
                lines_by_payout.setdefault(str(line.matched_payout_id), []).append(line)

        failures = []
        for payout in payouts:
            matches = lines_by_payout.get(str(payout.id), [])
            # Also check if payout.bank_line_id links to a bank line
            if not matches and payout.bank_line_id is not None:
                bl = session.get(BankLine, payout.bank_line_id)
                if bl is not None:
                    matches = [bl]

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

            if str(line.currency) != str(payout.currency):
                failures.append({
                    "payout_id": payout.id,
                    "reason": (
                        f"currency mismatch: payout.currency={payout.currency}, "
                        f"bank_line.currency={line.currency}"
                    ),
                })
                continue

            if payout.settled_at is None:
                failures.append({
                    "payout_id": payout.id,
                    "reason": "payout has no settled_at, cannot verify date window",
                })
                continue

            if line.posted_at is None:
                failures.append({
                    "payout_id": payout.id,
                    "reason": "bank_line has no posted_at, cannot verify date window",
                })
                continue

            settled_at = cast(datetime, payout.settled_at)
            posted_at = cast(datetime, line.posted_at)
            delta = abs(posted_at - settled_at)
            if delta > BANK_MATCH_DATE_WINDOW:
                failures.append({
                    "payout_id": payout.id,
                    "reason": (
                        f"bank_line posted_at {posted_at} outside +/- "
                        f"{BANK_MATCH_DATE_WINDOW_DAYS} day window of settled_at {settled_at}"
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

