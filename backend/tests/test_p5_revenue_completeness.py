"""Tests for P5 revenue completeness proof obligation."""
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from backend.app.contracts import RunContext
from backend.app.engine.proofs.p5 import P5RevenueCompleteness, _to_finite_decimal
from backend.app.models.base import Base
from backend.app.models.schema import CloseRun, Invoice, JournalEntry, JournalLine


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


def _make_je(session: Session, run_id: str, entry_id: str) -> JournalEntry:
    je = JournalEntry(
        id=entry_id,
        run_id=run_id,
        period="2026-08",
        memo="test entry",
        posted_at=datetime(2026, 8, 15),
        status="posted",
        created_by="rule",
    )
    session.add(je)
    return je


def _make_jl(
    session: Session, line_id: str, entry_id: str, account_code: str,
    debit: Decimal, credit: Decimal, currency: str = "USD",
) -> JournalLine:
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


def test_p5_passes_when_recognized_equals_invoiced_net_of_contra():
    engine = _make_engine()
    run_id = "run_p5_clean"

    with Session(engine) as session:
        _seed_run(session, run_id)
        # Invoice: subtotal $900.00, tax $90.00, total $990.00
        session.add(
            Invoice(
                id="inv_1",
                run_id=run_id,
                external_id="ext_1",
                customer_id="cust_1",
                issued_at=datetime(2026, 8, 15),
                subtotal=Decimal("900.00"),
                tax=Decimal("90.00"),
                total=Decimal("990.00"),
                currency="USD",
            )
        )
        # Payment entry: Dr 1310 $1090.00, Cr 4010 $1000.00, Cr 2100 (tax) $90.00
        _make_je(session, run_id, "je_pay")
        _make_jl(session, "jl_p1", "je_pay", "1310", Decimal("1090.00"), Decimal("0.00"))
        _make_jl(session, "jl_p2", "je_pay", "4010", Decimal("0.00"), Decimal("1000.00"))
        _make_jl(session, "jl_p3", "je_pay", "2100", Decimal("0.00"), Decimal("90.00"))

        # Refund entry: Dr 4900 (contra-revenue) $100.00, Cr 1310 $100.00
        _make_je(session, run_id, "je_ref")
        _make_jl(session, "jl_r1", "je_ref", "4900", Decimal("100.00"), Decimal("0.00"))
        _make_jl(session, "jl_r2", "je_ref", "1310", Decimal("0.00"), Decimal("100.00"))

        session.commit()

        ctx = RunContext(run_id=run_id, period="2026-08")
        result = P5RevenueCompleteness().evaluate(ctx, session=session)

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
                issued_at=datetime(2026, 8, 15),
                subtotal=Decimal("900.01"),
                tax=Decimal("0.00"),
                total=Decimal("900.01"),
                currency="USD",
            )
        )
        _make_je(session, run_id, "je_pay")
        _make_jl(session, "jl_p1", "je_pay", "4010", Decimal("0.00"), Decimal("1000.00"))
        _make_jl(session, "jl_p2", "je_pay", "1310", Decimal("1000.00"), Decimal("0.00"))

        _make_je(session, run_id, "je_ref")
        _make_jl(session, "jl_r1", "je_ref", "4900", Decimal("100.00"), Decimal("0.00"))
        _make_jl(session, "jl_r2", "je_ref", "1310", Decimal("0.00"), Decimal("100.00"))

        session.commit()

        ctx = RunContext(run_id=run_id, period="2026-08")
        result = P5RevenueCompleteness().evaluate(ctx, session=session)

    assert result.passed is False
    assert result.delta == Decimal("0.01")


