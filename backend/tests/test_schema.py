"""Test database schema and migrations."""
import os
import tempfile
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import NUMERIC, create_engine, inspect, text

import backend.app.models.schema  # noqa: F401
from backend.app.models.base import Base


def test_alembic_migration_runs_clean(monkeypatch):
    """Alembic migration upgrade and downgrade should run cleanly."""
    alembic_ini = Path(__file__).resolve().parents[2] / "alembic.ini"
    assert alembic_ini.exists()

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        # If no DATABASE_URL, test against a temporary sqlite file
        with tempfile.NamedTemporaryFile(suffix=".db") as tmp:
            test_url = f"sqlite:///{tmp.name}"
            cfg = Config(str(alembic_ini))
            cfg.set_main_option("sqlalchemy.url", test_url)
            command.upgrade(cfg, "head")
            command.downgrade(cfg, "base")
            command.upgrade(cfg, "head")
            engine = create_engine(test_url)
            tables = inspect(engine).get_table_names()
            assert "close_run" in tables
            assert "journal_line" in tables
        return

    # This test intentionally downgrades to a blank database and back, which
    # would wipe out tables other test modules share in the "public" schema
    # of the same live Postgres database used across the whole session. Run
    # it in its own throwaway schema instead so it never touches shared
    # state. alembic/env.py reads DATABASE_URL directly (taking priority over
    # the Config object's sqlalchemy.url), so the isolated schema must be
    # selected via the env var, not just the Config.
    base_engine = create_engine(db_url)
    schema_name = f"migration_test_{uuid.uuid4().hex[:8]}"
    with base_engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema_name}"'))
    try:
        # Note: the "=" is left unescaped (not "%3D") because alembic/env.py
        # re-sets sqlalchemy.url from os.environ verbatim, and configparser's
        # interpolation rejects any "%" in a value it hasn't escaped itself.
        isolated_url = f"{db_url}?options=-csearch_path={schema_name}"
        monkeypatch.setenv("DATABASE_URL", isolated_url)
        cfg = Config(str(alembic_ini))
        cfg.set_main_option("sqlalchemy.url", isolated_url)
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        command.upgrade(cfg, "head")

        engine = create_engine(isolated_url)
        tables = inspect(engine).get_table_names(schema=schema_name)
        assert "close_run" in tables
        assert "journal_line" in tables
        engine.dispose()
    finally:
        with base_engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema_name}" CASCADE'))
        base_engine.dispose()


def test_schema_tables_exist():
    """Required tables should exist in the schema after migration."""
    expected_tables = {
        "close_run",
        "settlement_event",
        "payout",
        "bank_line",
        "invoice",
        "gl_account",
        "journal_entry",
        "journal_line",
        "exception",
        "human_ruling",
        "rule",
        "proof_result",
        "audit_event",
    }

    db_url = os.getenv("DATABASE_URL")
    if db_url:
        engine = create_engine(db_url)
    else:
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)

    existing_tables = set(inspect(engine).get_table_names())
    assert expected_tables <= existing_tables


def test_close_run_table_columns():
    """close_run table should have expected columns with correct types."""
    expected_columns = {
        "id", "period", "status", "started_at", "finished_at",
        "rules_enabled", "seed", "metrics"
    }
    db_url = os.getenv("DATABASE_URL") or "sqlite:///:memory:"
    engine = create_engine(db_url)
    if "sqlite" in db_url:
        Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("close_run")}
    assert expected_columns <= cols


