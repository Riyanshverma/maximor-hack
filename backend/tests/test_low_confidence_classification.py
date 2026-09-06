"""Tests for LOW_CONFIDENCE_CLASSIFICATION (taxonomy type 12) handler."""
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.contracts import ExceptionDraft, RunContext
from backend.app.engine.handlers.low_confidence_classification import (
    LowConfidenceClassificationHandler,
)
from backend.app.models.base import Base
from backend.app.models.schema import CloseRun, SettlementEvent

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


def _event(session, eid, confidence=None):
    raw = (
        None
        if confidence is None
        else {
            "classification": {
                "account": "4010",
                "confidence": str(confidence),
                "candidates": [
                    {"account": "4010", "score": str(confidence)},
                    {"account": "4020", "score": "0.10"},
                    {"account": "4900", "score": "0.05"},
                ],
            }
        }
    )
    session.add(
        SettlementEvent(
            id=eid,
            run_id=RUN_ID,
            source="seed",
            event_type="payment",
            occurred_at=datetime(2026, 8, 5),
            amount_native=Decimal("20.00"),
            currency_native="USD",
            amount_payout=Decimal("20.00"),
            currency_payout="USD",
            raw=raw,
        )
    )


def test_low_confidence_triggers(session):
    _event(session, "se-low", Decimal("0.60"))
    session.commit()
    drafts = LowConfidenceClassificationHandler().detect(
        RunContext(run_id=RUN_ID, period=PERIOD), session=session
    )
    assert len(drafts) == 1
    assert drafts[0].type == "LOW_CONFIDENCE_CLASSIFICATION"
    assert drafts[0].confidence == Decimal("0.60")


def test_high_confidence_near_miss_does_not_trigger(session):
    _event(session, "se-ok", Decimal("0.95"))
    session.commit()
    drafts = LowConfidenceClassificationHandler().detect(
        RunContext(run_id=RUN_ID, period=PERIOD), session=session
    )
    assert drafts == []


def test_no_classification_near_miss_does_not_trigger(session):
    _event(session, "se-none")
    session.commit()
    drafts = LowConfidenceClassificationHandler().detect(
        RunContext(run_id=RUN_ID, period=PERIOD), session=session
    )
    assert drafts == []


def test_gather_hypothesize_always_escalates(session):
    _event(session, "se-1", Decimal("0.50"))
    session.commit()
    ctx = RunContext(run_id=RUN_ID, period=PERIOD)
    handler = LowConfidenceClassificationHandler()
    drafts = handler.detect(ctx, session=session)
    evidence = handler.gather(drafts[0], ctx, session=session)
    assert len(evidence["top_candidates"]) == 3
    hyps = handler.hypothesize(drafts[0], evidence)
    assert hyps[0]["hypothesis"] == "ambiguous_gl_assignment"
    remedy = handler.propose(drafts[0], hyps[0])
    assert remedy["route"] == "ESCALATE"
    assert remedy["remedy"] is None


def test_compile_rule_shape():
    exc = ExceptionDraft(
        type="LOW_CONFIDENCE_CLASSIFICATION",
        severity="medium",
        amount=Decimal("20.00"),
        confidence=Decimal("0.5"),
        evidence={"settlement_event_id": "se-1"},
    )
    rule = LowConfidenceClassificationHandler().compile_rule(exc, {"rationale": "ok"})
    assert rule["name"] == "classification_precedent"


def test_build_priority_and_type():
    handler = LowConfidenceClassificationHandler()
    assert handler.type == "LOW_CONFIDENCE_CLASSIFICATION"
    assert handler.build_priority == 1
