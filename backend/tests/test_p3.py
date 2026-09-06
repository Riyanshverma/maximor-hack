"""Tests for P3: clearing account rollforward proof obligation."""
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.contracts import RunContext
from backend.app.engine.proofs.p3 import P3, _to_finite_decimal
from backend.app.models.base import Base
from backend.app.models.schema import CloseRun, JournalEntry, JournalLine, Payout, SettlementEvent


@pytest.fixture
def db_url(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/p3_test.db"
    monkeypatch.setenv("DATABASE_URL", url)
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    return url


def _settlement_event(run_id, payout_id, event_type, amount, occurred_at, event_id, curr="USD"):
    return SettlementEvent(
        id=event_id,
        run_id=run_id,
        source="seed",
        external_id=f"evt_{event_id}",
        event_type=event_type,
        payout_id=payout_id,
        occurred_at=occurred_at,
        amount_native=amount,
        currency_native=curr,
        amount_payout=amount,
        currency_payout=curr,
    )


def _make_je(session, run_id, entry_id, memo="test"):
    je = JournalEntry(
        id=entry_id,
        run_id=run_id,
        period="2026-08",
        memo=memo,
        posted_at=datetime(2026, 8, 1),
        status="posted",
        created_by="rule",
    )
    session.add(je)
    return je


def _make_jl(session, line_id, entry_id, account_code, debit, credit, currency="USD"):
    jl = JournalLine(
        id=line_id,
        entry_id=entry_id,
        account_code=account_code,
        debit=debit,
        credit=credit,
        currency=currency,
    )
    session.add(jl)
    return jl


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
        # Journal entries:
        # 1. Payment: Dr 1310 $1000, Cr 4010 $1000
        _make_je(session, run_id, "je_pay")
        _make_jl(session, "jl_pay_dr", "je_pay", "1310", Decimal("1000.00"), Decimal("0.00"))
        _make_jl(session, "jl_pay_cr", "je_pay", "4010", Decimal("0.00"), Decimal("1000.00"))

        # 2. Fee: Dr 5100 $50, Cr 1310 $50
        _make_je(session, run_id, "je_fee")
        _make_jl(session, "jl_fee_dr", "je_fee", "5100", Decimal("50.00"), Decimal("0.00"))
        _make_jl(session, "jl_fee_cr", "je_fee", "1310", Decimal("0.00"), Decimal("50.00"))

        # 3. Payout transfer: Dr 1330 $950, Cr 1310 $950
        _make_je(session, run_id, "je_po")
        _make_jl(session, "jl_po_dr", "je_po", "1330", Decimal("950.00"), Decimal("0.00"))
        _make_jl(session, "jl_po_cr", "je_po", "1310", Decimal("0.00"), Decimal("950.00"))

        session.commit()

        ctx = RunContext(run_id=run_id, period="2026-08")
        result = P3().evaluate(ctx, session=session)

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
        # Journal entries with $4,812.50 gap:
        # Dr 1310: 14812.50, Cr 1310: 500.00 + 9500.00 = 10000.00 -> balance = 4812.50
        _make_je(session, run_id, "je_pay_gap")
        _make_jl(
            session, "jl_pay_gap_dr", "je_pay_gap", "1310",
            Decimal("14812.50"), Decimal("0.00"),
        )
        _make_jl(
            session, "jl_pay_gap_cr", "je_pay_gap", "4010",
            Decimal("0.00"), Decimal("14812.50"),
        )

        _make_je(session, run_id, "je_fee_gap")
        _make_jl(session, "jl_fee_gap_dr", "je_fee_gap", "5100", Decimal("500.00"), Decimal("0.00"))
        _make_jl(session, "jl_fee_gap_cr", "je_fee_gap", "1310", Decimal("0.00"), Decimal("500.00"))

        _make_je(session, run_id, "je_po_gap")
        _make_jl(session, "jl_po_gap_dr", "je_po_gap", "1330", Decimal("9500.00"), Decimal("0.00"))
        _make_jl(session, "jl_po_gap_cr", "je_po_gap", "1310", Decimal("0.00"), Decimal("9500.00"))

        session.commit()

        ctx = RunContext(run_id=run_id, period="2026-08")
        result = P3().evaluate(ctx, session=session)

    assert result.passed is False
    assert result.expected == Decimal("0.00")
    assert result.actual == residual
    assert result.delta == residual


def test_p3_fails_on_wrong_account_misposting_to_7490(db_url):
    """Reproduction: miscrediting payout to 7490 leaves 1310 balance != 0 and fails P3."""
    engine = create_engine(db_url)
    run_id = "run_wrong_gl"
    occurred_at = datetime(2026, 8, 1)

    with Session(engine) as session:
        session.add(CloseRun(id=run_id, period="2026-08", status="prove"))
        session.add(
            Payout(
                id="po_wrong",
                run_id=run_id,
                external_id="ext_wrong",
                status="completed",
                created_at=occurred_at,
                gross=Decimal("100.00"),
                fees=Decimal("0.00"),
                net=Decimal("100.00"),
                currency="USD",
            )
        )
        session.add(
            _settlement_event(run_id, "po_wrong", "payment", Decimal("100.00"), occurred_at, "se_w")
        )
        # Sale: Dr 1310 $100, Cr 4010 $100
        _make_je(session, run_id, "je_w_sale")
        _make_jl(session, "jl_w1", "je_w_sale", "1310", Decimal("100.00"), Decimal("0.00"))
        _make_jl(session, "jl_w2", "je_w_sale", "4010", Decimal("0.00"), Decimal("100.00"))

        # Transfer: Dr 1330 $100, Cr 7490 $100 (MISPOSTED to 7490 instead of 1310!)
        _make_je(session, run_id, "je_w_transfer")
        _make_jl(session, "jl_w3", "je_w_transfer", "1330", Decimal("100.00"), Decimal("0.00"))
        _make_jl(session, "jl_w4", "je_w_transfer", "7490", Decimal("0.00"), Decimal("100.00"))

        session.commit()

        ctx = RunContext(run_id=run_id, period="2026-08")
        result = P3().evaluate(ctx, session=session)

    assert result.passed is False
    # Account 1310 has Dr 100.00, Cr 0.00 -> balance is 100.00
    assert result.actual == Decimal("100.00")
    assert result.delta == Decimal("100.00")


def test_p3_fails_on_one_cent_residual(db_url):
    engine = create_engine(db_url)
    run_id = "run_cent"

    with Session(engine) as session:
        session.add(CloseRun(id=run_id, period="2026-08", status="prove"))
        _make_je(session, run_id, "je_c1")
        _make_jl(session, "jl_c1", "je_c1", "1310", Decimal("100.01"), Decimal("0.00"))
        _make_jl(session, "jl_c2", "je_c1", "4010", Decimal("0.00"), Decimal("100.01"))

        _make_je(session, run_id, "je_c2")
        _make_jl(session, "jl_c3", "je_c2", "1330", Decimal("100.00"), Decimal("0.00"))
        _make_jl(session, "jl_c4", "je_c2", "1310", Decimal("0.00"), Decimal("100.00"))

        session.commit()

        ctx = RunContext(run_id=run_id, period="2026-08")
        result = P3().evaluate(ctx, session=session)

    assert result.passed is False
    assert result.delta == Decimal("0.01")


def test_p3_fails_on_currency_mismatch(db_url):
    engine = create_engine(db_url)
    run_id = "run_currs"

    with Session(engine) as session:
        session.add(CloseRun(id=run_id, period="2026-08", status="prove"))
        # Dr 1310 in EUR
        _make_je(session, run_id, "je_curr1")
        _make_jl(
            session, "jl_cu1", "je_curr1", "1310",
            Decimal("100.00"), Decimal("0.00"), currency="EUR",
        )
        _make_jl(
            session, "jl_cu2", "je_curr1", "4010",
            Decimal("0.00"), Decimal("100.00"), currency="EUR",
        )

        # Cr 1310 in USD
        _make_je(session, run_id, "je_curr2")
        _make_jl(
            session, "jl_cu3", "je_curr2", "1330",
            Decimal("100.00"), Decimal("0.00"), currency="USD",
        )
        _make_jl(
            session, "jl_cu4", "je_curr2", "1310",
            Decimal("0.00"), Decimal("100.00"), currency="USD",
        )

        session.commit()

        ctx = RunContext(run_id=run_id, period="2026-08")
        result = P3().evaluate(ctx, session=session)

    assert result.passed is False
    assert result.delta == Decimal("100.00")


def test_p3_rejects_non_finite_decimal():
    with pytest.raises(ValueError, match="Non-finite decimal"):
        _to_finite_decimal(Decimal("NaN"))
    with pytest.raises(ValueError, match="Non-finite decimal"):
        _to_finite_decimal(Decimal("Infinity"))


def test_p3_formats_strings_in_detail(db_url):
    engine = create_engine(db_url)
    run_id = "run_fmt"

    with Session(engine) as session:
        session.add(CloseRun(id=run_id, period="2026-08", status="prove"))
        _make_je(session, run_id, "je_f1")
        _make_jl(session, "jl_f1", "je_f1", "1310", Decimal("50.00"), Decimal("0.00"))
        _make_jl(session, "jl_f2", "je_f1", "1310", Decimal("0.00"), Decimal("40.00"))
        session.commit()

        ctx = RunContext(run_id=run_id, period="2026-08")
        result = P3().evaluate(ctx, session=session)

    assert isinstance(result.detail["closing_balance"], str)
    assert isinstance(result.detail["debits_1310"], str)
    assert isinstance(result.detail["credits_1310"], str)

