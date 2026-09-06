"""Golden integration suite testing full close pipeline and P1-P6 invariants."""
import os
import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.app.contracts import RunContext
from backend.app.engine.matcher import match_bank_lines
from backend.app.engine.proofs.p1 import P1DebitCreditBalance
from backend.app.engine.proofs.p2 import P2PayoutComponentsSum
from backend.app.engine.proofs.p3 import P3
from backend.app.engine.proofs.p4 import P4BankTieOut
from backend.app.engine.proofs.p5 import P5RevenueCompleteness
from backend.app.engine.proofs.p6 import P6NoOrphans
from backend.app.ingest.generator import TestDataGenerator, get_chart_of_accounts
from backend.app.models.base import Base
from backend.app.models.schema import (
    BankLine,
    CloseRun,
    Invoice,
    JournalEntry,
    JournalLine,
    Payout,
    SettlementEvent,
)


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    """Provide a real database session, preferring PostgreSQL on 55432 with SQLite fallback."""
    pg_url = os.getenv("DATABASE_URL")
    if not pg_url:
        try:
            candidate = "postgresql://tieout:@127.0.0.1:55432/tieout_test"
            eng = create_engine(candidate)
            with eng.connect() as conn:
                conn.execute(text("SELECT 1"))
            pg_url = candidate
        except Exception:
            pg_url = f"sqlite:///{tmp_path}/golden_test.db"

    monkeypatch.setenv("DATABASE_URL", pg_url)
    engine = create_engine(pg_url)
    Base.metadata.create_all(engine)

    truncate_sql = (
        "TRUNCATE close_run, payout, bank_line, settlement_event, invoice, "
        "journal_entry, journal_line, exception, human_ruling, proof_result, "
        "audit_event CASCADE;"
    )

    with Session(engine) as session:
        if engine.dialect.name == "postgresql":
            session.execute(text(truncate_sql))
            session.commit()
        else:
            for tbl in reversed(Base.metadata.sorted_tables):
                if tbl.name != "gl_account":
                    session.execute(tbl.delete())
            session.commit()

        for acc in get_chart_of_accounts():
            session.merge(acc)
        session.commit()

    with Session(engine) as session:
        yield session
        if engine.dialect.name == "postgresql":
            session.rollback()
            session.execute(text(truncate_sql))
            session.commit()


def _seed_clean_run(session: Session, run_id: str, period: str = "2026-08") -> None:
    """Seed a fully coherent clean period where all P1-P6 obligations hold."""
    session.add(CloseRun(id=run_id, period=period, status="in_progress"))
    session.flush()

    type_priority = {
        Payout: 1,
        BankLine: 2,
        SettlementEvent: 3,
        Invoice: 4,
        JournalEntry: 5,
        JournalLine: 6,
    }

    import collections
    grouped: dict[int, list] = collections.defaultdict(list)

    gen = TestDataGenerator(seed=42)
    clean_objects = gen.generate_clean_data_august(run_id)
    for obj in clean_objects:
        priority = type_priority.get(type(obj), 99)
        grouped[priority].append(obj)

    for priority in sorted(grouped.keys()):
        for obj in grouped[priority]:
            session.add(obj)
        session.flush()

    session.commit()


def test_golden_clean_baseline_all_proofs_pass(db_session):
    """Clean dataset with matcher matches bank deposit and satisfies P1-P6 with 0 delta."""
    run_id = f"run_golden_clean_{uuid.uuid4().hex[:8]}"
    _seed_clean_run(db_session, run_id)

    # 1. Run matcher
    matches = match_bank_lines(db_session, run_id)
    db_session.commit()
    assert len(matches) >= 1

    # 2. Evaluate all proofs P1 - P6
    ctx = RunContext(run_id=run_id, period="2026-08")

    res_p1 = P1DebitCreditBalance().evaluate(ctx, session=db_session)
    res_p2 = P2PayoutComponentsSum().evaluate(ctx, session=db_session)
    res_p3 = P3().evaluate(ctx, session=db_session)
    res_p4 = P4BankTieOut().evaluate(ctx, session=db_session)
    res_p5 = P5RevenueCompleteness().evaluate(ctx, session=db_session)
    res_p6 = P6NoOrphans().evaluate(ctx, session=db_session)

    assert res_p1.passed is True and res_p1.delta == Decimal("0.00")
    assert res_p2.passed is True and res_p2.delta == Decimal("0.00")
    assert res_p3.passed is True and res_p3.delta == Decimal("0.00")
    assert res_p4.passed is True and res_p4.delta == Decimal("0.00")
    assert res_p5.passed is True and res_p5.delta == Decimal("0.00")
    assert res_p6.passed is True and res_p6.delta == Decimal("0.00")


