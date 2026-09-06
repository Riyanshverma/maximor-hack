"""Tests for P4 bank tie-out proof obligation."""
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.contracts import RunContext
from backend.app.engine.proofs.p4 import P4BankTieOut
from backend.app.models.base import Base
from backend.app.models.schema import BankLine, CloseRun, Payout


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'test_p4.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_run(session: Session, run_id: str) -> None:
    session.add(CloseRun(id=run_id, period="2026-08", status="prove"))


def _make_payout(
    session: Session, run_id: str, payout_id: str, net: Decimal, settled_at: datetime
) -> None:
    session.add(
        Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"po_{payout_id}",
            status="completed",
            created_at=settled_at - timedelta(days=1),
            settled_at=settled_at,
            gross=net,
            fees=Decimal("0.00"),
            net=net,
            currency="USD",
        )
    )


def _make_bank_line(
    session: Session,
    run_id: str,
    line_id: str,
    amount: Decimal,
    posted_at: datetime,
    matched_payout_id: str | None,
) -> None:
    session.add(
        BankLine(
            id=line_id,
            run_id=run_id,
            posted_at=posted_at,
            amount=amount,
            currency="USD",
            matched_payout_id=matched_payout_id,
        )
    )


def test_p4_passes_when_every_payout_has_one_correctly_matched_bank_line(db_session):
    run_id = str(uuid.uuid4())
    _make_run(db_session, run_id)

    settled_at = datetime(2026, 8, 15)
    payout_a = str(uuid.uuid4())
    payout_b = str(uuid.uuid4())
    _make_payout(db_session, run_id, payout_a, Decimal("1000.00"), settled_at)
    _make_payout(db_session, run_id, payout_b, Decimal("250.50"), settled_at)
    _make_bank_line(
        db_session, run_id, str(uuid.uuid4()), Decimal("1000.00"),
        settled_at + timedelta(days=2), payout_a,
    )
    _make_bank_line(
        db_session, run_id, str(uuid.uuid4()), Decimal("250.50"),
        settled_at + timedelta(days=1), payout_b,
    )
    db_session.commit()

    result = P4BankTieOut().evaluate(RunContext(run_id=run_id, period="2026-08"))

    assert result.passed
    assert result.id == "P4"
    assert result.actual == Decimal("0.00")
    assert result.delta == Decimal("0.00")
    assert result.detail["failures"] == []


def test_p4_fails_on_unmatched_payout(db_session):
    run_id = str(uuid.uuid4())
    _make_run(db_session, run_id)

    settled_at = datetime(2026, 8, 15)
    matched_id = str(uuid.uuid4())
    _make_payout(db_session, run_id, matched_id, Decimal("500.00"), settled_at)
    _make_bank_line(
        db_session, run_id, str(uuid.uuid4()), Decimal("500.00"),
        settled_at + timedelta(days=1), matched_id,
    )

    unmatched_id = str(uuid.uuid4())
    _make_payout(db_session, run_id, unmatched_id, Decimal("750.00"), settled_at)
    db_session.commit()

    result = P4BankTieOut().evaluate(RunContext(run_id=run_id, period="2026-08"))

    assert not result.passed
    assert result.actual == Decimal("1.00")
    assert len(result.detail["failures"]) == 1
    assert result.detail["failures"][0]["payout_id"] == unmatched_id


def test_p4_fails_on_amount_mismatch(db_session):
    run_id = str(uuid.uuid4())
    _make_run(db_session, run_id)

    settled_at = datetime(2026, 8, 15)
    payout_id = str(uuid.uuid4())
    _make_payout(db_session, run_id, payout_id, Decimal("500.00"), settled_at)
    _make_bank_line(
        db_session, run_id, str(uuid.uuid4()), Decimal("499.00"),
        settled_at + timedelta(days=1), payout_id,
    )
    db_session.commit()

    result = P4BankTieOut().evaluate(RunContext(run_id=run_id, period="2026-08"))

    assert not result.passed
    assert result.actual == Decimal("1.00")
    assert "amount mismatch" in result.detail["failures"][0]["reason"]


def test_p4_fails_on_currency_mismatch(db_session):
    run_id = str(uuid.uuid4())
    _make_run(db_session, run_id)

    settled_at = datetime(2026, 8, 15)
    payout_id = str(uuid.uuid4())
    _make_payout(db_session, run_id, payout_id, Decimal("500.00"), settled_at)
    # Bank line in EUR while payout is USD
    db_session.add(
        BankLine(
            id=str(uuid.uuid4()),
            run_id=run_id,
            posted_at=settled_at + timedelta(days=1),
            amount=Decimal("500.00"),
            currency="EUR",
            matched_payout_id=payout_id,
        )
    )
    db_session.commit()

    result = P4BankTieOut().evaluate(RunContext(run_id=run_id, period="2026-08"))
    assert not result.passed
    assert result.actual == Decimal("1.00")
    assert "currency mismatch" in result.detail["failures"][0]["reason"]


