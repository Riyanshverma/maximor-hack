"""Tests for P6: no orphans between settlement events and journal lines."""
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.contracts import RunContext
from backend.app.engine.proofs.p6 import P6NoOrphans
from backend.app.models.base import Base
from backend.app.models.schema import (
    CloseRun,
    GLAccount,
    JournalEntry,
    JournalLine,
    SettlementEvent,
)

RUN_ID = "run-1"


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(CloseRun(id=RUN_ID, period="2026-08", status="prove"))
        session.add(GLAccount(code="1000", name="Cash", type="asset", normal_side="debit"))
        session.commit()
        yield session


def _settlement_event(event_id: str) -> SettlementEvent:
    return SettlementEvent(
        id=event_id,
        run_id=RUN_ID,
        source="seed",
        event_type="payment",
        occurred_at=datetime(2026, 8, 1),
        amount_native=Decimal("100.0000"),
        currency_native="USD",
        amount_payout=Decimal("100.0000"),
        currency_payout="USD",
    )


def _journal_line(line_id: str, entry_id: str, settlement_event_id: str) -> JournalLine:
    return JournalLine(
        id=line_id,
        entry_id=entry_id,
        account_code="1000",
        debit=Decimal("100.0000"),
        credit=Decimal("0.0000"),
        currency="USD",
        settlement_event_id=settlement_event_id,
    )


def test_clean_case_passes(session):
    session.add(_settlement_event("se-1"))
    session.add(_settlement_event("se-2"))
    session.add(JournalEntry(id="je-1", run_id=RUN_ID, period="2026-08", created_by="agent"))
    session.add(_journal_line("jl-1", "je-1", "se-1"))
    session.add(_journal_line("jl-2", "je-1", "se-2"))
    session.commit()

    result = P6NoOrphans()._evaluate(session, RunContext(run_id=RUN_ID, period="2026-08"))

    assert result.passed is True
    assert result.expected == Decimal("0")
    assert result.actual == Decimal("0")
    assert result.delta == Decimal("0")
    assert result.detail["missing_settlement_events"] == []
    assert result.detail["duplicate_settlement_events"] == []
    assert result.detail["dangling_journal_lines"] == []


def test_missing_settlement_event_fails(session):
    session.add(_settlement_event("se-1"))
    session.add(_settlement_event("se-2"))  # no journal line for this one
    session.add(JournalEntry(id="je-1", run_id=RUN_ID, period="2026-08", created_by="agent"))
    session.add(_journal_line("jl-1", "je-1", "se-1"))
    session.commit()

    result = P6NoOrphans()._evaluate(session, RunContext(run_id=RUN_ID, period="2026-08"))

    assert result.passed is False
    assert result.actual == Decimal("1")
    assert result.delta == Decimal("1")
    assert result.detail["missing_settlement_events"] == ["se-2"]


def test_duplicate_mapped_settlement_event_fails(session):
    session.add(_settlement_event("se-1"))
    session.add(JournalEntry(id="je-1", run_id=RUN_ID, period="2026-08", created_by="agent"))
    session.add(_journal_line("jl-1", "je-1", "se-1"))
    session.add(_journal_line("jl-2", "je-1", "se-1"))  # duplicate mapping
    session.commit()

    result = P6NoOrphans()._evaluate(session, RunContext(run_id=RUN_ID, period="2026-08"))

    assert result.passed is False
    assert result.actual == Decimal("1")
    assert result.detail["duplicate_settlement_events"] == ["se-1"]


def test_multi_line_split_entry_with_designated_clearing_line(session):
    """Multi-line split entry maps via designated clearing line 1310 without duplicate error."""
    session.add(_settlement_event("se-split"))
    session.add(JournalEntry(id="je-split", run_id=RUN_ID, period="2026-08", created_by="agent"))

    # Line 1: Clearing line (1310) carries settlement_event_id
    session.add(
        JournalLine(
            id="jl-s1",
            entry_id="je-split",
            account_code="1310",
            debit=Decimal("110.00"),
            credit=Decimal("0.00"),
            currency="USD",
            settlement_event_id="se-split",
        )
    )
    # Line 2: Revenue split (4010) also tagged with settlement_event_id
    session.add(
        JournalLine(
            id="jl-s2",
            entry_id="je-split",
            account_code="4010",
            debit=Decimal("0.00"),
            credit=Decimal("100.00"),
            currency="USD",
            settlement_event_id="se-split",
        )
    )
    # Line 3: Tax split (2100) also tagged with settlement_event_id
    session.add(
        JournalLine(
            id="jl-s3",
            entry_id="je-split",
            account_code="2100",
            debit=Decimal("0.00"),
            credit=Decimal("10.00"),
            currency="USD",
            settlement_event_id="se-split",
        )
    )
    session.commit()

    result = P6NoOrphans().evaluate(RunContext(run_id=RUN_ID, period="2026-08"), session=session)

    assert result.passed is True
    assert result.actual == Decimal("0")
    assert result.detail["duplicate_settlement_events"] == []
    assert result.detail["missing_settlement_events"] == []


def test_dangling_journal_line_fails(session):
    """Journal line referencing a non-existent settlement event is detected as dangling."""
    session.add(JournalEntry(id="je-dang", run_id=RUN_ID, period="2026-08", created_by="agent"))
    session.add(
        JournalLine(
            id="jl-dang",
            entry_id="je-dang",
            account_code="1000",
            debit=Decimal("50.00"),
            credit=Decimal("0.00"),
            currency="USD",
            settlement_event_id="se-nonexistent",
        )
    )
    session.commit()

    result = P6NoOrphans().evaluate(RunContext(run_id=RUN_ID, period="2026-08"), session=session)

    assert result.passed is False
    assert result.actual == Decimal("1")
    assert "se-nonexistent" in result.detail["dangling_journal_lines"]