def test_golden_isolated_defect_p1_imbalance(db_session):
    """P1 imbalance fails P1 while independent obligations remain valid."""
    run_id = f"run_def_p1_{uuid.uuid4().hex[:8]}"
    _seed_clean_run(db_session, run_id)
    match_bank_lines(db_session, run_id)
    db_session.commit()

    # Tamper with a journal line debit (+0.01)
    jl = db_session.query(JournalLine).filter(JournalLine.debit > 0).first()
    assert jl is not None
    jl.debit = Decimal(str(jl.debit)) + Decimal("0.01")
    db_session.commit()

    ctx = RunContext(run_id=run_id, period="2026-08")
    res_p1 = P1DebitCreditBalance().evaluate(ctx, session=db_session)
    assert res_p1.passed is False
    assert res_p1.delta == Decimal("0.01")


def test_golden_isolated_defect_p2_component_mismatch(db_session):
    """P2 fails when settlement event sum does not equal payout net."""
    run_id = f"run_def_p2_{uuid.uuid4().hex[:8]}"
    _seed_clean_run(db_session, run_id)
    match_bank_lines(db_session, run_id)
    db_session.commit()

    # Tamper with settlement event amount
    evt = db_session.query(SettlementEvent).filter(SettlementEvent.run_id == run_id).first()
    assert evt is not None
    evt.amount_payout = Decimal(str(evt.amount_payout)) + Decimal("15.00")
    db_session.commit()

    ctx = RunContext(run_id=run_id, period="2026-08")
    res_p2 = P2PayoutComponentsSum().evaluate(ctx, session=db_session)
    assert res_p2.passed is False
    assert res_p2.delta == Decimal("15.00")


def test_golden_isolated_defect_p3_clearing_misposting(db_session):
    """Reproduction: crediting 7490 instead of 1310 for payout transfer fails P3."""
    run_id = f"run_def_p3_{uuid.uuid4().hex[:8]}"
    _seed_clean_run(db_session, run_id)
    match_bank_lines(db_session, run_id)
    db_session.commit()

    # Change credit line on 1310 to 7490
    jl = (
        db_session.query(JournalLine)
        .filter(JournalLine.account_code == "1310", JournalLine.credit > 0)
        .first()
    )
    assert jl is not None
    jl.account_code = "7490"
    db_session.commit()

    ctx = RunContext(run_id=run_id, period="2026-08")
    # P1 still passes because entry is balanced
    res_p1 = P1DebitCreditBalance().evaluate(ctx, session=db_session)
    assert res_p1.passed is True

    # P3 fails because 1310 does not clear!
    res_p3 = P3().evaluate(ctx, session=db_session)
    assert res_p3.passed is False
    assert res_p3.delta == Decimal("4750.00")


def test_golden_isolated_defect_p4_bank_window(db_session):
    """P4 fails when bank line posted date is outside the +/- 3-day window."""
    run_id = f"run_def_p4_{uuid.uuid4().hex[:8]}"
    _seed_clean_run(db_session, run_id)

    bl = db_session.query(BankLine).filter(BankLine.run_id == run_id).first()
    po = db_session.query(Payout).filter(Payout.run_id == run_id).first()
    assert bl is not None and po is not None

    # Post 5 days later (outside 3-day window)
    bl.posted_at = po.settled_at + timedelta(days=5)
    db_session.commit()

    match_bank_lines(db_session, run_id)
    db_session.commit()

    ctx = RunContext(run_id=run_id, period="2026-08")
    res_p4 = P4BankTieOut().evaluate(ctx, session=db_session)
    assert res_p4.passed is False
    assert res_p4.actual >= Decimal("1.00")


def test_golden_isolated_defect_p5_tax_miscredited_to_revenue(db_session):
    """P5 fails when tax is incorrectly credited to revenue 4010."""
    run_id = f"run_def_p5_{uuid.uuid4().hex[:8]}"
    _seed_clean_run(db_session, run_id)
    match_bank_lines(db_session, run_id)
    db_session.commit()

    # Credit an extra $50 to 4010
    rev_jl = (
        db_session.query(JournalLine)
        .filter(JournalLine.account_code == "4010", JournalLine.credit > 0)
        .first()
    )
    assert rev_jl is not None
    rev_jl.credit = Decimal(str(rev_jl.credit)) + Decimal("50.00")
    db_session.commit()

    ctx = RunContext(run_id=run_id, period="2026-08")
    res_p5 = P5RevenueCompleteness().evaluate(ctx, session=db_session)
    assert res_p5.passed is False
    assert res_p5.delta == Decimal("50.00")


def test_golden_isolated_defect_p6_missing_mapping(db_session):
    """P6 fails when a settlement event lacks its designated clearing journal line."""
    run_id = f"run_def_p6_{uuid.uuid4().hex[:8]}"
    _seed_clean_run(db_session, run_id)
    match_bank_lines(db_session, run_id)
    db_session.commit()

    # Clear settlement_event_id from journal line
    jl = (
        db_session.query(JournalLine)
        .filter(JournalLine.settlement_event_id.is_not(None))
        .first()
    )
    assert jl is not None
    jl.settlement_event_id = None
    db_session.commit()

    ctx = RunContext(run_id=run_id, period="2026-08")
    res_p6 = P6NoOrphans().evaluate(ctx, session=db_session)
    assert res_p6.passed is False
    assert res_p6.delta == Decimal("1.00")
