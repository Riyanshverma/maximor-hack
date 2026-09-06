"""AMOUNT_MISMATCH handler (taxonomy type 1).

Sum of a payout's settlement-event components must equal payout.net. Detection
reuses the P2 payout-components-sum pattern (backend/app/engine/proofs/p2.py).

Per docs/02-exception-taxonomy.md:
  Auto if: delta <= $1.00 and attributable to pro-rating -> post to 7490 within cap.
  Escalate if: delta > $1.00, or the 7490 cap is already consumed.
  Rule shape: none (structural) -- compile_rule always returns None.

Per docs/01-chart-of-accounts.md, account 7490 is capped at <=$1.00 per payout
and <=$25.00 per period aggregate; breaching either forces escalation instead
of an auto-post (a breach itself is POLICY_VIOLATION territory, handled by a
different handler).
"""
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.contracts import ExceptionDraft, RunContext
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import JournalEntry, JournalLine, Payout, SettlementEvent

ZERO = Decimal("0.00")
PER_PAYOUT_CAP = Decimal("1.00")
PER_PERIOD_CAP = Decimal("25.00")
ROUNDING_ACCOUNT = "7490"
CLEARING_ACCOUNT = "1310"


def _to_finite_decimal(val: Any) -> Decimal:
    if val is None:
        return ZERO
    d = Decimal(str(val))
    if not d.is_finite():
        raise ValueError(f"Non-finite decimal: {val}")
    return d


class AmountMismatchHandler:
    """Detects payouts whose settlement-event components don't sum to payout.net."""

    type = "AMOUNT_MISMATCH"
    build_priority = 1

    def detect(self, ctx: RunContext, session: Session | None = None) -> list[ExceptionDraft]:
        if session is not None:
            return self._detect(session, ctx)
        engine = create_engine(get_db_url())
        with Session(engine) as owned_session:
            return self._detect(owned_session, ctx)

    def _detect(self, session: Session, ctx: RunContext) -> list[ExceptionDraft]:
        payouts = list(session.scalars(select(Payout).where(Payout.run_id == ctx.run_id)))
        events = list(
            session.scalars(
                select(SettlementEvent).where(
                    SettlementEvent.run_id == ctx.run_id,
                    SettlementEvent.payout_id.isnot(None),
                )
            )
        )

        components_by_payout: dict[str, Decimal] = {}
        for event in events:
            pid = str(event.payout_id)
            components_by_payout[pid] = components_by_payout.get(pid, ZERO) + _to_finite_decimal(
                event.amount_payout
            )

        drafts = []
        for payout in payouts:
            pid = str(payout.id)
            net = _to_finite_decimal(payout.net)
            actual = components_by_payout.get(pid, ZERO)
            delta = actual - net
            if delta == ZERO:
                continue
            severity = "low" if abs(delta) <= PER_PAYOUT_CAP else "high"
            drafts.append(
                ExceptionDraft(
                    type=self.type,
                    severity=severity,
                    amount=abs(delta),
                    confidence=Decimal("1.0"),
                    evidence={
                        "payout_id": pid,
                        "delta": str(delta),
                        "currency": str(payout.currency),
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

    def _gather(self, session: Session, exc: ExceptionDraft, ctx: RunContext) -> dict[str, Any]:
        payout_id = exc.evidence["payout_id"]
        payout = session.get(Payout, payout_id)
        events = list(
            session.scalars(
                select(SettlementEvent).where(SettlementEvent.payout_id == payout_id)
            )
        )

        entries = [
            {
                "id": e.id,
                "event_type": e.event_type,
                "amount_native": str(_to_finite_decimal(e.amount_native)),
                "currency_native": e.currency_native,
                "amount_payout": str(_to_finite_decimal(e.amount_payout)),
                "currency_payout": e.currency_payout,
                "fx_rate": str(_to_finite_decimal(e.fx_rate)) if e.fx_rate is not None else None,
            }
            for e in events
        ]

        payout_header = (
            {
                "id": payout.id,
                "net": str(_to_finite_decimal(payout.net)),
                "gross": str(_to_finite_decimal(payout.gross)),
                "fees": str(_to_finite_decimal(payout.fees)),
                "currency": payout.currency,
            }
            if payout is not None
            else None
        )

        period_7490_consumed = self._period_7490_consumed(session, ctx)

        return {
            "entries": entries,
            "payout": payout_header,
            "delta": exc.evidence.get("delta"),
            "period_7490_consumed": str(period_7490_consumed),
            "per_payout_cap": str(PER_PAYOUT_CAP),
            "per_period_cap": str(PER_PERIOD_CAP),
        }

    def _period_7490_consumed(self, session: Session, ctx: RunContext) -> Decimal:
        """Sum of amounts already posted to 7490 for this run's period (cap tracking)."""
        lines = list(
            session.scalars(
                select(JournalLine)
                .join(JournalEntry, JournalLine.entry_id == JournalEntry.id)
                .where(
                    JournalEntry.run_id == ctx.run_id,
                    JournalEntry.period == ctx.period,
                    JournalLine.account_code == ROUNDING_ACCOUNT,
                )
            )
        )
        total = ZERO
        for line in lines:
            total += abs(_to_finite_decimal(line.debit) - _to_finite_decimal(line.credit))
        return total

    def hypothesize(self, exc: ExceptionDraft, evidence: dict[str, Any]) -> list[dict[str, Any]]:
        delta = _to_finite_decimal(evidence.get("delta"))
        cap_consumed = _to_finite_decimal(evidence.get("period_7490_consumed"))
        cap_available = PER_PERIOD_CAP - cap_consumed
        attributable_to_pro_rating = abs(delta) <= PER_PAYOUT_CAP

        root_cause = "pro_rating_residual" if attributable_to_pro_rating else "unexplained"
        return [
            {
                "root_cause": root_cause,
                "delta": str(delta),
                "cap_available": str(cap_available),
                "confidence": "1.0",
            }
        ]

    def propose(
        self, exc: ExceptionDraft, hypothesis: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        delta = _to_finite_decimal(hypothesis.get("delta"))
        cap_available = _to_finite_decimal(hypothesis.get("cap_available"))

        if hypothesis.get("root_cause") != "pro_rating_residual":
            return {
                "route": "ESCALATE",
                "reason": (
                    f"delta {delta} exceeds ${PER_PAYOUT_CAP} per-payout auto-resolve threshold"
                ),
            }

        if abs(delta) > cap_available:
            return {
                "route": "ESCALATE",
                "reason": "period aggregate 7490 rounding cap already consumed",
            }

        # Per docs/01-chart-of-accounts.md posting map: "pro-rating residual" ->
        # Debit 7490 Rounding, Credit 1310 Clearing (magnitude only; sign is not posted).
        return {
            "route": "AUTO",
            "action": "post_journal_entry",
            "debit_account": ROUNDING_ACCOUNT,
            "credit_account": CLEARING_ACCOUNT,
            "amount": str(abs(delta)),
        }

    def compile_rule(
        self, exc: ExceptionDraft, ruling: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        # AMOUNT_MISMATCH is structural per docs/02-exception-taxonomy.md ("Rule shape: none").
        return None
