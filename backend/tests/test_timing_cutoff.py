"""Tests for TIMING_CUTOFF (taxonomy type 6) exception handler."""
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.contracts import RunContext
from backend.app.engine.handlers.timing_cutoff import TimingCutoffHandler
from backend.app.models.base import Base
from backend.app.models.schema import CloseRun, Payout, SettlementEvent

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
        s.commit()
        yield s


def _payout(session, pid, created, settled, net="100.00"):
    session.add(
        Payout(
            id=pid,
            run_id=RUN_ID,
            external_id=f"ext-{pid}",
            status="completed",
            created_at=created,
            settled_at=settled,
            gross=Decimal(net),
            fees=Decimal("0.00"),
            net=Decimal(net),
            currency="USD",
        )
    )


def test_boundary_spanning_payout_triggers(session):
    _payout(session, "p1", datetime(2026, 8, 31, 23, 0), datetime(2026, 9, 1, 1, 0))
    session.commit()
    drafts = TimingCutoffHandler().detect(RunContext(run_id=RUN_ID, period=PERIOD), session=session)
    assert len(drafts) == 1
    assert drafts[0].type == "TIMING_CUTOFF"
    assert drafts[0].evidence["created_period"] == "2026-08"
    assert drafts[0].evidence["settled_period"] == "2026-09"


def test_same_period_near_miss_does_not_trigger(session):
    _payout(session, "p2", datetime(2026, 8, 10), datetime(2026, 8, 12))
    session.commit()
    drafts = TimingCutoffHandler().detect(RunContext(run_id=RUN_ID, period=PERIOD), session=session)
    assert drafts == []


def test_gather_hypothesize_propose_flow(session):
    _payout(session, "p3", datetime(2026, 8, 31), datetime(2026, 9, 2), net="50.00")
    session.add(
        SettlementEvent(
            id="se-1",
            run_id=RUN_ID,
            source="seed",
            event_type="payment",
            payout_id="p3",
            occurred_at=datetime(2026, 8, 31),
            amount_native=Decimal("50.00"),
            currency_native="USD",
            amount_payout=Decimal("50.00"),
            currency_payout="USD",
        )
    )
    session.commit()
    ctx = RunContext(run_id=RUN_ID, period=PERIOD)
    handler = TimingCutoffHandler()
    drafts = handler.detect(ctx, session=session)
    assert len(drafts) == 1
    evidence = handler.gather(drafts[0], ctx, session=session)
    assert evidence["payout"]["id"] == "p3"
    assert len(evidence["constituent_entries"]) == 1
    hyps = handler.hypothesize(drafts[0], evidence)
    assert hyps[0]["root_cause"] == "period_boundary_lag"
    remedy = handler.propose(drafts[0], hyps[0])
    assert remedy["route"] == "AUTO"
    assert remedy["debit_account"] == "1330"


def test_material_amount_escalates(session):
    _payout(session, "p4", datetime(2026, 8, 31), datetime(2026, 9, 1), net="500.00")
    session.commit()
    ctx = RunContext(run_id=RUN_ID, period=PERIOD)
    handler = TimingCutoffHandler()
    drafts = handler.detect(ctx, session=session)
    evidence = handler.gather(drafts[0], ctx, session=session)
    remedy = handler.propose(drafts[0], handler.hypothesize(drafts[0], evidence)[0])
    assert remedy["route"] == "ESCALATE"


def test_compile_rule_shape():
    from backend.app.contracts import ExceptionDraft

    exc = ExceptionDraft(
        type="TIMING_CUTOFF",
        severity="medium",
        amount=Decimal("10.00"),
        confidence=Decimal("1.0"),
        evidence={"payout_id": "p"},
    )
    rule = TimingCutoffHandler().compile_rule(exc, {"rationale": "ok"})
    assert rule["name"] == "cutoff_policy"


def test_build_priority_and_type():
    handler = TimingCutoffHandler()
    assert handler.type == "TIMING_CUTOFF"
    assert handler.build_priority == 6
