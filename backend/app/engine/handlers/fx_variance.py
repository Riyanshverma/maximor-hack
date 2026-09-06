"""FX_VARIANCE exception handler (taxonomy type 2).

Settlement FX rate differs from the rate booked at invoice time. The booked
rate is planted by the generator in ``SettlementEvent.raw["booked_fx_rate"]``;
the settled rate is the event's ``fx_rate`` column (there is no separate
schema column for the booked rate).
"""
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.contracts import ExceptionDraft, RunContext
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import Invoice, SettlementEvent

RATE_VARIANCE_THRESHOLD = Decimal("0.005")
AUTO_RESOLVE_LIMIT = Decimal("250")
FX_GAIN_LOSS_ACCOUNT = "7410"


def _rates(event: SettlementEvent) -> Optional[tuple[Decimal, Decimal]]:
    """Extract (rate_booked, rate_settled) from a settlement event, if planted."""
    raw = event.raw or {}
    booked = raw.get("booked_fx_rate")
    if booked is None or event.fx_rate is None:
        return None
    return Decimal(str(booked)), Decimal(str(event.fx_rate))


class FXVarianceHandler:
    """Detects settlement FX rate variance against the rate booked at invoice."""

    type = "FX_VARIANCE"
    build_priority = 1

    def detect(
        self, ctx: RunContext, session: Session | None = None
    ) -> list[ExceptionDraft]:
        if session is not None:
            return self._detect(session, ctx)
        engine = create_engine(get_db_url())
        with Session(engine) as owned_session:
            return self._detect(owned_session, ctx)

    def _detect(self, session: Session, ctx: RunContext) -> list[ExceptionDraft]:
        events = list(
            session.scalars(
                select(SettlementEvent).where(SettlementEvent.run_id == ctx.run_id)
            )
        )
        drafts = []
        for event in events:
            rates = _rates(event)
            if rates is None:
                continue
            rate_booked, rate_settled = rates
            if rate_booked == 0:
                continue
            variance = abs(rate_settled - rate_booked) / rate_booked
            if variance <= RATE_VARIANCE_THRESHOLD:
                continue

            impact = (
                abs(rate_settled - rate_booked) * Decimal(str(event.amount_payout))
            ).quantize(Decimal("0.01"))
            ambiguous = event.fx_source is None
            escalate = impact >= AUTO_RESOLVE_LIMIT or ambiguous

            drafts.append(
                ExceptionDraft(
                    type=self.type,
                    severity="medium" if escalate else "low",
                    amount=impact,
                    confidence=Decimal("1.0"),
                    evidence={
                        "settlement_event_id": event.id,
                        "rate_booked": str(rate_booked),
                        "rate_settled": str(rate_settled),
                        "variance": str(variance),
                        "rate_source_ambiguous": ambiguous,
                    },
                )
            )
        return drafts

    def gather(
        self, exc: ExceptionDraft, ctx: RunContext, session: Session | None = None
    ) -> dict[str, Any]:
        if session is not None:
            return self._gather(session, exc, ctx)
        engine = create_engine(get_db_url())
        with Session(engine) as owned_session:
            return self._gather(owned_session, exc, ctx)

    def _gather(
        self, session: Session, exc: ExceptionDraft, ctx: RunContext
    ) -> dict[str, Any]:
        event = session.get(SettlementEvent, exc.evidence["settlement_event_id"])

        invoice = None
        if event is not None and event.customer_id is not None:
            invoice = session.scalars(
                select(Invoice)
                .where(
                    Invoice.run_id == ctx.run_id,
                    Invoice.customer_id == event.customer_id,
                )
                .order_by(Invoice.issued_at)
            ).first()

        return {
            "rate_booked": exc.evidence["rate_booked"],
            "rate_settled": exc.evidence["rate_settled"],
            "variance": exc.evidence["variance"],
            "rate_source_ambiguous": exc.evidence["rate_source_ambiguous"],
            "settlement_event": None
            if event is None
            else {
                "id": event.id,
                "amount_payout": str(event.amount_payout),
                "currency_payout": event.currency_payout,
                "order_id": event.order_id,
            },
            "source_invoice": None
            if invoice is None
            else {
                "id": invoice.id,
                "external_id": invoice.external_id,
                "currency": invoice.currency,
            },
        }

    def hypothesize(
        self, exc: ExceptionDraft, evidence: dict[str, Any]
    ) -> list[dict[str, Any]]:
        return [
            {
                "cause": "fx_rate_variance",
                "description": (
                    "Settlement FX rate diverged from the rate booked at invoice time."
                ),
                "confidence": float(exc.confidence),
            }
        ]

    def propose(
        self, exc: ExceptionDraft, hypothesis: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        ambiguous = bool(exc.evidence.get("rate_source_ambiguous", False))
        auto_eligible = exc.amount < AUTO_RESOLVE_LIMIT and not ambiguous
        return {
            "action": "post_journal_entry",
            "account_code": FX_GAIN_LOSS_ACCOUNT,
            "amount": str(exc.amount),
            "auto_eligible": auto_eligible,
        }

    def compile_rule(
        self, exc: ExceptionDraft, ruling: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        return {
            "name": "fx_variance_threshold",
            "predicate": {
                "currency": ruling.get("currency"),
                "band": str(AUTO_RESOLVE_LIMIT),
            },
            "action": {"post_account": FX_GAIN_LOSS_ACCOUNT},
            "source_ruling_id": ruling.get("id"),
        }
