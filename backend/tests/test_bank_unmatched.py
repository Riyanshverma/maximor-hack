"""Tests for the BANK_UNMATCHED (type 11) exception handler."""
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.contracts import RunContext
from backend.app.engine.handlers.bank_unmatched import BankUnmatchedHandler
from backend.app.engine.matcher import match_bank_lines
from backend.app.models.base import Base
from backend.app.models.schema import BankLine, CloseRun, Payout

RUN_ID = "run-1"


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        s.add(CloseRun(id=RUN_ID, period="2026-08", status="ingest"))
        s.commit()
        yield s


def make_payout(session, payout_id, net, settled_at, status="completed", currency="USD"):
    payout = Payout(
        id=payout_id,
        run_id=RUN_ID,
        external_id=f"ext-{payout_id}",
        status=status,
        created_at=settled_at,
        settled_at=settled_at,
        gross=net + Decimal("5.00"),
        fees=Decimal("5.00"),
        net=net,
        currency=currency,
    )
    session.add(payout)
    return payout


def make_bank_line(session, line_id, amount, posted_at, currency="USD"):
    bank_line = BankLine(
        id=line_id,
        run_id=RUN_ID,
        posted_at=posted_at,
        amount=amount,
        currency=currency,
        description="deposit",
    )
    session.add(bank_line)
    return bank_line


@pytest.fixture
def handler():
    return BankUnmatchedHandler()


def test_type_and_build_priority(handler):
    assert handler.type == "BANK_UNMATCHED"
    assert handler.build_priority == 1


def test_detect_triggers_on_zero_candidate_payout(session, handler):
    """A completed payout with no matching bank deposit anywhere must trigger."""
    make_payout(session, "payout-unmatched", Decimal("1425.00"), datetime(2026, 8, 13, 12, 0))
    session.commit()

    match_bank_lines(session, RUN_ID)

    ctx = RunContext(run_id=RUN_ID, period="2026-08")
    exceptions = handler.detect(ctx, session=session)

    assert len(exceptions) == 1
    exc = exceptions[0]
    assert exc.type == "BANK_UNMATCHED"
    assert exc.amount == Decimal("1425.00")
    assert exc.evidence["payout_id"] == "payout-unmatched"


def test_detect_does_not_trigger_on_near_miss_matched_payout(session, handler):
    """A payout the matcher successfully ties out must not trigger."""
    make_payout(session, "payout-matched", Decimal("95.00"), datetime(2026, 8, 10, 9, 0))
    make_bank_line(session, "bank-matched", Decimal("95.00"), datetime(2026, 8, 11, 9, 0))
    session.commit()

    matches = match_bank_lines(session, RUN_ID)
    assert matches == [("bank-matched", "payout-matched")]

    ctx = RunContext(run_id=RUN_ID, period="2026-08")
    exceptions = handler.detect(ctx, session=session)

    assert exceptions == []


def test_detect_triggers_on_ambiguous_candidates(session, handler):
    """A payout with 2+ candidate bank lines is left unmatched by the matcher and must trigger."""
    make_payout(session, "payout-ambig", Decimal("50.00"), datetime(2026, 8, 10, 9, 0))
    make_bank_line(session, "bank-a", Decimal("50.00"), datetime(2026, 8, 10, 9, 0))
    make_bank_line(session, "bank-b", Decimal("50.00"), datetime(2026, 8, 11, 9, 0))
    session.commit()

    matches = match_bank_lines(session, RUN_ID)
    assert matches == []

    ctx = RunContext(run_id=RUN_ID, period="2026-08")
    exceptions = handler.detect(ctx, session=session)

    assert len(exceptions) == 1
    assert exceptions[0].evidence["payout_id"] == "payout-ambig"


def test_detect_ignores_non_paid_status(session, handler):
    make_payout(
        session, "payout-pending", Decimal("10.00"), datetime(2026, 8, 10), status="pending"
    )
    session.commit()

    ctx = RunContext(run_id=RUN_ID, period="2026-08")
    exceptions = handler.detect(ctx, session=session)

    assert exceptions == []


def test_gather_zero_candidates(session, handler):
    make_payout(session, "payout-unmatched", Decimal("1425.00"), datetime(2026, 8, 13, 12, 0))
    session.commit()
    match_bank_lines(session, RUN_ID)

    ctx = RunContext(run_id=RUN_ID, period="2026-08")
    exc = handler.detect(ctx, session=session)[0]
    evidence = handler.gather(exc, ctx, session=session)

    assert evidence["candidate_count"] == 0
    assert evidence["candidate_bank_lines"] == []
    assert evidence["payout"]["id"] == "payout-unmatched"
    assert evidence["date_window_days"] == 3


def test_gather_multiple_candidates(session, handler):
    make_payout(session, "payout-ambig", Decimal("50.00"), datetime(2026, 8, 10, 9, 0))
    make_bank_line(session, "bank-a", Decimal("50.00"), datetime(2026, 8, 10, 9, 0))
    make_bank_line(session, "bank-b", Decimal("50.00"), datetime(2026, 8, 11, 9, 0))
    session.commit()
    match_bank_lines(session, RUN_ID)

    ctx = RunContext(run_id=RUN_ID, period="2026-08")
    exc = handler.detect(ctx, session=session)[0]
    evidence = handler.gather(exc, ctx, session=session)

    assert evidence["candidate_count"] == 2
    assert {bl["id"] for bl in evidence["candidate_bank_lines"]} == {"bank-a", "bank-b"}


def test_gather_excludes_out_of_window_bank_line(session, handler):
    make_payout(session, "payout-unmatched", Decimal("1425.00"), datetime(2026, 8, 13, 12, 0))
    make_bank_line(
        session, "bank-far", Decimal("1425.00"), datetime(2026, 8, 13, 12, 0) + timedelta(days=4)
    )
    session.commit()
    match_bank_lines(session, RUN_ID)

    ctx = RunContext(run_id=RUN_ID, period="2026-08")
    exc = handler.detect(ctx, session=session)[0]
    evidence = handler.gather(exc, ctx, session=session)

    assert evidence["candidate_count"] == 0


def test_hypothesize_zero_candidates(handler):
    hyps = handler.hypothesize(None, {"candidate_count": 0})
    assert len(hyps) == 1
    assert hyps[0]["hypothesis"] == "deposit_missing_or_not_yet_posted"


def test_hypothesize_ambiguous_candidates(handler):
    hyps = handler.hypothesize(None, {"candidate_count": 2})
    assert len(hyps) == 1
    assert hyps[0]["hypothesis"] == "ambiguous_deposit_match"


def test_propose_returns_none(handler):
    assert handler.propose(None, {"hypothesis": "deposit_missing_or_not_yet_posted"}) is None


def test_compile_rule_returns_bank_match_window_rule(handler):
    rule = handler.compile_rule(None, {"rationale": "deposit posted late"})
    assert rule["name"] == "bank_match_window"
    assert rule["action"]["days"] == 3
    assert rule["action"]["amount_tolerance"] == "0.00"
    assert rule["rationale"] == "deposit posted late"
