"""Tests for the DISPUTE_LIFECYCLE_INCOMPLETE handler (taxonomy type 3)."""
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.contracts import ExceptionDraft, RunContext
from backend.app.engine.handlers.dispute_lifecycle import (
    DisputeLifecycleHandler,
    dispute_provision_policy,
)
from backend.app.models.base import Base
from backend.app.models.schema import CloseRun, SettlementEvent

RUN_ID = "run_sep_2026"
PERIOD = "2026-09"


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path / 'test_dispute_lifecycle.db'}"
    monkeypatch.setenv("DATABASE_URL", db_url)
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(CloseRun(id=RUN_ID, period=PERIOD, status="prove"))
        session.commit()
        yield session


def _event(
    event_id: str,
    payout_id: str,
    event_type: str,
    amount: Decimal,
    occurred_at: datetime,
    raw: dict | None = None,
) -> SettlementEvent:
    return SettlementEvent(
        id=event_id,
        run_id=RUN_ID,
        source="seed",
        external_id=f"ext_{event_id}",
        event_type=event_type,
        payout_id=payout_id,
        order_id=f"ord_{payout_id}",
        customer_id=f"cust_{payout_id}",
        occurred_at=occurred_at,
        amount_native=amount,
        currency_native="USD",
        amount_payout=amount,
        currency_payout="USD",
        fx_rate=Decimal("1.0"),
        fx_source="dodo_spot_rate",
        raw=raw or {},
    )


def _plant_unresolved_dispute(session: Session, payout_id: str = "po_dispute_1") -> None:
    """Matches generator.plant_dispute_incomplete_september's planted shape."""
    session.add(
        _event(
            "se_payment_1", payout_id, "payment", Decimal("4900.00"),
            datetime(2026, 9, 16, 10, 0, 0),
        )
    )
    session.add(
        _event(
            "se_dispute_1", payout_id, "dispute_opened", Decimal("-100.00"),
            datetime(2026, 9, 16, 10, 0, 0),
            raw={"dispute_status": "opened", "dispute_id": "dp_planted_001"},
        )
    )
    session.commit()


def _plant_resolved_dispute(session: Session, payout_id: str = "po_dispute_2") -> None:
    """Near-miss: dispute opened AND resolved within the period -- must not trigger."""
    session.add(
        _event(
            "se_payment_2", payout_id, "payment", Decimal("4900.00"),
            datetime(2026, 9, 5, 10, 0, 0),
        )
    )
    session.add(
        _event(
            "se_dispute_2", payout_id, "dispute_opened", Decimal("-100.00"),
            datetime(2026, 9, 5, 10, 0, 0),
            raw={"dispute_status": "opened", "dispute_id": "dp_resolved_001"},
        )
    )
    session.add(
        _event(
            "se_dispute_2_won", payout_id, "dispute_won", Decimal("100.00"),
            datetime(2026, 9, 10, 10, 0, 0),
        )
    )
    session.commit()


def test_detect_finds_unresolved_dispute_in_period(db_session):
    _plant_unresolved_dispute(db_session)
    handler = DisputeLifecycleHandler()
    ctx = RunContext(run_id=RUN_ID, period=PERIOD)

    drafts = handler.detect(ctx, session=db_session)

    assert len(drafts) == 1
    draft = drafts[0]
    assert draft.type == "DISPUTE_LIFECYCLE_INCOMPLETE"
    assert draft.amount == Decimal("100.00")
    assert draft.evidence["payout_id"] == "po_dispute_1"
    assert draft.evidence["status"] == "opened"


def test_detect_ignores_resolved_dispute(db_session):
    """Near-miss fixture: dispute resolved within period must not trigger."""
    _plant_resolved_dispute(db_session)
    handler = DisputeLifecycleHandler()
    ctx = RunContext(run_id=RUN_ID, period=PERIOD)

    drafts = handler.detect(ctx, session=db_session)

    assert drafts == []


def test_detect_ignores_dispute_opened_outside_period(db_session):
    db_session.add(
        _event(
            "se_payment_3", "po_dispute_3", "payment", Decimal("500.00"),
            datetime(2026, 8, 20, 10, 0, 0),
        )
    )
    db_session.add(
        _event(
            "se_dispute_3", "po_dispute_3", "dispute_opened", Decimal("-50.00"),
            datetime(2026, 8, 20, 10, 0, 0),
            raw={"dispute_status": "opened", "dispute_id": "dp_out_of_period"},
        )
    )
    db_session.commit()
    handler = DisputeLifecycleHandler()
    ctx = RunContext(run_id=RUN_ID, period=PERIOD)

    drafts = handler.detect(ctx, session=db_session)

    assert drafts == []


