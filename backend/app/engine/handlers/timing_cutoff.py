"""TIMING_CUTOFF (taxonomy type 6): payout spans the period boundary.

Detect: payout.created_at and payout.settled_at fall in different YYYY-MM
periods (docs/02-exception-taxonomy.md #6). The accrual is mechanical --
split via 1330 In-Transit -- unless the split would move material revenue
(>= $250) across the boundary, in which case escalate.
"""
import calendar
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.contracts import ExceptionDraft, RunContext
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import BankLine, Payout, SettlementEvent

IN_TRANSIT_ACCOUNT = "1330"
CLEARING_ACCOUNT = "1310"
MATERIALITY = Decimal("250.00")


def _period_of(dt) -> str:
    return f"{dt.year:04d}-{dt.month:02d}"


def _period_end(period: str) -> date:
    year, month = (int(p) for p in period.split("-"))
    return date(year, month, calendar.monthrange(year, month)[1])


class TimingCutoffHandler:
    """Detects payouts whose creation and settlement straddle a period boundary."""

    type = "TIMING_CUTOFF"
    build_priority = 6

    def detect(self, ctx: RunContext, session: Session | None = None) -> list[ExceptionDraft]:
        if session is not None:
            return self._detect(session, ctx)
        engine = create_engine(get_db_url())
        with Session(engine) as s:
            return self._detect(s, ctx)

    def _detect(self, session: Session, ctx: RunContext) -> list[ExceptionDraft]:
        payouts = list(session.scalars(select(Payout).where(Payout.run_id == ctx.run_id)))
        drafts = []
        for p in payouts:
            if p.created_at is None or p.settled_at is None:
                continue
            if _period_of(p.created_at) == _period_of(p.settled_at):
                continue
            net = Decimal(str(p.net))
            severity = "high" if abs(net) >= MATERIALITY else "medium"
            drafts.append(
                ExceptionDraft(
                    type=self.type,
                    severity=severity,
                    amount=abs(net),
                    confidence=Decimal("1.0"),
                    evidence={
                        "payout_id": p.id,
                        "created_at": p.created_at.isoformat(),
                        "settled_at": p.settled_at.isoformat(),
                        "created_period": _period_of(p.created_at),
                        "settled_period": _period_of(p.settled_at),
                    },
                )
            )
        return drafts

    def gather(
        self, exc: ExceptionDraft, ctx: RunContext, session: Session | None = None
    ) -> dict[str, Any]:
        if session is not None:
            return self._gather(session, exc)
        engine = create_engine(get_db_url())
        with Session(engine) as s:
            return self._gather(s, exc)

    def _gather(self, session: Session, exc: ExceptionDraft) -> dict[str, Any]:
        payout_id = exc.evidence["payout_id"]
        payout = session.get(Payout, payout_id)
        events = list(
            session.scalars(select(SettlementEvent).where(SettlementEvent.payout_id == payout_id))
        )
        bank_line = None
        if payout is not None and payout.bank_line_id is not None:
            bank_line = session.get(BankLine, payout.bank_line_id)
        return {
            "payout": {
                "id": payout_id,
                "net": str(payout.net) if payout else None,
                "currency": payout.currency if payout else None,
                "created_at": exc.evidence.get("created_at"),
                "settled_at": exc.evidence.get("settled_at"),
            },
            "bank_deposit_date": bank_line.posted_at.isoformat() if bank_line else None,
            "constituent_entries": [
                {
                    "id": e.id,
                    "event_type": e.event_type,
                    "amount_payout": str(e.amount_payout),
                    "occurred_at": e.occurred_at.isoformat() if e.occurred_at is not None else None,
                }
                for e in events
            ],
        }

    def hypothesize(self, exc: ExceptionDraft, evidence: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "root_cause": "period_boundary_lag",
                "created_period": exc.evidence.get("created_period"),
                "settled_period": exc.evidence.get("settled_period"),
                "material": str(exc.amount >= MATERIALITY).lower(),
            }
        ]

    def propose(
        self, exc: ExceptionDraft, hypothesis: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        if exc.amount >= MATERIALITY:
            return {
                "route": "ESCALATE",
                "reason": (
                    f"split would move {exc.amount} across the period boundary "
                    "(material revenue timing)"
                ),
            }
        return {
            "route": "AUTO",
            "action": "in_transit_split",
            "debit_account": IN_TRANSIT_ACCOUNT,
            "credit_account": CLEARING_ACCOUNT,
            "amount": str(exc.amount),
        }

    def compile_rule(
        self, exc: ExceptionDraft, ruling: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        return {
            "name": "cutoff_policy",
            "predicate": {"type": self.type},
            "action": {"days_tolerance": 3, "in_transit_account": IN_TRANSIT_ACCOUNT},
            "rationale": ruling.get("rationale", ""),
        }