def test_monetary_columns_are_numeric():
    """All monetary columns must be NUMERIC(18,4) or NUMERIC(18,8), never float."""
    db_url = os.getenv("DATABASE_URL") or "sqlite:///:memory:"
    engine = create_engine(db_url)
    if "sqlite" in db_url:
        Base.metadata.create_all(bind=engine)
    inspector = inspect(engine)

    monetary_fields = [
        ("payout", "gross", 18, 4),
        ("payout", "fees", 18, 4),
        ("payout", "net", 18, 4),
        ("bank_line", "amount", 18, 4),
        ("invoice", "subtotal", 18, 4),
        ("invoice", "tax", 18, 4),
        ("invoice", "total", 18, 4),
        ("settlement_event", "amount_native", 18, 4),
        ("settlement_event", "amount_payout", 18, 4),
        ("settlement_event", "fx_rate", 18, 8),
        ("journal_line", "debit", 18, 4),
        ("journal_line", "credit", 18, 4),
        ("exception", "amount", 18, 4),
        ("proof_result", "expected", 18, 4),
        ("proof_result", "actual", 18, 4),
        ("proof_result", "delta", 18, 4),
    ]

    for table, col_name, exp_prec, exp_scale in monetary_fields:
        cols = {c["name"]: c for c in inspector.get_columns(table)}
        assert col_name in cols, f"{col_name} missing from {table}"
        col_type = cols[col_name]["type"]
        # Numeric check
        assert isinstance(col_type, NUMERIC) or hasattr(col_type, "precision"), (
            f"{table}.{col_name} is not NUMERIC: {col_type}"
        )
        if hasattr(col_type, "precision") and col_type.precision is not None:
            assert col_type.precision == exp_prec, (
                f"{table}.{col_name} precision {col_type.precision} != {exp_prec}"
            )
            assert col_type.scale == exp_scale, (
                f"{table}.{col_name} scale {col_type.scale} != {exp_scale}"
            )


def test_migrated_schema_matches_orm_metadata():
    """Migrated schema must match SQLAlchemy metadata for non-nullability and constraints."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        return
    engine = create_engine(db_url)
    inspector = inspect(engine)

    jl_cols = {c["name"]: c for c in inspector.get_columns("journal_line")}
    assert jl_cols["debit"]["nullable"] is False, "journal_line.debit must be NOT NULL"
    assert jl_cols["credit"]["nullable"] is False, "journal_line.credit must be NOT NULL"


def test_audit_event_append_only():
    """AuditEvent is append-only: updates and deletes must be rejected."""
    import pytest
    from sqlalchemy.orm import Session

    from backend.app.models.schema import AuditEvent, CloseRun

    db_url = os.getenv("DATABASE_URL") or "sqlite:///:memory:"
    engine = create_engine(db_url)
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        run = CloseRun(id="run_audit_test", period="2026-08", status="ingest")
        session.merge(run)
        session.flush()
        evt = AuditEvent(
            id="audit_test_1",
            run_id="run_audit_test",
            actor="system",
            action="test_created",
            subject_type="payout",
            subject_id="po_123",
            payload={"action": "test"},
        )
        session.add(evt)
        session.commit()

    with Session(engine) as session:
        fetched = session.get(AuditEvent, "audit_test_1")
        assert fetched is not None
        fetched.actor = "human"
        with pytest.raises(ValueError, match="audit_event is append-only and cannot be updated"):
            session.commit()
        session.rollback()

    with Session(engine) as session:
        fetched = session.get(AuditEvent, "audit_test_1")
        assert fetched is not None
        session.delete(fetched)
        with pytest.raises(ValueError, match="audit_event is append-only and cannot be deleted"):
            session.commit()
        session.rollback()


def test_exception_ground_truth_key_write_once():
    """Exception.ground_truth_key is write-once and cannot be changed once set."""
    from decimal import Decimal

    import pytest
    from sqlalchemy.orm import Session

    from backend.app.models.schema import CloseRun
    from backend.app.models.schema import Exception as ExceptionModel

    db_url = os.getenv("DATABASE_URL") or "sqlite:///:memory:"
    engine = create_engine(db_url)
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        run = CloseRun(id="run_gt_test", period="2026-08", status="ingest")
        session.merge(run)
        exc = ExceptionModel(
            id="exc_gt_test",
            run_id="run_gt_test",
            type="AMOUNT_MISMATCH",
            status="open",
            severity="medium",
            amount=Decimal("10.00"),
            currency="USD",
            confidence=Decimal("0.9500"),
            detected_by="detector",
            ground_truth_key="gt_AMOUNT_MISMATCH_2026-08",
        )
        session.add(exc)
        session.commit()

    # Allowed: updating non-ground_truth fields
    with Session(engine) as session:
        fetched = session.get(ExceptionModel, "exc_gt_test")
        assert fetched is not None
        fetched.status = "investigating"
        session.commit()
        assert fetched.status == "investigating"

    # Forbidden: updating ground_truth_key
    with Session(engine) as session:
        fetched = session.get(ExceptionModel, "exc_gt_test")
        assert fetched is not None
        fetched.ground_truth_key = "gt_AMOUNT_MISMATCH_tampered"
        with pytest.raises(ValueError, match="ground_truth_key is write-once"):
            session.commit()
        session.rollback()


