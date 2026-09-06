"""Tests for the AMOUNT_MISMATCH handler (taxonomy type 1)."""
from datetime import datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.contracts import RunContext
from backend.app.engine.handlers.amount_mismatch import AmountMismatchHandler
from backend.app.models.base import Base
from backend.app.models.schema import (
    CloseRun,
    JournalEntry,
    JournalLine,
    Payout,
    SettlementEvent,
)


def _make_session(tmp_path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path}/test.db")
    Base.metadata.create_all(engine)
    return Session(engine)


def _seed_payout(session, run_id, payout_id, net, event_amounts, period="2026-08"):
    session.add(
        Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext-{payout_id}",
            status="completed",
            created_at=datetime(2026, 8, 1),
            gross=net + Decimal("50.00"),
            fees=Decimal("50.00"),
            net=net,
            currency="USD",
        )
    )
    for i, amount in enumerate(event_amounts):
        session.add(
            SettlementEvent(
                id=f"{payout_id}-event-{i}",
                run_id=run_id,
                source="seed",
                event_type="payment",
                payout_id=payout_id,
                occurred_at=datetime(2026, 8, 1),
                amount_native=amount,
                currency_native="USD",
                amount_payout=amount,
                currency_payout="USD",
                fx_rate=Decimal("1.0"),
            )
        )


def test_detect_finds_mismatch_matching_generator_planted_shape(tmp_path):
    """Mirrors generator.plant_amount_mismatch_august: events sum $0.01 over net."""
    session = _make_session(tmp_path)
    session.add(CloseRun(id="run-1", period="2026-08", status="prove"))
    _seed_payout(
        session,
        "run-1",
        "payout-mismatch",
        net=Decimal("950.00"),
        event_amounts=[Decimal("500.01"), Decimal("250.00"), Decimal("200.00")],
    )
    session.commit()

    handler = AmountMismatchHandler()
    ctx = RunContext(run_id="run-1", period="2026-08")
    drafts = handler.detect(ctx, session=session)

    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.type == "AMOUNT_MISMATCH"
    assert draft.amount == Decimal("0.01")
    assert draft.severity == "low"
    assert draft.evidence["payout_id"] == "payout-mismatch"


def test_detect_ignores_payout_with_zero_delta(tmp_path):
    """Near-miss: components sum exactly to net -> must not be detected."""
    session = _make_session(tmp_path)
    session.add(CloseRun(id="run-1", period="2026-08", status="prove"))
    _seed_payout(
        session,
        "run-1",
        "payout-clean",
        net=Decimal("950.00"),
        event_amounts=[Decimal("500.00"), Decimal("250.00"), Decimal("200.00")],
    )
    session.commit()

    handler = AmountMismatchHandler()
    ctx = RunContext(run_id="run-1", period="2026-08")
    drafts = handler.detect(ctx, session=session)

    assert drafts == []


def test_full_lifecycle_auto_resolves_small_delta_within_cap(tmp_path):
    session = _make_session(tmp_path)
    session.add(CloseRun(id="run-1", period="2026-08", status="prove"))
    _seed_payout(
        session,
        "run-1",
        "payout-mismatch",
        net=Decimal("950.00"),
        event_amounts=[Decimal("500.01"), Decimal("250.00"), Decimal("200.00")],
    )
    session.commit()

    handler = AmountMismatchHandler()
    ctx = RunContext(run_id="run-1", period="2026-08")

    draft = handler.detect(ctx, session=session)[0]
    evidence = handler.gather(draft, ctx, session=session)
    assert evidence["payout"]["id"] == "payout-mismatch"
    assert len(evidence["entries"]) == 3

    hypotheses = handler.hypothesize(draft, evidence)
    assert hypotheses[0]["root_cause"] == "pro_rating_residual"

    remedy = handler.propose(draft, hypotheses[0])
    assert remedy is not None
    assert remedy["route"] == "AUTO"
    assert remedy["debit_account"] == "7490"
    assert remedy["credit_account"] == "1310"
    assert Decimal(remedy["amount"]) == Decimal("0.01")

    assert handler.compile_rule(draft, {"decision": "approved"}) is None


def test_escalates_when_delta_exceeds_one_dollar(tmp_path):
    """delta > $1.00 must escalate, never auto-resolve, per taxonomy type 1."""
    session = _make_session(tmp_path)
    session.add(CloseRun(id="run-1", period="2026-08", status="prove"))
    _seed_payout(
        session,
        "run-1",
        "payout-big-mismatch",
        net=Decimal("950.00"),
        event_amounts=[Decimal("500.00"), Decimal("250.00"), Decimal("205.00")],
    )
    session.commit()

    handler = AmountMismatchHandler()
    ctx = RunContext(run_id="run-1", period="2026-08")

    drafts = handler.detect(ctx, session=session)
    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.amount == Decimal("5.00")
    assert draft.severity == "high"

    evidence = handler.gather(draft, ctx, session=session)
    hypotheses = handler.hypothesize(draft, evidence)
    assert hypotheses[0]["root_cause"] == "unexplained"

    remedy = handler.propose(draft, hypotheses[0])
    assert remedy is not None
    assert remedy["route"] == "ESCALATE"


def test_escalates_when_period_7490_cap_already_consumed(tmp_path):
    """Small delta that would normally auto-resolve, but the $25 period cap is exhausted."""
    session = _make_session(tmp_path)
    session.add(CloseRun(id="run-1", period="2026-08", status="prove"))
    _seed_payout(
        session,
        "run-1",
        "payout-mismatch",
        net=Decimal("950.00"),
        event_amounts=[Decimal("500.01"), Decimal("250.00"), Decimal("200.00")],
    )
    # Prior postings to 7490 for this period already consumed the full $25.00 cap.
    session.add(
        JournalEntry(
            id="je-prior",
            run_id="run-1",
            period="2026-08",
            status="posted",
            created_by="agent",
        )
    )
    session.add(
        JournalLine(
            id="jl-prior-debit",
            entry_id="je-prior",
            account_code="7490",
            debit=Decimal("25.00"),
            credit=Decimal("0.00"),
            currency="USD",
        )
    )
    session.add(
        JournalLine(
            id="jl-prior-credit",
            entry_id="je-prior",
            account_code="1310",
            debit=Decimal("0.00"),
            credit=Decimal("25.00"),
            currency="USD",
        )
    )
    session.commit()

    handler = AmountMismatchHandler()
    ctx = RunContext(run_id="run-1", period="2026-08")

    draft = handler.detect(ctx, session=session)[0]
    evidence = handler.gather(draft, ctx, session=session)
    assert Decimal(evidence["period_7490_consumed"]) == Decimal("25.00")

    hypotheses = handler.hypothesize(draft, evidence)
    assert hypotheses[0]["root_cause"] == "pro_rating_residual"
    assert Decimal(hypotheses[0]["cap_available"]) == Decimal("0.00")

    remedy = handler.propose(draft, hypotheses[0])
    assert remedy is not None
    assert remedy["route"] == "ESCALATE"