def test_detect_both_fixtures_together_only_flags_unresolved(db_session):
    _plant_unresolved_dispute(db_session, payout_id="po_dispute_1")
    _plant_resolved_dispute(db_session, payout_id="po_dispute_2")
    handler = DisputeLifecycleHandler()
    ctx = RunContext(run_id=RUN_ID, period=PERIOD)

    drafts = handler.detect(ctx, session=db_session)

    assert len(drafts) == 1
    assert drafts[0].evidence["payout_id"] == "po_dispute_1"


def test_gather_returns_timeline_original_charge_and_fees(db_session):
    payout_id = "po_dispute_fee"
    db_session.add(
        _event(
            "se_payment_4", payout_id, "payment", Decimal("4900.00"),
            datetime(2026, 9, 3, 10, 0, 0),
        )
    )
    db_session.add(
        _event(
            "se_dispute_4", payout_id, "dispute_opened", Decimal("-100.00"),
            datetime(2026, 9, 3, 11, 0, 0),
            raw={"dispute_status": "opened", "dispute_id": "dp_004"},
        )
    )
    db_session.add(
        _event(
            "se_dispute_fee_4", payout_id, "dispute_fee", Decimal("-15.00"),
            datetime(2026, 9, 3, 11, 5, 0),
        )
    )
    db_session.commit()

    handler = DisputeLifecycleHandler()
    ctx = RunContext(run_id=RUN_ID, period=PERIOD)
    draft = ExceptionDraft(
        type="DISPUTE_LIFECYCLE_INCOMPLETE",
        severity="high",
        amount=Decimal("100.00"),
        confidence=Decimal("1.00"),
        evidence={"payout_id": payout_id, "status": "opened", "period": PERIOD},
    )

    evidence = handler.gather(draft, ctx, session=db_session)

    assert evidence["original_charge"]["amount_payout"] == "4900.0000"
    assert len(evidence["fee_entries"]) == 1
    assert evidence["fee_entries"][0]["amount_payout"] == "-15.0000"
    assert len(evidence["timeline"]) == 3


def test_hypothesize_computes_age_days_and_provision():
    handler = DisputeLifecycleHandler()
    draft = ExceptionDraft(
        type="DISPUTE_LIFECYCLE_INCOMPLETE",
        severity="high",
        amount=Decimal("100.00"),
        confidence=Decimal("1.00"),
        evidence={
            "payout_id": "po_dispute_1",
            "status": "opened",
            "opened_at": "2026-09-16T10:00:00",
            "period": "2026-09",
        },
    )

    hypotheses = handler.hypothesize(draft, evidence={})

    assert len(hypotheses) == 1
    h = hypotheses[0]
    assert h["age_days"] == 14  # 2026-09-16 -> 2026-09-30
    assert h["provision_pct"] == "0.50"


def test_propose_always_escalates_with_provision():
    handler = DisputeLifecycleHandler()
    draft = ExceptionDraft(
        type="DISPUTE_LIFECYCLE_INCOMPLETE",
        severity="high",
        amount=Decimal("100.00"),
        confidence=Decimal("1.00"),
        evidence={"payout_id": "po_dispute_1", "dispute_id": "dp_planted_001"},
    )
    hypothesis = {"status": "opened", "age_days": 14, "provision_pct": "0.50"}

    remedy = handler.propose(draft, hypothesis)

    assert remedy is not None
    assert remedy["autonomy"] == "escalate"
    assert remedy["provision_amount"] == "50.00"
    assert remedy["entry"]["debit"]["account"] == "6810"
    assert remedy["entry"]["credit"]["account"] == "1310"


def test_compile_rule_returns_dispute_provision_policy_shape():
    handler = DisputeLifecycleHandler()
    draft = ExceptionDraft(
        type="DISPUTE_LIFECYCLE_INCOMPLETE",
        severity="high",
        amount=Decimal("100.00"),
        confidence=Decimal("1.00"),
        evidence={"status": "opened"},
    )
    ruling = {"status": "opened", "provision_pct": "0.60", "rationale": "prior loss rate"}

    rule = handler.compile_rule(draft, ruling)

    assert rule is not None
    assert rule["name"] == "dispute_provision_policy"
    assert rule["predicate"] == {"status": "opened"}
    assert rule["action"] == {"provision_pct": "0.60"}


@pytest.mark.parametrize(
    "status,age_days,expected",
    [
        ("opened", 10, Decimal("0.50")),
        ("opened", 45, Decimal("0.75")),
        ("opened", 90, Decimal("1.00")),
        ("under_review", 10, Decimal("0.40")),
    ],
)
def test_dispute_provision_policy_bands(status, age_days, expected):
    assert dispute_provision_policy(status, age_days) == expected
