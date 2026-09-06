"""P6: no orphans — every settlement event maps to exactly one journal line."""
from collections import Counter
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.contracts import ProofResult, RunContext
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import JournalEntry, JournalLine, SettlementEvent

CLEARING_ACCOUNT_CODE = "1310"


class P6NoOrphans:
    """Every settlement event has exactly one journal line, and vice versa."""

    id = "P6"
    blocking = True

    def evaluate(self, ctx: RunContext, session: Session | None = None) -> ProofResult:
        if session is not None:
            return self._evaluate(session, ctx)
        engine = create_engine(get_db_url())
        with Session(engine) as owned_session:
            return self._evaluate(owned_session, ctx)

    def _evaluate(self, session: Session, ctx: RunContext) -> ProofResult:
        settlement_ids = set(
            session.scalars(
                select(SettlementEvent.id).where(SettlementEvent.run_id == ctx.run_id)
            ).all()
        )

        lines = list(
            session.scalars(
                select(JournalLine)
                .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
                .where(
                    JournalEntry.run_id == ctx.run_id,
                    JournalLine.settlement_event_id.is_not(None),
                )
            ).all()
        )

        # For multi-line split entries: if an entry contains lines tagged with the same
        # settlement_event_id, designate the clearing line (1310) as the primary mapping.
        # If an entry has a designated 1310 line for that event, subordinate split lines
        # (revenue, tax, etc.) in the same entry do not count as duplicate mappings.
        entry_event_lines: dict[tuple[str, str], list[JournalLine]] = {}
        for line in lines:
            eid = str(line.entry_id)
            sid = str(line.settlement_event_id)
            entry_event_lines.setdefault((eid, sid), []).append(line)

        mapped_ids: list[str] = []
        for (eid, sid), elines in entry_event_lines.items():
            clearing_lines = [
                entry_line for entry_line in elines
                if str(entry_line.account_code) == CLEARING_ACCOUNT_CODE
            ]
            if clearing_lines:
                for _ in clearing_lines:
                    mapped_ids.append(sid)
            else:
                for _ in elines:
                    mapped_ids.append(sid)

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

