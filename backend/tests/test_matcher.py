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
