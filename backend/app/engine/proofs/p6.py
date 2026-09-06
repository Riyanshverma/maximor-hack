"""P6: no orphans — every settlement event maps to exactly one journal line."""
from collections import Counter
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.contracts import ProofResult, RunContext
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import JournalEntry, JournalLine, SettlementEvent


class P6NoOrphans:
    """Every settlement event has exactly one journal line, and vice versa."""

    id = "P6"
    blocking = True

    def evaluate(self, ctx: RunContext) -> ProofResult:
        engine = create_engine(get_db_url())
        with Session(engine) as session:
            return self._evaluate(session, ctx)

    def _evaluate(self, session: Session, ctx: RunContext) -> ProofResult:
        settlement_ids = set(
            session.scalars(
                select(SettlementEvent.id).where(SettlementEvent.run_id == ctx.run_id)
            ).all()
        )

        mapped_ids = list(
            session.scalars(
                select(JournalLine.settlement_event_id)
                .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
                .where(
                    JournalEntry.run_id == ctx.run_id,
                    JournalLine.settlement_event_id.is_not(None),
                )
            ).all()
        )

        counts = Counter(mapped_ids)
        missing = sorted(settlement_ids - set(mapped_ids))
        duplicated = sorted(
            sid for sid, count in counts.items() if count > 1 and sid in settlement_ids
        )
        dangling = sorted(set(mapped_ids) - settlement_ids)

        orphan_count = len(missing) + len(duplicated) + len(dangling)
        expected = Decimal("0")
        actual = Decimal(orphan_count)

        return ProofResult(
            id=self.id,
            passed=orphan_count == 0,
            expected=expected,
            actual=actual,
            delta=actual - expected,
            detail={
                "missing_settlement_events": missing,
                "duplicate_settlement_events": duplicated,
                "dangling_journal_lines": dangling,
            },
        )
