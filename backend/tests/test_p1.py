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


def test_p1_fails_on_currency_mismatch(session):
    # Debit in USD, Credit in EUR with same numeral (100.00)
    session.add(
        JournalEntry(id="entry-curr", run_id=RUN_ID, period=PERIOD, created_by="rule")
    )
    session.add(
        JournalLine(
            id="entry-curr-debit",
            entry_id="entry-curr",
            account_code="1000",
            debit=Decimal("100.00"),
            credit=Decimal("0.00"),
            currency="USD",
        )
    )
    session.add(
        JournalLine(
            id="entry-curr-credit",
            entry_id="entry-curr",
            account_code="4000",
            debit=Decimal("0.00"),
            credit=Decimal("100.00"),
            currency="EUR",
        )
    )
    session.commit()

    ctx = RunContext(run_id=RUN_ID, period=PERIOD)
    result = P1DebitCreditBalance().evaluate(ctx, session=session)

    assert result.passed is False
    assert result.delta > Decimal("0.00")
    assert any("mixed-currency" in e.get("reason", "") for e in result.detail["imbalanced_entries"])


def test_p1_rejects_non_finite_decimal():
    from backend.app.engine.proofs.p1 import _to_finite_decimal

    with pytest.raises(ValueError, match="Non-finite decimal"):
        _to_finite_decimal(Decimal("NaN"))
    with pytest.raises(ValueError, match="Non-finite decimal"):
        _to_finite_decimal(Decimal("Infinity"))
    with pytest.raises(ValueError, match="Non-finite decimal"):
        _to_finite_decimal(Decimal("-Infinity"))


def test_p1_formats_deltas_as_strings_in_detail(session):
    _add_entry(session, "entry-diff", Decimal("100.50"), Decimal("100.00"))

    ctx = RunContext(run_id=RUN_ID, period=PERIOD)
    result = P1DebitCreditBalance().evaluate(ctx, session=session)

    assert result.passed is False
    imbalanced = [e for e in result.detail["imbalanced_entries"] if e["entry_id"] == "entry-diff"]
    assert len(imbalanced) == 1
    assert isinstance(imbalanced[0]["delta"], str)
    assert isinstance(imbalanced[0]["debit"], str)
    assert isinstance(imbalanced[0]["credit"], str)

