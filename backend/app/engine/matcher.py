"""Matcher: payout decomposition and bank tie-out.

Pure, deterministic, no LLM, no network. All amounts are Decimal.
"""
from collections import defaultdict
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
BANK_MATCH_DATE_WINDOW = timedelta(days=BANK_MATCH_DATE_WINDOW_DAYS)
VALID_PAYOUT_STATUSES = ("paid", "completed")


def is_candidate_bank_match(
    bank_line: BankLine,
    payout: Payout,
    window: timedelta = BANK_MATCH_DATE_WINDOW,
) -> bool:
    """Whether a bank line is a valid candidate for a payout under the bank tie-out contract.

    Contract requirements:
    1. payout.status in ("paid", "completed")
    2. payout.settled_at is not None and bank_line.posted_at is not None
    3. exact currency match (bank_line.currency == payout.currency)
    4. exact amount match (Decimal(bank_line.amount) == Decimal(payout.net))
    5. absolute date difference <= window (default +/- 3 days):
       abs(posted_at - settled_at) <= window
    """
    if payout.status not in VALID_PAYOUT_STATUSES:
        return False
    if payout.settled_at is None or bank_line.posted_at is None:
        return False
    if cast(str, bank_line.currency) != cast(str, payout.currency):
        return False
    if Decimal(str(bank_line.amount)) != Decimal(str(payout.net)):
        return False
    delta = cast(datetime, bank_line.posted_at) - cast(datetime, payout.settled_at)
    return abs(delta) <= window


def _is_candidate(bank_line: BankLine, payout: Payout, window: timedelta) -> bool:
    """Legacy helper maintained for compatibility."""
    if bank_line.matched_payout_id is not None:
        return False
    return is_candidate_bank_match(bank_line, payout, window)


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
    """Match BankLine rows to Payouts for a run and persist bidirectional foreign keys.

    A payout matches a bank line only when there is an unambiguous 1:1 match:
    - exactly 1 candidate bank line for the payout (resolves 1:N ambiguity)
    - exactly 1 candidate payout for that bank line (resolves N:1 ambiguity)
    Ambiguous (multiple candidates) or absent matches are left unmatched.

    Sets both:
      bank_line.matched_payout_id = payout.id
      payout.bank_line_id = bank_line.id
    """
    payouts = list(
        session.scalars(
            select(Payout).where(
                Payout.run_id == run_id,
                Payout.status.in_(VALID_PAYOUT_STATUSES),
            )
        )
    )
    bank_lines = list(session.scalars(select(BankLine).where(BankLine.run_id == run_id)))

    # Filter out already matched records
    available_payouts = [p for p in payouts if p.bank_line_id is None and p.settled_at is not None]
    available_lines = [bl for bl in bank_lines if bl.matched_payout_id is None]

    # Map candidates in both directions
    payout_candidates: dict[str, list[BankLine]] = defaultdict(list)
    line_candidates: dict[str, list[Payout]] = defaultdict(list)

    for p in available_payouts:
        for bl in available_lines:
            if is_candidate_bank_match(bl, p, BANK_MATCH_DATE_WINDOW):
                payout_candidates[cast(str, p.id)].append(bl)
                line_candidates[cast(str, bl.id)].append(p)

    matches: list[tuple[str, str]] = []

    for p in available_payouts:
        p_id = cast(str, p.id)
        candidate_lines = payout_candidates.get(p_id, [])
        # Must have exactly 1 candidate bank line (no 1:N ambiguity)
        if len(candidate_lines) != 1:
            continue
        bl = candidate_lines[0]
        bl_id = cast(str, bl.id)
        # That bank line must only candidate for this payout (no N:1 ambiguity)
        if len(line_candidates.get(bl_id, [])) != 1:
            continue

        # Valid unambiguous 1:1 match
        bl.matched_payout_id = p.id
        p.bank_line_id = bl.id
        matches.append((bl_id, p_id))

    session.commit()
    return matches