def test_p4_symmetric_3_day_window(db_session):
    run_id = str(uuid.uuid4())
    _make_run(db_session, run_id)

    settled_at = datetime(2026, 8, 15)

    # 1. Negative offset: posted 2 days before settled_at -> should PASS
    payout_early = str(uuid.uuid4())
    _make_payout(db_session, run_id, payout_early, Decimal("100.00"), settled_at)
    _make_bank_line(
        db_session, run_id, str(uuid.uuid4()), Decimal("100.00"),
        settled_at - timedelta(days=2), payout_early,
    )

    # 2. Positive offset: posted 3 days after settled_at -> should PASS
    payout_late = str(uuid.uuid4())
    _make_payout(db_session, run_id, payout_late, Decimal("200.00"), settled_at)
    _make_bank_line(
        db_session, run_id, str(uuid.uuid4()), Decimal("200.00"),
        settled_at + timedelta(days=3), payout_late,
    )
    db_session.commit()

    result = P4BankTieOut().evaluate(RunContext(run_id=run_id, period="2026-08"))
    assert result.passed
    assert result.delta == Decimal("0.00")


def test_p4_fails_outside_3_day_window(db_session):
    run_id = str(uuid.uuid4())
    _make_run(db_session, run_id)

    settled_at = datetime(2026, 8, 15)

    # Posted 4 days before settled_at -> should FAIL
    payout_past = str(uuid.uuid4())
    _make_payout(db_session, run_id, payout_past, Decimal("100.00"), settled_at)
    _make_bank_line(
        db_session, run_id, str(uuid.uuid4()), Decimal("100.00"),
        settled_at - timedelta(days=4), payout_past,
    )

    # Posted 4 days after settled_at -> should FAIL
    payout_future = str(uuid.uuid4())
    _make_payout(db_session, run_id, payout_future, Decimal("200.00"), settled_at)
    _make_bank_line(
        db_session, run_id, str(uuid.uuid4()), Decimal("200.00"),
        settled_at + timedelta(days=4), payout_future,
    )
    db_session.commit()

    result = P4BankTieOut().evaluate(RunContext(run_id=run_id, period="2026-08"))
    assert not result.passed
    assert result.actual == Decimal("2.00")
    assert len(result.detail["failures"]) == 2
    assert any("outside +/- 3 day window" in f["reason"] for f in result.detail["failures"])


def test_p4_checks_paid_status_and_ignores_pending(db_session):
    run_id = str(uuid.uuid4())
    _make_run(db_session, run_id)

    settled_at = datetime(2026, 8, 15)

    # Payout with status="paid" but no bank line -> MUST fail
    payout_paid = str(uuid.uuid4())
    db_session.add(
        Payout(
            id=payout_paid,
            run_id=run_id,
            external_id=f"po_{payout_paid}",
            status="paid",
            created_at=settled_at - timedelta(days=1),
            settled_at=settled_at,
            gross=Decimal("300.00"),
            fees=Decimal("0.00"),
            net=Decimal("300.00"),
            currency="USD",
        )
    )

    # Payout with status="pending" (not settled) -> should NOT be checked by P4
    payout_pending = str(uuid.uuid4())
    db_session.add(
        Payout(
            id=payout_pending,
            run_id=run_id,
            external_id=f"po_{payout_pending}",
            status="pending",
            created_at=settled_at - timedelta(days=1),
            settled_at=None,
            gross=Decimal("400.00"),
            fees=Decimal("0.00"),
            net=Decimal("400.00"),
            currency="USD",
        )
    )
    db_session.commit()

    result = P4BankTieOut().evaluate(RunContext(run_id=run_id, period="2026-08"))
    assert not result.passed
    assert result.actual == Decimal("1.00")
    assert result.detail["failures"][0]["payout_id"] == payout_paid


def test_p4_supports_bidirectional_foreign_keys(db_session):
    run_id = str(uuid.uuid4())
    _make_run(db_session, run_id)

    settled_at = datetime(2026, 8, 15)
    payout_id = str(uuid.uuid4())
    line_id = str(uuid.uuid4())

    payout = Payout(
        id=payout_id,
        run_id=run_id,
        external_id=f"po_{payout_id}",
        status="paid",
        created_at=settled_at - timedelta(days=1),
        settled_at=settled_at,
        gross=Decimal("500.00"),
        fees=Decimal("0.00"),
        net=Decimal("500.00"),
        currency="USD",
        bank_line_id=line_id,
    )
    bank_line = BankLine(
        id=line_id,
        run_id=run_id,
        posted_at=settled_at + timedelta(days=1),
        amount=Decimal("500.00"),
        currency="USD",
        matched_payout_id=payout_id,
    )
    db_session.add(payout)
    db_session.add(bank_line)
    db_session.commit()

    result = P4BankTieOut().evaluate(RunContext(run_id=run_id, period="2026-08"))
    assert result.passed
    assert result.delta == Decimal("0.00")

