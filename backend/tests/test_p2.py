"""Tests for P2: payout net must equal the sum of its settlement event components."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.contracts import RunContext
from backend.app.engine.proofs.p2 import P2PayoutComponentsSum
from backend.app.models.base import Base
from backend.app.models.schema import CloseRun, Payout, SettlementEvent


def _make_engine(tmp_path):
    db_url = f"sqlite:///{tmp_path}/test.db"
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    return db_url, engine


def _seed(session, event_amounts):
    session.add(CloseRun(id="run-1", period="2026-08", status="prove"))
    session.add(
        Payout(
            id="payout-1",
            run_id="run-1",
            external_id="ext-1",
            status="completed",
            created_at=datetime(2026, 8, 1),
            gross=Decimal("100.00"),
            fees=Decimal("5.00"),
            net=Decimal("95.00"),
            currency="USD",
        )
    )
    for i, amount in enumerate(event_amounts):
        session.add(
            SettlementEvent(
                id=f"event-{i}",
                run_id="run-1",
                source="seed",
                event_type="payment",
                payout_id="payout-1",
                occurred_at=datetime(2026, 8, 1),
                amount_native=amount,
                currency_native="USD",
                amount_payout=amount,
                currency_payout="USD",
            )
        )
    session.commit()


def test_p2_passes_when_components_sum_to_net(tmp_path, monkeypatch):
    db_url, engine = _make_engine(tmp_path)
    monkeypatch.setenv("DATABASE_URL", db_url)

    with Session(engine) as session:
        _seed(session, [Decimal("60.00"), Decimal("35.00")])

    result = P2PayoutComponentsSum().evaluate(RunContext(run_id="run-1", period="2026-08"))

    assert result.passed is True
    assert result.delta == Decimal("0")
    assert result.expected == Decimal("95.00")
    assert result.actual == Decimal("95.00")
    assert result.detail["failures"] == []


def test_p2_fails_on_off_by_one_cent(tmp_path, monkeypatch):
    db_url, engine = _make_engine(tmp_path)
    monkeypatch.setenv("DATABASE_URL", db_url)

    with Session(engine) as session:
        _seed(session, [Decimal("60.01"), Decimal("35.00")])

    result = P2PayoutComponentsSum().evaluate(RunContext(run_id="run-1", period="2026-08"))

    assert result.passed is False
    assert result.delta == Decimal("0.01")
    assert len(result.detail["failures"]) == 1
