"""Handler for DISPUTE_LIFECYCLE_INCOMPLETE (taxonomy type 3).

A dispute opened in the period and unresolved at period end is never
auto-resolved -- it is a judgment call on loss provisioning -- so this
handler always escalates, with a proposed provision computed by the
deterministic `dispute_provision_policy` rule.
"""
import calendar
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.contracts import ExceptionDraft, RunContext
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import CloseRun, SettlementEvent

DISPUTE_OPENED = "dispute_opened"
OPEN_STATUSES = {"opened", "under_review"}
RESOLUTION_EVENT_TYPES = {"dispute_won", "dispute_lost"}

ZERO = Decimal("0.00")


def _to_decimal(val: Any) -> Decimal:
    if val is None:
        return ZERO
    return Decimal(str(val))


def _period_end(period: str) -> date:
    year, month = (int(part) for part in period.split("-"))
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)


def dispute_provision_policy(status: str, age_days: int) -> Decimal:
    """Deterministic loss provision % for an unresolved dispute.

    Provision escalates with age (older disputes are less likely to be won).
    A dispute already `under_review` gets a lower provision than a merely
    `opened` dispute of the same age, since review implies some progress.
    """
    if age_days <= 30:
        base = Decimal("0.50")
    elif age_days <= 60:
        base = Decimal("0.75")
    else:
        base = Decimal("1.00")
    if status == "under_review":
        base = base * Decimal("0.8")
    return base.quantize(Decimal("0.01"))


class DisputeLifecycleHandler:
    """Detects disputes opened in the period that remain unresolved at period end."""

    type = "DISPUTE_LIFECYCLE_INCOMPLETE"
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
        run = session.get(CloseRun, ctx.run_id)
        period = str(run.period) if run is not None else ctx.period

        events = list(
            session.scalars(
                select(SettlementEvent).where(SettlementEvent.run_id == ctx.run_id)
            )
        )

        by_payout: dict[str, list[SettlementEvent]] = {}
        for ev in events:
            if ev.payout_id is None:
                continue
            by_payout.setdefault(str(ev.payout_id), []).append(ev)

        drafts: list[ExceptionDraft] = []
        for payout_id, payout_events in by_payout.items():
            if any(str(e.event_type) in RESOLUTION_EVENT_TYPES for e in payout_events):
                continue
            for open_event in payout_events:
                if str(open_event.event_type) != DISPUTE_OPENED:
                    continue
                occurred_at = open_event.occurred_at
                if occurred_at is None or occurred_at.strftime("%Y-%m") != period:
                    continue
                raw = open_event.raw or {}
                status = raw.get("dispute_status", "opened")
                if status not in OPEN_STATUSES:
                    continue
                drafts.append(
                    ExceptionDraft(
                        type=self.type,
                        severity="high",
                        amount=abs(_to_decimal(open_event.amount_payout)),
                        confidence=Decimal("1.00"),
                        evidence={
                            "payout_id": payout_id,
                            "dispute_event_id": str(open_event.id),
                            "dispute_id": raw.get("dispute_id"),
                            "status": status,
                            "opened_at": occurred_at.isoformat(),
                            "period": period,
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
        payout_id = exc.evidence["payout_id"]
        events = list(
            session.scalars(
                select(SettlementEvent)
                .where(SettlementEvent.run_id == ctx.run_id)
                .where(SettlementEvent.payout_id == payout_id)
                .order_by(SettlementEvent.occurred_at)
            )
        )

        timeline = [
            {
                "event_id": str(e.id),
                "event_type": str(e.event_type),
                "occurred_at": e.occurred_at.isoformat() if e.occurred_at is not None else None,
                "amount_payout": str(_to_decimal(e.amount_payout)),
            }
            for e in events
        ]
        original_charge = next(
            (e for e in events if str(e.event_type) == "payment"), None
        )
        fee_entries = [e for e in events if str(e.event_type) == "dispute_fee"]

        return {
            "payout_id": payout_id,
            "timeline": timeline,
            "original_charge": (
                {
                    "event_id": str(original_charge.id),
                    "amount_payout": str(_to_decimal(original_charge.amount_payout)),
                }
                if original_charge is not None
                else None
            ),
            "fee_entries": [
                {
                    "event_id": str(f.id),
                    "amount_payout": str(_to_decimal(f.amount_payout)),
                }
                for f in fee_entries
            ],
        }

    def hypothesize(
        self, exc: ExceptionDraft, evidence: dict[str, Any]
    ) -> list[dict[str, Any]]:
        status = exc.evidence.get("status", "opened")
        opened_at = date.fromisoformat(str(exc.evidence["opened_at"])[:10])
        period_end = _period_end(str(exc.evidence["period"]))
        age_days = max((period_end - opened_at).days, 0)
        provision_pct = dispute_provision_policy(status, age_days)
        return [
            {
                "root_cause": "dispute_unresolved_at_period_end",
                "status": status,
                "age_days": age_days,
                "provision_pct": str(provision_pct),
            }
        ]

    def propose(
        self, exc: ExceptionDraft, hypothesis: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        provision_pct = Decimal(str(hypothesis["provision_pct"]))
        provision_amount = (exc.amount * provision_pct).quantize(Decimal("0.01"))
        return {
            "action": "propose_provision",
            "autonomy": "escalate",
            "reason": (
                "an open dispute is a judgment call on loss provisioning; "
                "never auto-resolved"
            ),
            "provision_pct": str(provision_pct),
            "provision_amount": str(provision_amount),
            "entry": {
                "debit": {"account": "6810", "amount": str(provision_amount)},
                "credit": {"account": "1310", "amount": str(provision_amount)},
            },
            "evidence": {
                "payout_id": exc.evidence.get("payout_id"),
                "dispute_id": exc.evidence.get("dispute_id"),
                "status": hypothesis.get("status"),
                "age_days": hypothesis.get("age_days"),
            },
        }

    def compile_rule(
        self, exc: ExceptionDraft, ruling: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        status = ruling.get("status") or exc.evidence.get("status")
        provision_pct = ruling.get("provision_pct")
        if status is None or provision_pct is None:
            return None
        return {
            "name": "dispute_provision_policy",
            "predicate": {"status": status},
            "action": {"provision_pct": str(provision_pct)},
            "rationale": ruling.get("rationale"),
        }
