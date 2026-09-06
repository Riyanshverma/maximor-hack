"""Tests for P1: journal entry debit/credit balance proof obligation."""
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.contracts import RunContext
from backend.app.engine.proofs.p1 import P1DebitCreditBalance
from backend.app.models.base import Base
from backend.app.models.schema import CloseRun, GLAccount, JournalEntry, JournalLine

RUN_ID = "run-1"
PERIOD = "2026-08"


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(CloseRun(id=RUN_ID, period=PERIOD, status="prove"))
        s.add(GLAccount(code="1000", name="Cash", type="asset", normal_side="debit"))
        s.add(GLAccount(code="4000", name="Revenue", type="revenue", normal_side="credit"))
        s.commit()
        yield s


def _add_entry(session, entry_id: str, debit: Decimal, credit: Decimal) -> None:
    session.add(
        JournalEntry(id=entry_id, run_id=RUN_ID, period=PERIOD, created_by="rule")
    )
    session.add(
        JournalLine(
            id=f"{entry_id}-debit",
            entry_id=entry_id,
            account_code="1000",
            debit=debit,
            credit=Decimal("0"),
            currency="USD",
        )
    )
    session.add(
        JournalLine(
            id=f"{entry_id}-credit",
            entry_id=entry_id,
            account_code="4000",
            debit=Decimal("0"),
            credit=credit,
            currency="USD",
        )
    )
    session.commit()


def test_p1_passes_when_all_entries_balance(session):
    _add_entry(session, "entry-1", Decimal("100.00"), Decimal("100.00"))
    _add_entry(session, "entry-2", Decimal("50.25"), Decimal("50.25"))

    ctx = RunContext(run_id=RUN_ID, period=PERIOD)
    result = P1DebitCreditBalance().evaluate(ctx, session=session)

    assert result.id == "P1"
    assert result.passed is True
    assert result.expected == Decimal("0.00")
    assert result.actual == Decimal("0.00")
    assert result.delta == Decimal("0.00")


def test_p1_fails_on_one_cent_imbalance(session):
    _add_entry(session, "entry-1", Decimal("100.00"), Decimal("100.00"))
    _add_entry(session, "entry-2", Decimal("100.01"), Decimal("100.00"))

    ctx = RunContext(run_id=RUN_ID, period=PERIOD)
    result = P1DebitCreditBalance().evaluate(ctx, session=session)

    assert result.passed is False
    assert result.delta == Decimal("0.01")
    assert result.detail["imbalanced_entries"][0]["entry_id"] == "entry-2"