def test_p5_ignores_dispute_fees_and_does_not_reduce_revenue():
    """Account 6820 is an expense, NOT contra-revenue. It must not reduce recognized revenue."""
    engine = _make_engine()
    run_id = "run_p5_dispute_fee"

    with Session(engine) as session:
        _seed_run(session, run_id)
        # Invoice: subtotal $1000.00
        session.add(
            Invoice(
                id="inv_df",
                run_id=run_id,
                external_id="ext_df",
                customer_id="cust_df",
                issued_at=datetime(2026, 8, 15),
                subtotal=Decimal("1000.00"),
                tax=Decimal("0.00"),
                total=Decimal("1000.00"),
                currency="USD",
            )
        )
        # Revenue entry: Cr 4010 $1000.00
        _make_je(session, run_id, "je_rev")
        _make_jl(session, "jl_rev", "je_rev", "4010", Decimal("0.00"), Decimal("1000.00"))
        _make_jl(session, "jl_rev_dr", "je_rev", "1310", Decimal("1000.00"), Decimal("0.00"))

        # Dispute fee entry: Dr 6820 $15.00 (expense!), Cr 1310 $15.00
        _make_je(session, run_id, "je_fee")
        _make_jl(session, "jl_fee", "je_fee", "6820", Decimal("15.00"), Decimal("0.00"))
        _make_jl(session, "jl_fee_cr", "je_fee", "1310", Decimal("0.00"), Decimal("15.00"))

        session.commit()

        ctx = RunContext(run_id=run_id, period="2026-08")
        result = P5RevenueCompleteness().evaluate(ctx, session=session)

    # Recognized revenue must remain $1000.00 (not $985.00)
    assert result.passed is True
    assert result.actual == Decimal("1000.00")
    assert result.delta == Decimal("0.00")


def test_p5_fails_when_tax_incorrectly_credited_to_revenue():
    """Tax incorrectly credited to 4010 instead of 2100 increases revenue and fails P5."""
    engine = _make_engine()
    run_id = "run_p5_tax_mispost"

    with Session(engine) as session:
        _seed_run(session, run_id)
        # Invoice: subtotal $100.00, tax $10.00, total $110.00
        session.add(
            Invoice(
                id="inv_tax",
                run_id=run_id,
                external_id="ext_tax",
                customer_id="cust_tax",
                issued_at=datetime(2026, 8, 15),
                subtotal=Decimal("100.00"),
                tax=Decimal("10.00"),
                total=Decimal("110.00"),
                currency="USD",
            )
        )
        # Entry incorrectly credits all $110.00 to 4010 (misposting tax to revenue!)
        _make_je(session, run_id, "je_tax_mis")
        _make_jl(session, "jl_tm1", "je_tax_mis", "1310", Decimal("110.00"), Decimal("0.00"))
        _make_jl(session, "jl_tm2", "je_tax_mis", "4010", Decimal("0.00"), Decimal("110.00"))

        session.commit()

        ctx = RunContext(run_id=run_id, period="2026-08")
        result = P5RevenueCompleteness().evaluate(ctx, session=session)

    assert result.passed is False
    # Invoiced subtotal is 100.00, but recognized revenue is 110.00 -> delta is 10.00
    assert result.expected == Decimal("100.00")
    assert result.actual == Decimal("110.00")
    assert result.delta == Decimal("10.00")


def test_p5_fails_on_currency_mismatch():
    engine = _make_engine()
    run_id = "run_p5_currs"

    with Session(engine) as session:
        _seed_run(session, run_id)
        # Invoice in EUR
        session.add(
            Invoice(
                id="inv_eur",
                run_id=run_id,
                external_id="ext_eur",
                customer_id="cust_eur",
                issued_at=datetime(2026, 8, 15),
                subtotal=Decimal("100.00"),
                tax=Decimal("0.00"),
                total=Decimal("100.00"),
                currency="EUR",
            )
        )
        # Revenue booked in USD
        _make_je(session, run_id, "je_usd")
        _make_jl(
            session, "jl_u1", "je_usd", "4010",
            Decimal("0.00"), Decimal("100.00"), currency="USD",
        )
        _make_jl(
            session, "jl_u2", "je_usd", "1310",
            Decimal("100.00"), Decimal("0.00"), currency="USD",
        )

        session.commit()

        ctx = RunContext(run_id=run_id, period="2026-08")
        result = P5RevenueCompleteness().evaluate(ctx, session=session)

    assert result.passed is False
    assert result.delta == Decimal("100.00")


def test_p5_rejects_non_finite_decimal():
    with pytest.raises(ValueError, match="Non-finite decimal"):
        _to_finite_decimal(Decimal("NaN"))
    with pytest.raises(ValueError, match="Non-finite decimal"):
        _to_finite_decimal(Decimal("Infinity"))

