"""Tests for the FX_VARIANCE exception handler."""
import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.contracts import ExceptionDraft, RunContext
from backend.app.engine.handlers.fx_variance import (
    AUTO_RESOLVE_LIMIT,
    FX_GAIN_LOSS_ACCOUNT,
    FXVarianceHandler,
)
from backend.app.models.base import Base
from backend.app.models.schema import CloseRun, Payout, SettlementEvent


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'test_fx_variance.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_run(session: Session, run_id: str) -> None:
    session.add(CloseRun(id=run_id, period="2026-08", status="prove"))


def _make_payout(session: Session, run_id: str, payout_id: str, net: Decimal) -> None:
    occurred_at = datetime(2026, 8, 11, 10, 0, 0)
    session.add(
        Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext_{payout_id}",
            status="completed",
            created_at=occurred_at,
            settled_at=occurred_at,
            gross=net,
            fees=Decimal("0.00"),
            net=net,
            currency="USD",
        )
    )


def _make_settlement_event(
    session: Session,
    run_id: str,
    payout_id: str,
    event_id: str,
    amount_payout: Decimal,
    rate_booked: Decimal,
    rate_settled: Decimal,
    fx_source: str | None = "dodo_spot_rate",
) -> None:
    session.add(
        SettlementEvent(
            id=event_id,
            run_id=run_id,
            source="seed",
            external_id=f"evt_{event_id}",
            event_type="payment",
            payout_id=payout_id,
            order_id=f"ord_{event_id}",
            customer_id=f"cust_{event_id}",
            occurred_at=datetime(2026, 8, 11, 10, 0, 0),
            amount_native=amount_payout,
            currency_native="USD",
            amount_payout=amount_payout,
            currency_payout="USD",
            fx_rate=rate_settled,
            fx_source=fx_source,
            raw={
                "booked_fx_rate": str(rate_booked),
                "settled_fx_rate": str(rate_settled),
            },
        )
    )


def test_detects_planted_fx_variance_trigger(db_session):
    """Matches generator.plant_fx_variance_august: booked 1.00, settled 1.08, net 3800.00."""
    run_id = str(uuid.uuid4())
    payout_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    _make_run(db_session, run_id)
    _make_payout(db_session, run_id, payout_id, Decimal("3800.00"))
    _make_settlement_event(
        db_session,
        run_id,
        payout_id,
        event_id,
        amount_payout=Decimal("3800.00"),
        rate_booked=Decimal("1.00"),
        rate_settled=Decimal("1.08"),
    )
    db_session.commit()

    drafts = FXVarianceHandler().detect(RunContext(run_id=run_id, period="2026-08"))

    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.type == "FX_VARIANCE"
    assert draft.amount == Decimal("304.00")
    assert draft.severity == "medium"  # >= $250, must escalate
    assert Decimal(draft.evidence["rate_booked"]) == Decimal("1.00")
    assert Decimal(draft.evidence["rate_settled"]) == Decimal("1.08")


def test_near_miss_within_band_is_not_detected(db_session):
    """Variance of 0.4% is under the 0.5% threshold and must not be flagged."""
    run_id = str(uuid.uuid4())
    payout_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    _make_run(db_session, run_id)
    _make_payout(db_session, run_id, payout_id, Decimal("1000.00"))
    _make_settlement_event(
        db_session,
        run_id,
        payout_id,
        event_id,
        amount_payout=Decimal("1000.00"),
        rate_booked=Decimal("1.000"),
        rate_settled=Decimal("1.004"),  # 0.4% variance, below the 0.5% band
    )
    db_session.commit()

    drafts = FXVarianceHandler().detect(RunContext(run_id=run_id, period="2026-08"))

    assert drafts == []


