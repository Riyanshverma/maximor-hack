"""P5: Revenue completeness proof obligation.

Recognized revenue (settlement payments, net of refund/dispute contra-entries)
must equal invoiced net-of-contra for the period.
"""
from decimal import Decimal
from typing import Optional, cast

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session

from backend.app.contracts import ProofResult, RunContext
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import Invoice, SettlementEvent

REVENUE_EVENT_PREFIXES = ("payment", "refund", "dispute")


def _is_revenue_event(event_type) -> bool:
    return str(event_type).startswith(REVENUE_EVENT_PREFIXES)


class P5RevenueCompleteness:
    """Proof obligation: recognized revenue matches invoiced net-of-contra."""

    id = "P5"
    blocking = True

    def evaluate(self, ctx: RunContext, engine: Optional[Engine] = None) -> ProofResult:
        engine = engine or create_engine(get_db_url(), echo=False)

        with Session(engine) as session:
            invoices = (
                session.query(Invoice).filter(Invoice.run_id == ctx.run_id).all()
            )
            events = (
                session.query(SettlementEvent)
                .filter(SettlementEvent.run_id == ctx.run_id)
                .all()
            )

        invoiced_total: Decimal = sum(
            (cast(Decimal, inv.total) for inv in invoices), Decimal("0")
        )
        recognized_total: Decimal = sum(
            (
                cast(Decimal, evt.amount_native)
                for evt in events
                if _is_revenue_event(evt.event_type)
            ),
            Decimal("0"),
        )

        delta = abs(invoiced_total - recognized_total)

        return ProofResult(
            id=self.id,
            passed=delta == Decimal("0"),
            expected=invoiced_total,
            actual=recognized_total,
            delta=delta,
            detail={
                "invoice_count": len(invoices),
                "revenue_event_count": sum(
                    1 for evt in events if _is_revenue_event(evt.event_type)
                ),
            },
        )
