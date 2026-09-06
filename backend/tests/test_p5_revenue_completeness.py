"""Tests for P5 revenue completeness proof obligation."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.contracts import RunContext
from backend.app.engine.proofs.p5 import P5RevenueCompleteness
from backend.app.models.base import Base
from backend.app.models.schema import CloseRun, Invoice, SettlementEvent


def _make_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine


def _seed_run(session: Session, run_id: str) -> None:
    session.add(
        CloseRun(id=run_id, period="2026-08", status="prove")
    )


def test_p5_passes_when_recognized_equals_invoiced_net_of_contra():
    engine = _make_engine()
    run_id = "run_p5_clean"

    with Session(engine) as session:
        _seed_run(session, run_id)
        session.add(
            Invoice(
                id="inv_1",
                run_id=run_id,
                external_id="ext_1",
                customer_id="cust_1",
                issued_at=datetime.utcnow(),
                subtotal=Decimal("900.00"),
                tax=Decimal("0.00"),
                total=Decimal("900.00"),
                currency="USD",
            )
        )
        session.add_all(
            [
                SettlementEvent(
                    id="evt_payment",
                    run_id=run_id,
                    source="seed",
                    event_type="payment",
                    occurred_at=datetime.utcnow(),
                    amount_native=Decimal("1000.00"),
                    currency_native="USD",
                    amount_payout=Decimal("1000.00"),
                    currency_payout="USD",
                ),
                SettlementEvent(
                    id="evt_refund",
                    run_id=run_id,
                    source="seed",
                    event_type="refund",
                    occurred_at=datetime.utcnow(),
                    amount_native=Decimal("-100.00"),
                    currency_native="USD",
                    amount_payout=Decimal("-100.00"),
                    currency_payout="USD",
                ),
            ]
        )
        session.commit()

    ctx = RunContext(run_id=run_id, period="2026-08")
    result = P5RevenueCompleteness().evaluate(ctx, engine=engine)

    assert result.passed is True
    assert result.expected == Decimal("900.00")
    assert result.actual == Decimal("900.00")
    assert result.delta == Decimal("0.00")


def test_p5_fails_on_one_cent_mismatch():
    engine = _make_engine()
    run_id = "run_p5_mismatch"

    with Session(engine) as session:
        _seed_run(session, run_id)
        session.add(
            Invoice(
                id="inv_1",
                run_id=run_id,
                external_id="ext_1",
                customer_id="cust_1",
                issued_at=datetime.utcnow(),
                subtotal=Decimal("900.01"),
                tax=Decimal("0.00"),
                total=Decimal("900.01"),
                currency="USD",
            )
        )
        session.add_all(
            [
                SettlementEvent(
                    id="evt_payment",
                    run_id=run_id,
                    source="seed",
                    event_type="payment",
                    occurred_at=datetime.utcnow(),
                    amount_native=Decimal("1000.00"),
                    currency_native="USD",
                    amount_payout=Decimal("1000.00"),
                    currency_payout="USD",
                ),
                SettlementEvent(
                    id="evt_refund",
                    run_id=run_id,
                    source="seed",
                    event_type="refund",
                    occurred_at=datetime.utcnow(),
                    amount_native=Decimal("-100.00"),
                    currency_native="USD",
                    amount_payout=Decimal("-100.00"),
                    currency_payout="USD",
                ),
            ]
        )
        session.commit()

    ctx = RunContext(run_id=run_id, period="2026-08")
    result = P5RevenueCompleteness().evaluate(ctx, engine=engine)

    assert result.passed is False
    assert result.delta == Decimal("0.01")
