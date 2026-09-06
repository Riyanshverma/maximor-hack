"""Tests for engine/matcher.py: payout decomposition and bank tie-out."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.engine.matcher import decompose_payout, match_bank_lines
from backend.app.models.base import Base
from backend.app.models.schema import BankLine, CloseRun, Payout, SettlementEvent

RUN_ID = "run-1"


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(CloseRun(id=RUN_ID, period="2026-08", status="ingest"))
        s.commit()
        yield s


def make_payout(session, payout_id, net, settled_at, currency="USD"):
    payout = Payout(
        id=payout_id,
        run_id=RUN_ID,
        external_id=f"ext-{payout_id}",
        status="completed",
        created_at=settled_at,
        settled_at=settled_at,
        gross=net + Decimal("5.00"),
        fees=Decimal("5.00"),
        net=net,
        currency=currency,
    )
    session.add(payout)
    return payout


def test_decompose_payout_sums_settlement_events(session):
    make_payout(session, "payout-1", Decimal("95.00"), datetime(2026, 8, 10))
    events = [
        SettlementEvent(
            id="evt-1", run_id=RUN_ID, source="dodo", event_type="payment",
            payout_id="payout-1", occurred_at=datetime(2026, 8, 10),
            amount_native=Decimal("100.00"), currency_native="USD",
            amount_payout=Decimal("100.00"), currency_payout="USD",
        ),
        SettlementEvent(
            id="evt-2", run_id=RUN_ID, source="dodo", event_type="fee",
            payout_id="payout-1", occurred_at=datetime(2026, 8, 10),
            amount_native=Decimal("-5.00"), currency_native="USD",
            amount_payout=Decimal("-5.00"), currency_payout="USD",
        ),
        SettlementEvent(
            id="evt-3", run_id=RUN_ID, source="dodo", event_type="refund",
            payout_id="payout-2", occurred_at=datetime(2026, 8, 10),
            amount_native=Decimal("-20.00"), currency_native="USD",
            amount_payout=Decimal("-20.00"), currency_payout="USD",
        ),
    ]
    session.add_all(events)
    session.commit()

    result = decompose_payout(session, RUN_ID, "payout-1")

    assert {e.id for e in result.events} == {"evt-1", "evt-2"}
    assert result.total_amount_payout == Decimal("95.00")


def test_match_bank_lines_clean_1to1_match(session):
    make_payout(session, "payout-1", Decimal("95.00"), datetime(2026, 8, 10))
    bank_line = BankLine(
        id="bank-1", run_id=RUN_ID, posted_at=datetime(2026, 8, 11),
        amount=Decimal("95.00"), currency="USD", description="deposit",
    )
    session.add(bank_line)
    session.commit()

    matches = match_bank_lines(session, RUN_ID)

    assert matches == [("bank-1", "payout-1")]
    refreshed = session.get(BankLine, "bank-1")
    assert refreshed.matched_payout_id == "payout-1"


def test_match_bank_lines_does_not_match_amount_near_miss(session):
    make_payout(session, "payout-1", Decimal("95.00"), datetime(2026, 8, 10))
    bank_line = BankLine(
        id="bank-1", run_id=RUN_ID, posted_at=datetime(2026, 8, 11),
        amount=Decimal("95.01"), currency="USD", description="deposit",
    )
    session.add(bank_line)
    session.commit()

    matches = match_bank_lines(session, RUN_ID)

    assert matches == []
    refreshed = session.get(BankLine, "bank-1")
    assert refreshed.matched_payout_id is None


def test_match_bank_lines_does_not_match_outside_date_window(session):
    make_payout(session, "payout-1", Decimal("95.00"), datetime(2026, 8, 10))
    bank_line = BankLine(
        id="bank-1", run_id=RUN_ID,
        posted_at=datetime(2026, 8, 10) + timedelta(days=4),
        amount=Decimal("95.00"), currency="USD", description="deposit",
    )
    session.add(bank_line)
    session.commit()

    matches = match_bank_lines(session, RUN_ID)

    assert matches == []
    refreshed = session.get(BankLine, "bank-1")
    assert refreshed.matched_payout_id is None


def test_match_bank_lines_sets_bidirectional_foreign_keys(session):
    make_payout(session, "payout-bidi", Decimal("100.00"), datetime(2026, 8, 10))
    bank_line = BankLine(
        id="bank-bidi",
        run_id=RUN_ID,
        posted_at=datetime(2026, 8, 11),
        amount=Decimal("100.00"),
        currency="USD",
        description="deposit",
    )
    session.add(bank_line)
    session.commit()

    matches = match_bank_lines(session, RUN_ID)
    assert matches == [("bank-bidi", "payout-bidi")]

    refreshed_line = session.get(BankLine, "bank-bidi")
    assert refreshed_line is not None
    assert refreshed_line.matched_payout_id == "payout-bidi"

    refreshed_payout = session.get(Payout, "payout-bidi")
    assert refreshed_payout is not None
    assert refreshed_payout.bank_line_id == "bank-bidi"


def test_match_bank_lines_resolves_1_to_n_ambiguity(session):
    """1 payout with multiple matching bank lines must leave both unmatched."""
    make_payout(session, "payout-ambig-1", Decimal("50.00"), datetime(2026, 8, 10))
    bl1 = BankLine(
        id="bank-ambig-1a", run_id=RUN_ID, posted_at=datetime(2026, 8, 10),
        amount=Decimal("50.00"), currency="USD", description="dep1",
    )
    bl2 = BankLine(
        id="bank-ambig-1b", run_id=RUN_ID, posted_at=datetime(2026, 8, 11),
        amount=Decimal("50.00"), currency="USD", description="dep2",
    )
    session.add_all([bl1, bl2])
    session.commit()

    matches = match_bank_lines(session, RUN_ID)
    assert matches == []

    p = session.get(Payout, "payout-ambig-1")
    assert p is not None and p.bank_line_id is None
    assert session.get(BankLine, "bank-ambig-1a").matched_payout_id is None
    assert session.get(BankLine, "bank-ambig-1b").matched_payout_id is None


def test_match_bank_lines_resolves_n_to_1_ambiguity(session):
    """Multiple payouts matching same bank line must leave all unmatched."""
    make_payout(session, "payout-ambig-2a", Decimal("70.00"), datetime(2026, 8, 10))
    make_payout(session, "payout-ambig-2b", Decimal("70.00"), datetime(2026, 8, 11))
    bl = BankLine(
        id="bank-ambig-2", run_id=RUN_ID, posted_at=datetime(2026, 8, 10),
        amount=Decimal("70.00"), currency="USD", description="dep",
    )
    session.add(bl)
    session.commit()

    matches = match_bank_lines(session, RUN_ID)
    assert matches == []

    assert session.get(Payout, "payout-ambig-2a").bank_line_id is None
    assert session.get(Payout, "payout-ambig-2b").bank_line_id is None
    assert session.get(BankLine, "bank-ambig-2").matched_payout_id is None


def test_match_bank_lines_status_filter_and_currency(session):
    """Only paid/completed payouts match; currency must match."""
    p_pending = Payout(
        id="payout-pending", run_id=RUN_ID, external_id="ext-pend",
        status="pending", created_at=datetime(2026, 8, 10),
        settled_at=datetime(2026, 8, 10), gross=Decimal("30.00"),
        fees=Decimal("0.00"), net=Decimal("30.00"), currency="USD",
    )
    p_eur = Payout(
        id="payout-eur", run_id=RUN_ID, external_id="ext-eur",
        status="completed", created_at=datetime(2026, 8, 10),
        settled_at=datetime(2026, 8, 10), gross=Decimal("40.00"),
        fees=Decimal("0.00"), net=Decimal("40.00"), currency="EUR",
    )
    bl_usd = BankLine(
        id="bank-eur-mismatch", run_id=RUN_ID, posted_at=datetime(2026, 8, 10),
        amount=Decimal("40.00"), currency="USD", description="usd dep",
    )
    session.add_all([p_pending, p_eur, bl_usd])
    session.commit()

    matches = match_bank_lines(session, RUN_ID)
    assert matches == []

