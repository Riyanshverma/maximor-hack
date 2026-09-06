"""LOW_CONFIDENCE_CLASSIFICATION (taxonomy type 12): classifier below threshold.

Detect: a settlement event carrying classifier output in ``raw``
(``raw.classification.confidence < 0.85``) for its GL account assignment.
Auto if: never -- that is what the threshold means. Always escalates with
the top-3 candidate accounts as evidence. Rule shape:
``classification_precedent(event_signature) -> account``.
"""
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.contracts import ExceptionDraft, RunContext
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import SettlementEvent

THRESHOLD = Decimal("0.85")


def _classification(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    cls = raw.get("classification")
    return cls if isinstance(cls, dict) else None


class LowConfidenceClassificationHandler:
    """Detects GL account assignments the classifier was unsure about."""

    type = "LOW_CONFIDENCE_CLASSIFICATION"
    build_priority = 1

    def detect(self, ctx: RunContext, session: Session | None = None) -> list[ExceptionDraft]:
        if session is not None:
            return self._detect(session, ctx)
        engine = create_engine(get_db_url())
        with Session(engine) as s:
            return self._detect(s, ctx)

    def _detect(self, session: Session, ctx: RunContext) -> list[ExceptionDraft]:
        events = list(
            session.scalars(select(SettlementEvent).where(SettlementEvent.run_id == ctx.run_id))
        )
        drafts = []
        for e in events:
            cls = _classification(e.raw)
            if cls is None:
                continue
            try:
                conf = Decimal(str(cls.get("confidence")))
            except Exception:
                continue
            if not conf.is_finite() or conf >= THRESHOLD:
                continue
            drafts.append(
                ExceptionDraft(
                    type=self.type,
                    severity="medium",
                    amount=abs(Decimal(str(e.amount_payout))),
                    confidence=conf,
                    evidence={
                        "settlement_event_id": e.id,
                        "assigned_account": cls.get("account"),
                        "confidence": str(conf),
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
        event = session.get(SettlementEvent, exc.evidence["settlement_event_id"])
        cls = _classification(event.raw) if event is not None else None
        candidates = (cls or {}).get("candidates", [])
        return {
            "entry": {
                "id": event.id if event else None,
                "event_type": event.event_type if event else None,
                "amount_payout": str(event.amount_payout) if event else None,
            },
            "assigned_account": (cls or {}).get("account"),
            "confidence": str(exc.confidence),
            "top_candidates": candidates[:3],
        }

    def hypothesize(self, exc: ExceptionDraft, evidence: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "hypothesis": "ambiguous_gl_assignment",
                "assigned_account": evidence.get("assigned_account"),
                "confidence": evidence.get("confidence"),
                "top_candidates": evidence.get("top_candidates", []),
            }
        ]

    def propose(
        self, exc: ExceptionDraft, hypothesis: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        return {
            "remedy": None,
            "route": "ESCALATE",
            "reason": (
                f"classifier confidence {exc.confidence} below {THRESHOLD} "
                "threshold; human must confirm the GL account"
            ),
        }

    def compile_rule(
        self, exc: ExceptionDraft, ruling: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        return {
            "name": "classification_precedent",
            "predicate": {
                "type": self.type,
                "event_signature": exc.evidence.get("settlement_event_id"),
            },
            "action": {"account": ruling.get("account")},
            "rationale": ruling.get("rationale", ""),
        }
