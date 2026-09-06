"""Tests for P3: clearing account rollforward proof obligation."""
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.contracts import RunContext
from backend.app.engine.proofs.p3 import P3
from backend.app.models.base import Base
from backend.app.models.schema import CloseRun, Payout, SettlementEvent


@pytest.fixture
def db_url(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/p3_test.db"
    monkeypatch.setenv("DATABASE_URL", url)
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    return url


def _settlement_event(run_id, payout_id, event_type, amount, occurred_at, event_id):
    return SettlementEvent(
        id=event_id,
        run_id=run_id,
        source="seed",
        external_id=f"evt_{event_id}",
        event_type=event_type,
        payout_id=payout_id,
        occurred_at=occurred_at,
        amount_native=amount,
        currency_native="USD",
        amount_payout=amount,
        currency_payout="USD",
    )


def test_p3_passes_when_rollforward_nets_to_zero(db_url):
    engine = create_engine(db_url)
    run_id = "run_clean"
    payout_id = "po_clean"
    occurred_at = datetime(2026, 8, 1)

    with Session(engine) as session:
        session.add(CloseRun(id=run_id, period="2026-08", status="prove"))
        session.add(
            Payout(
                id=payout_id,
                run_id=run_id,
                external_id="ext_1",
                status="completed",
                created_at=occurred_at,
                gross=Decimal("1000.00"),
                fees=Decimal("50.00"),
                net=Decimal("950.00"),
                currency="USD",
            )
        )
        session.add(
            _settlement_event(run_id, payout_id, "payment", Decimal("1000.00"), occurred_at, "se_1")
        )
        session.add(
            _settlement_event(
                run_id, payout_id, "processing_fee", Decimal("-50.00"), occurred_at, "se_2"
            )
        )
        session.commit()

    result = P3().evaluate(RunContext(run_id=run_id, period="2026-08"))

    assert result.id == "P3"
    assert result.passed is True
    assert result.expected == Decimal("0.00")
    assert result.actual == Decimal("0.00")
    assert result.delta == Decimal("0.00")


def test_p3_fails_with_residual_matching_demo_scenario(db_url):
    engine = create_engine(db_url)
    run_id = "run_residual"
    payout_id = "po_residual"
    occurred_at = datetime(2026, 8, 1)
    residual = Decimal("4812.50")

    with Session(engine) as session:
        session.add(CloseRun(id=run_id, period="2026-08", status="prove"))
        session.add(
            Payout(
                id=payout_id,
                run_id=run_id,
                external_id="ext_2",
                status="completed",
                created_at=occurred_at,
                gross=Decimal("10000.00"),
                fees=Decimal("500.00"),
                net=Decimal("9500.00"),
                currency="USD",
            )
        )
        # Events sum to 14312.50, leaving a 4812.50 gap vs payout.net 9500.00
        session.add(
            _settlement_event(
                run_id, payout_id, "payment", Decimal("14812.50"), occurred_at, "se_3"
            )
        )
        session.add(
            _settlement_event(
                run_id, payout_id, "processing_fee", Decimal("-500.00"), occurred_at, "se_4"
            )
        )
        session.commit()

    result = P3().evaluate(RunContext(run_id=run_id, period="2026-08"))

    assert result.passed is False
    assert result.expected == Decimal("0.00")
    assert result.actual == residual
    assert result.delta == residual
