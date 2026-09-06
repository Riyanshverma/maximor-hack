"""Tests for POLICY_VIOLATION (taxonomy type 13) exception handler."""
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.contracts import RunContext
from backend.app.engine.handlers.policy_violation import PolicyViolationHandler
from backend.app.models.base import Base
from backend.app.models.schema import (
    CloseRun,
    GLAccount,
    JournalEntry,
    JournalLine,
    Payout,
    SettlementEvent,
)

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
        s.add(GLAccount(code="1310", name="MoR Clearing", type="asset", normal_side="debit"))
        s.add(
            GLAccount(
                code="7490", name="Rounding Adjustment", type="other", normal_side="debit"
            )
        )
        s.add(
            GLAccount(
                code="9999",
                name="Restricted Reserve",
                type="asset",
                normal_side="debit",
                is_restricted=True,
            )
        )
        s.commit()
        yield s


def _entry(session, entry_id: str) -> None:
    session.add(JournalEntry(id=entry_id, run_id=RUN_ID, period=PERIOD, created_by="rule"))


def test_rounding_cap_per_payout_breach_triggers(session):
    """A single payout's postings to 7490 exceed the $1.00 hard cap."""
    session.add(
        Payout(
            id="payout-1",
            run_id=RUN_ID,
            external_id="ext-1",
            status="completed",
            created_at=datetime(2026, 8, 1),
            gross=Decimal("100.00"),
            fees=Decimal("2.00"),
            net=Decimal("98.00"),
            currency="USD",
        )
    )
    session.add(
        SettlementEvent(
            id="se-1",
            run_id=RUN_ID,
            source="seed",
            event_type="payment",
            payout_id="payout-1",
            occurred_at=datetime(2026, 8, 1),
            amount_native=Decimal("98.00"),
            currency_native="USD",
            amount_payout=Decimal("98.00"),
            currency_payout="USD",
        )
    )
    _entry(session, "entry-1")
    session.add(
        JournalLine(
            id="line-1",
            entry_id="entry-1",
            account_code="7490",
            debit=Decimal("1.50"),
            credit=Decimal("0.00"),
            currency="USD",
            settlement_event_id="se-1",
        )
    )
    session.commit()

    ctx = RunContext(run_id=RUN_ID, period=PERIOD)
    drafts = PolicyViolationHandler().detect(ctx, session=session)

    assert len(drafts) == 1
    assert drafts[0].type == "POLICY_VIOLATION"
    assert drafts[0].evidence["trigger"] == "rounding_cap_per_payout"
    assert drafts[0].amount == Decimal("1.50")


def test_restricted_account_touched_triggers(session):
    _entry(session, "entry-2")
    session.add(
        JournalLine(
            id="line-2",
            entry_id="entry-2",
            account_code="9999",
            debit=Decimal("50.00"),
            credit=Decimal("0.00"),
            currency="USD",
        )
    )
    session.commit()

    ctx = RunContext(run_id=RUN_ID, period=PERIOD)
    drafts = PolicyViolationHandler().detect(ctx, session=session)

    assert len(drafts) == 1
    assert drafts[0].evidence["trigger"] == "restricted_account_touched"
    assert drafts[0].evidence["account_code"] == "9999"


def test_period_aggregate_trigger_triggers(session):
    _entry(session, "entry-3")
    session.add(
        JournalLine(
            id="line-3",
            entry_id="entry-3",
            account_code="1310",
            debit=Decimal("2500.01"),
            credit=Decimal("0.00"),
            currency="USD",
        )
    )
    session.commit()

    ctx = RunContext(run_id=RUN_ID, period=PERIOD)
    drafts = PolicyViolationHandler().detect(ctx, session=session)

    assert len(drafts) == 1
    assert drafts[0].evidence["trigger"] == "period_aggregate_trigger"
    assert drafts[0].amount == Decimal("2500.01")


def test_clean_near_miss_does_not_trigger(session):
    """Normal postings under every cap, no restricted account: must not fire."""
    _entry(session, "entry-4")
    session.add(
        JournalLine(
            id="line-4a",
            entry_id="entry-4",
            account_code="1310",
            debit=Decimal("2500.00"),
            credit=Decimal("0.00"),
            currency="USD",
        )
    )
    session.add(
        JournalLine(
            id="line-4b",
            entry_id="entry-4",
            account_code="7490",
            debit=Decimal("1.00"),
            credit=Decimal("0.00"),
            currency="USD",
        )
    )
    session.add(
        JournalLine(
            id="line-4c",
            entry_id="entry-4",
            account_code="1310",
            debit=Decimal("0.00"),
            credit=Decimal("2500.00"),
            currency="USD",
        )
    )
    session.commit()

    ctx = RunContext(run_id=RUN_ID, period=PERIOD)
    drafts = PolicyViolationHandler().detect(ctx, session=session)

    assert drafts == []


def test_gather_returns_proposed_entry_rule_and_cap_consumption(session):
    _entry(session, "entry-5")
    session.add(
        JournalLine(
            id="line-5",
            entry_id="entry-5",
            account_code="9999",
            debit=Decimal("10.00"),
            credit=Decimal("0.00"),
            currency="USD",
        )
    )
    session.commit()

    ctx = RunContext(run_id=RUN_ID, period=PERIOD)
    handler = PolicyViolationHandler()
    drafts = handler.detect(ctx, session=session)
    evidence = handler.gather(drafts[0], ctx, session=session)

    assert evidence["proposed_entry"]["line_id"] == "line-5"
    assert "violated_rule" in evidence
    assert "cap_consumption_to_date" in evidence
    assert isinstance(evidence["cap_consumption_to_date"], str)


def test_never_auto_resolves_and_blocks_close(session):
    _entry(session, "entry-6")
    session.add(
        JournalLine(
            id="line-6",
            entry_id="entry-6",
            account_code="9999",
            debit=Decimal("10.00"),
            credit=Decimal("0.00"),
            currency="USD",
        )
    )
    session.commit()

    ctx = RunContext(run_id=RUN_ID, period=PERIOD)
    handler = PolicyViolationHandler()
    drafts = handler.detect(ctx, session=session)
    evidence = handler.gather(drafts[0], ctx, session=session)
    hypotheses = handler.hypothesize(drafts[0], evidence)
    remedy = handler.propose(drafts[0], hypotheses[0])
    rule = handler.compile_rule(drafts[0], {"decision": "approved"})

    assert remedy is not None
    assert remedy["blocks_close"] is True
    assert remedy["remedy"] is None
    assert rule is None


def test_build_priority_and_type():
    handler = PolicyViolationHandler()
    assert handler.type == "POLICY_VIOLATION"
    assert handler.build_priority == 1
