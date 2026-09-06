"""P1: every journal entry's debit lines must equal its credit lines, to the cent."""
from decimal import Decimal

from sqlalchemy import create_engine, func
from sqlalchemy.orm import Session

from backend.app.contracts import ProofResult, RunContext
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import JournalEntry, JournalLine

ZERO = Decimal("0.00")


class P1DebitCreditBalance:
    """Proof obligation P1: every journal entry's debits must equal its credits."""

    id = "P1"
    blocking = True

    def evaluate(self, ctx: RunContext, session: Session | None = None) -> ProofResult:
        if session is not None:
            return self._evaluate(session, ctx)
        engine = create_engine(get_db_url())
        with Session(engine) as owned_session:
            return self._evaluate(owned_session, ctx)

    def _evaluate(self, session: Session, ctx: RunContext) -> ProofResult:
        rows = (
            session.query(
                JournalLine.entry_id,
                func.sum(JournalLine.debit),
                func.sum(JournalLine.credit),
            )
            .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
            .filter(JournalEntry.run_id == ctx.run_id)
            .group_by(JournalLine.entry_id)
            .all()
        )

        max_delta = ZERO
        imbalanced_entries = []
        for entry_id, total_debit, total_credit in rows:
            delta = abs((total_debit or ZERO) - (total_credit or ZERO))
            if delta > max_delta:
                max_delta = delta
            if delta != ZERO:
                imbalanced_entries.append(
                    {
                        "entry_id": entry_id,
                        "debit": str(total_debit),
                        "credit": str(total_credit),
                        "delta": str(delta),
                    }
                )

        return ProofResult(
            id=self.id,
            passed=max_delta == ZERO,
            expected=ZERO,
            actual=max_delta,
            delta=max_delta,
            detail={
                "entries_checked": len(rows),
                "imbalanced_entries": imbalanced_entries,
            },
        )
