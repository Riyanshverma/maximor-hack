"""Matcher: payout decomposition and bank tie-out.

Pure, deterministic, no LLM, no network. All amounts are Decimal.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.schema import BankLine, Payout, SettlementEvent

# BANK_UNMATCHED window per docs/02-exception-taxonomy.md: amount tolerance is
# zero (exact match to the cent); date window is +/- 3 days.
BANK_MATCH_DATE_WINDOW_DAYS = 3


def _is_candidate(bank_line: BankLine, payout: Payout, window: timedelta) -> bool:
    """Whether a bank line is an unmatched, exact-amount, in-window candidate for a payout."""
    if bank_line.matched_payout_id is not None:
        return False
    if cast(str, bank_line.currency) != cast(str, payout.currency):
        return False
    if cast(Decimal, bank_line.amount) != cast(Decimal, payout.net):
        return False
    delta = cast(datetime, bank_line.posted_at) - cast(datetime, payout.settled_at)
    return abs(delta) <= window


@dataclass
class PayoutDecomposition:
    """Summary of the settlement events that compose a payout."""
    payout_id: str
    events: list[SettlementEvent]
    total_amount_payout: Decimal


def decompose_payout(session: Session, run_id: str, payout_id: str) -> PayoutDecomposition:
    """Group SettlementEvent rows by payout_id for a given payout."""
    events = list(
        session.scalars(
            select(SettlementEvent)
            .where(SettlementEvent.run_id == run_id)
            .where(SettlementEvent.payout_id == payout_id)
            .order_by(SettlementEvent.occurred_at)
        )
    )
    total = sum((cast(Decimal, e.amount_payout) for e in events), Decimal("0"))
    return PayoutDecomposition(payout_id=payout_id, events=events, total_amount_payout=total)


def match_bank_lines(session: Session, run_id: str) -> list[tuple[str, str]]:
    """Match BankLine rows to Payouts for a run and persist matched_payout_id.

    A payout matches a bank line only when there is exactly one candidate bank
    line with an exact (zero-tolerance) amount match inside the date window
    around the payout's settled_at. Ambiguous (multiple candidates) or absent
    matches are left unmatched rather than forced.
    """
    payouts = list(session.scalars(select(Payout).where(Payout.run_id == run_id)))
    bank_lines = list(session.scalars(select(BankLine).where(BankLine.run_id == run_id)))

    matches: list[tuple[str, str]] = []
    window = timedelta(days=BANK_MATCH_DATE_WINDOW_DAYS)

    for payout in payouts:
        if payout.settled_at is None or payout.bank_line_id is not None:
            continue

        candidates = [bl for bl in bank_lines if _is_candidate(bl, payout, window)]

        if len(candidates) == 1:
            bank_line = candidates[0]
            bank_line.matched_payout_id = payout.id
            matches.append((cast(str, bank_line.id), cast(str, payout.id)))

    session.commit()
    return matches