def test_near_miss_above_auto_resolve_limit_must_not_auto_resolve(db_session):
    """Variance impact >= $250 is detected but propose() must not mark it auto-eligible."""
    run_id = str(uuid.uuid4())
    payout_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    _make_run(db_session, run_id)
    _make_payout(db_session, run_id, payout_id, Decimal("5000.00"))
    _make_settlement_event(
        db_session,
        run_id,
        payout_id,
        event_id,
        amount_payout=Decimal("5000.00"),
        rate_booked=Decimal("1.00"),
        rate_settled=Decimal("1.05"),  # 5% variance, impact = $250.00
    )
    db_session.commit()

    handler = FXVarianceHandler()
    drafts = handler.detect(RunContext(run_id=run_id, period="2026-08"))

    assert len(drafts) == 1
    assert drafts[0].amount == AUTO_RESOLVE_LIMIT
    remedy = handler.propose(drafts[0], hypothesis={})
    assert remedy is not None
    assert remedy["auto_eligible"] is False


def test_auto_resolve_eligible_under_threshold(db_session):
    """Variance impact under $250 with a known rate source is auto-eligible for 7410."""
    run_id = str(uuid.uuid4())
    payout_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    _make_run(db_session, run_id)
    _make_payout(db_session, run_id, payout_id, Decimal("1000.00"))
    _make_settlement_event(
        db_session,
        run_id,
        payout_id,
        event_id,
        amount_payout=Decimal("1000.00"),
        rate_booked=Decimal("1.00"),
        rate_settled=Decimal("1.02"),  # 2% variance, impact = $20.00
    )
    db_session.commit()

    handler = FXVarianceHandler()
    drafts = handler.detect(RunContext(run_id=run_id, period="2026-08"))

    assert len(drafts) == 1
    assert drafts[0].severity == "low"
    remedy = handler.propose(drafts[0], hypothesis={})
    assert remedy is not None
    assert remedy["auto_eligible"] is True
    assert remedy["account_code"] == FX_GAIN_LOSS_ACCOUNT


def test_ambiguous_rate_source_forces_escalation(db_session):
    """A missing fx_source is ambiguous and must escalate regardless of amount."""
    run_id = str(uuid.uuid4())
    payout_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    _make_run(db_session, run_id)
    _make_payout(db_session, run_id, payout_id, Decimal("1000.00"))
    _make_settlement_event(
        db_session,
        run_id,
        payout_id,
        event_id,
        amount_payout=Decimal("1000.00"),
        rate_booked=Decimal("1.00"),
        rate_settled=Decimal("1.02"),  # impact = $20.00, well under $250
        fx_source=None,
    )
    db_session.commit()

    handler = FXVarianceHandler()
    drafts = handler.detect(RunContext(run_id=run_id, period="2026-08"))

    assert len(drafts) == 1
    assert drafts[0].severity == "medium"
    remedy = handler.propose(drafts[0], hypothesis={})
    assert remedy is not None
    assert remedy["auto_eligible"] is False


def test_gather_attaches_settlement_event_and_invoice_evidence(db_session):
    run_id = str(uuid.uuid4())
    payout_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    _make_run(db_session, run_id)
    _make_payout(db_session, run_id, payout_id, Decimal("3800.00"))
    _make_settlement_event(
        db_session,
        run_id,
        payout_id,
        event_id,
        amount_payout=Decimal("3800.00"),
        rate_booked=Decimal("1.00"),
        rate_settled=Decimal("1.08"),
    )
    db_session.commit()

    handler = FXVarianceHandler()
    ctx = RunContext(run_id=run_id, period="2026-08")
    draft = handler.detect(ctx)[0]
    evidence = handler.gather(draft, ctx)

    assert evidence["settlement_event"]["id"] == event_id
    assert evidence["source_invoice"] is None  # no invoice planted for this fixture
    assert Decimal(evidence["rate_booked"]) == Decimal("1.00")
    assert Decimal(evidence["rate_settled"]) == Decimal("1.08")


def test_compile_rule_shape():
    handler = FXVarianceHandler()
    dummy_exc = ExceptionDraft(
        type="FX_VARIANCE",
        severity="medium",
        amount=Decimal("304.00"),
        confidence=Decimal("1.0"),
        evidence={},
    )
    rule = handler.compile_rule(
        dummy_exc, ruling={"currency": "USD", "id": "ruling-1"}
    )
    assert rule is not None
    assert rule["name"] == "fx_variance_threshold"
    assert rule["action"]["post_account"] == FX_GAIN_LOSS_ACCOUNT
    assert rule["predicate"]["currency"] == "USD"
