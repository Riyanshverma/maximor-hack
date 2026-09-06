"""POLICY_VIOLATION (taxonomy type 13): a proposed entry breaches a control.

Never auto-resolved, always blocks the close, and is not learnable as a rule
(see docs/02-exception-taxonomy.md #13). This handler only detects and
reports; it never proposes a remedy amount or a compiled rule.
"""
from decimal import Decimal
from typing import Any, Optional, cast

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.contracts import ExceptionDraft, RunContext
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import GLAccount, JournalEntry, JournalLine, SettlementEvent

ZERO = Decimal("0.00")
ROUNDING_ACCOUNT = "7490"
ROUNDING_CAP_PER_PAYOUT = Decimal("1.00")
ROUNDING_CAP_AGGREGATE = Decimal("25.00")
PERIOD_AGGREGATE_TRIGGER = Decimal("2500.00")

_RULE_TEXT = {
    "rounding_cap_per_payout": (
        f"Rounding adjustments to account {ROUNDING_ACCOUNT} for a single payout "
        f"exceeded the ${ROUNDING_CAP_PER_PAYOUT} hard cap."
    ),
    "rounding_cap_aggregate": (
        f"Rounding adjustments to account {ROUNDING_ACCOUNT} for the period "
        f"exceeded the ${ROUNDING_CAP_AGGREGATE} hard cap."
    ),
    "restricted_account_touched": "A journal line posted to a restricted GL account.",
    "period_aggregate_trigger": (
        f"A single journal line exceeded the ${PERIOD_AGGREGATE_TRIGGER} "
        "period aggregate trigger."
    ),
}


def _dec(val: Any) -> Decimal:
    return Decimal(str(val)) if val is not None else ZERO


class PolicyViolationHandler:
    """Handler for POLICY_VIOLATION exceptions. build_priority=1."""

    type = "POLICY_VIOLATION"
    build_priority = 1

    def detect(self, ctx: RunContext, session: Session | None = None) -> list[ExceptionDraft]:
        if session is not None:
            return self._detect(session, ctx)
        engine = create_engine(get_db_url())
        with Session(engine) as owned_session:
            return self._detect(owned_session, ctx)

    def _detect(self, session: Session, ctx: RunContext) -> list[ExceptionDraft]:
        lines = list(
            session.scalars(
                select(JournalLine)
                .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                .where(JournalEntry.run_id == ctx.run_id)
            )
        )
        drafts: list[ExceptionDraft] = []

        # Trigger: period aggregate trigger — single entry over $2,500.00.
        for line in lines:
            amount = max(_dec(line.debit), _dec(line.credit))
            if amount > PERIOD_AGGREGATE_TRIGGER:
                drafts.append(self._draft(line, "period_aggregate_trigger", amount))

        # Trigger: restricted account touched.
        restricted_codes = {
            code
            for (code,) in session.execute(
                select(GLAccount.code).where(GLAccount.is_restricted.is_(True))
            )
        }
        for line in lines:
            if line.account_code in restricted_codes:
                amount = max(_dec(line.debit), _dec(line.credit))
                drafts.append(self._draft(line, "restricted_account_touched", amount))

        # Trigger: rounding cap breaches on account 7490.
        rounding_lines = [
            line for line in lines if cast(str, line.account_code) == ROUNDING_ACCOUNT
        ]

        by_payout: dict[str, Decimal] = {}
        by_payout_lines: dict[str, list[JournalLine]] = {}
        for line in rounding_lines:
            payout_id: str | None = None
            if line.settlement_event_id is not None:
                se = session.get(SettlementEvent, cast(str, line.settlement_event_id))
                payout_id = cast(Optional[str], se.payout_id) if se is not None else None
            key = payout_id if payout_id is not None else f"no-payout:{line.entry_id}"
            by_payout[key] = by_payout.get(key, ZERO) + (_dec(line.debit) - _dec(line.credit))
            by_payout_lines.setdefault(key, []).append(line)

        for key, net in by_payout.items():
            if abs(net) > ROUNDING_CAP_PER_PAYOUT:
                worst = max(
                    by_payout_lines[key], key=lambda ln: max(_dec(ln.debit), _dec(ln.credit))
                )
                drafts.append(self._draft(worst, "rounding_cap_per_payout", abs(net)))

        aggregate_net = sum(
            (_dec(line.debit) - _dec(line.credit) for line in rounding_lines), ZERO
        )
        if rounding_lines and abs(aggregate_net) > ROUNDING_CAP_AGGREGATE:
            worst = max(rounding_lines, key=lambda ln: max(_dec(ln.debit), _dec(ln.credit)))
            drafts.append(self._draft(worst, "rounding_cap_aggregate", abs(aggregate_net)))

        return drafts

    def _draft(self, line: JournalLine, trigger: str, amount: Decimal) -> ExceptionDraft:
        return ExceptionDraft(
            type=self.type,
            severity="critical",
            amount=amount,
            confidence=Decimal("1.00"),
            evidence={
                "trigger": trigger,
                "line_id": str(line.id),
                "entry_id": str(line.entry_id),
                "account_code": line.account_code,
            },
        )

    def gather(
        self, exc: ExceptionDraft, ctx: RunContext, session: Session | None = None
    ) -> dict[str, Any]:
        if session is not None:
            return self._gather(session, exc, ctx)
        engine = create_engine(get_db_url())
        with Session(engine) as owned_session:
            return self._gather(owned_session, exc, ctx)

    def _gather(self, session: Session, exc: ExceptionDraft, ctx: RunContext) -> dict[str, Any]:
        trigger = exc.evidence["trigger"]
        line = session.get(JournalLine, exc.evidence["line_id"])
        entry = session.get(JournalEntry, line.entry_id) if line is not None else None

        rounding_lines = list(
            session.scalars(
                select(JournalLine)
                .join(JournalEntry, JournalEntry.id == JournalLine.entry_id)
                .where(
                    JournalEntry.run_id == ctx.run_id,
                    JournalLine.account_code == ROUNDING_ACCOUNT,
                )
            )
        )
        cap_consumption = sum(
            (_dec(ln.debit) - _dec(ln.credit) for ln in rounding_lines), ZERO
        )

        return {
            "proposed_entry": {
                "entry_id": str(line.entry_id) if line is not None else None,
                "line_id": str(line.id) if line is not None else None,
                "account_code": line.account_code if line is not None else None,
                "debit": str(_dec(line.debit)) if line is not None else None,
                "credit": str(_dec(line.credit)) if line is not None else None,
                "currency": line.currency if line is not None else None,
                "memo": entry.memo if entry is not None else None,
            },
            "violated_rule": _RULE_TEXT.get(trigger, "policy control breached"),
            "cap_consumption_to_date": str(abs(cap_consumption)),
            "trigger": trigger,
        }

    def hypothesize(self, exc: ExceptionDraft, evidence: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "hypothesis": "policy_violation_detected",
                "trigger": evidence.get("trigger"),
                "rule_violated": evidence.get("violated_rule"),
            }
        ]

    def propose(
        self, exc: ExceptionDraft, hypothesis: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        return {
            "remedy": None,
            "blocks_close": True,
            "reason": (
                "POLICY_VIOLATION exceptions are never auto-resolved; policy is not "
                "learnable by the agent and always blocks the close."
            ),
        }

    def compile_rule(
        self, exc: ExceptionDraft, ruling: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        return None
