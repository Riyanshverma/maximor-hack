"""BANK_UNMATCHED (taxonomy type 11): payout with no corresponding bank deposit.

Runs after backend.app.engine.matcher.match_bank_lines. The matcher already
resolves every unmatched payout to a unique 1:1 bank line where one exists
(both 1:N and N:1 ambiguity are settled there), so by the time this handler's
detect() runs, any payout with bank_line_id is None is by construction either
a zero-candidate or an ambiguous (2+ candidate) case. See PR description.
"""
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.contracts import ExceptionDraft, RunContext
from backend.app.engine.matcher import (
    BANK_MATCH_DATE_WINDOW,
    BANK_MATCH_DATE_WINDOW_DAYS,
    VALID_PAYOUT_STATUSES,
    is_candidate_bank_match,
)
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import BankLine, Payout


class BankUnmatchedHandler:
    """Detects payouts left unmatched by the bank tie-out matcher."""

    type = "BANK_UNMATCHED"
    build_priority = 1

    def detect(self, ctx: RunContext, session: Session | None = None) -> list[ExceptionDraft]:
        if session is not None:
            return self._detect(session, ctx)
        engine = create_engine(get_db_url())
        with Session(engine) as owned_session:
            return self._detect(owned_session, ctx)

    def _detect(self, session: Session, ctx: RunContext) -> list[ExceptionDraft]:
        payouts = session.scalars(
            select(Payout).where(
                Payout.run_id == ctx.run_id,
                Payout.status.in_(VALID_PAYOUT_STATUSES),
                Payout.bank_line_id.is_(None),
            )
        )
        return [
            ExceptionDraft(
                type=self.type,
                severity="high",
                amount=Decimal(str(payout.net)),
                confidence=Decimal("1.0"),
                evidence={"payout_id": payout.id},
            )
            for payout in payouts
        ]

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
        payout = session.get(Payout, payout_id)
        if payout is None:
            return {"payout_id": payout_id, "candidate_bank_lines": [], "candidate_count": 0}

        bank_lines = session.scalars(select(BankLine).where(BankLine.run_id == ctx.run_id))
        candidates = [
            bl for bl in bank_lines if is_candidate_bank_match(bl, payout, BANK_MATCH_DATE_WINDOW)
        ]

        return {
            "payout": {
                "id": payout.id,
                "net": str(payout.net),
                "currency": payout.currency,
                "settled_at": (
                    payout.settled_at.isoformat() if payout.settled_at is not None else None
                ),
                "status": payout.status,
            },
            "candidate_bank_lines": [
                {
                    "id": bl.id,
                    "amount": str(bl.amount),
                    "currency": bl.currency,
                    "posted_at": bl.posted_at.isoformat() if bl.posted_at is not None else None,
                    "already_matched_to": bl.matched_payout_id,
                }
                for bl in candidates
            ],
            "candidate_count": len(candidates),
            "date_window_days": BANK_MATCH_DATE_WINDOW_DAYS,
        }

    def hypothesize(
        self, exc: ExceptionDraft, evidence: dict[str, Any]
    ) -> list[dict[str, Any]]:
        candidate_count = evidence.get("candidate_count", 0)
        if candidate_count == 0:
            return [
                {
                    "hypothesis": "deposit_missing_or_not_yet_posted",
                    "rationale": (
                        "No bank line matches the payout amount and currency within "
                        f"the +/- {BANK_MATCH_DATE_WINDOW_DAYS} day window."
                    ),
                }
            ]
        return [
            {
                "hypothesis": "ambiguous_deposit_match",
                "rationale": (
                    f"{candidate_count} bank lines match the payout amount and currency "
                    "within the window; the match cannot be uniquely resolved."
                ),
            }
        ]

    def propose(
        self, exc: ExceptionDraft, hypothesis: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        # No deterministic remedy exists for BANK_UNMATCHED: the taxonomy only
        # auto-resolves on a unique in-window candidate, and the matcher has
        # already claimed every such case before this handler runs.
        return None

    def compile_rule(
        self, exc: ExceptionDraft, ruling: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        return {
            "name": "bank_match_window",
            "predicate": {"type": self.type},
            "action": {
                "days": BANK_MATCH_DATE_WINDOW_DAYS,
                "amount_tolerance": "0.00",
            },
            "rationale": ruling.get("rationale", ""),
        }
