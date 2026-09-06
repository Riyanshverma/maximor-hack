"""P1: every journal entry's debit lines must equal its credit lines, to the cent."""
from decimal import Decimal
from typing import Any

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.contracts import ProofResult, RunContext
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import JournalEntry, JournalLine

ZERO = Decimal("0.00")


def _to_finite_decimal(val: Any) -> Decimal:
    if val is None:
        return ZERO
    d = Decimal(str(val))
    if not d.is_finite():
        raise ValueError(f"Non-finite decimal: {val}")
    return d


class P1DebitCreditBalance:
    """Proof obligation P1: every journal entry's debits must equal its credits per currency."""

    id = "P1"
    blocking = True

    def evaluate(self, ctx: RunContext, session: Session | None = None) -> ProofResult:
        if session is not None:
            return self._evaluate(session, ctx)
        engine = create_engine(get_db_url())
        with Session(engine) as owned_session:
            return self._evaluate(owned_session, ctx)

    def _evaluate(self, session: Session, ctx: RunContext) -> ProofResult:
        entries = list(
            session.scalars(
                select(JournalEntry).where(JournalEntry.run_id == ctx.run_id)
            )
        )
        lines = list(
            session.scalars(
                select(JournalLine)
                .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                .where(JournalEntry.run_id == ctx.run_id)
            )
        )

        lines_by_entry: dict[str, list[JournalLine]] = {}
        for line in lines:
            lines_by_entry.setdefault(str(line.entry_id), []).append(line)

        max_delta = ZERO
        imbalanced_entries: list[dict[str, Any]] = []

        for entry in entries:
            entry_lines = lines_by_entry.get(str(entry.id), [])
            if not entry_lines:
                imbalanced_entries.append({
                    "entry_id": str(entry.id),
                    "currency": "NONE",
                    "debit": str(ZERO),
                    "credit": str(ZERO),
                    "delta": str(ZERO),
                    "reason": "entry has no journal lines",
                })
                continue

            # Group lines within this entry by currency
            currencies: dict[str, tuple[Decimal, Decimal]] = {}
            for line in entry_lines:
                curr = str(line.currency) if line.currency is not None else "UNKNOWN"
                dr = _to_finite_decimal(line.debit)
                cr = _to_finite_decimal(line.credit)
                prev_dr, prev_cr = currencies.get(curr, (ZERO, ZERO))
                currencies[curr] = (prev_dr + dr, prev_cr + cr)

            has_mixed_currencies = len(currencies) > 1

            for curr, (tot_dr, tot_cr) in currencies.items():
                delta = abs(tot_dr - tot_cr)
                if delta > max_delta:
                    max_delta = delta
                if delta != ZERO or curr == "UNKNOWN" or has_mixed_currencies:
                    reason = "debits != credits"
                    if curr == "UNKNOWN":
                        reason = "unknown currency"
                    elif has_mixed_currencies:
                        reason = "mixed-currency journal entry"
                    imbalanced_entries.append({
                        "entry_id": str(entry.id),
                        "currency": curr,
                        "debit": str(tot_dr),
                        "credit": str(tot_cr),
                        "delta": str(delta),
                        "reason": reason,
                    })
                    if has_mixed_currencies and delta == ZERO and max_delta == ZERO:
                        max_delta = Decimal("1.00")

        return ProofResult(
            id=self.id,
            passed=(max_delta == ZERO) and (len(imbalanced_entries) == 0),
            expected=ZERO,
            actual=max_delta,
            delta=max_delta,
            detail={
                "entries_checked": len(entries),
                "imbalanced_entries": imbalanced_entries,
            },
        )

