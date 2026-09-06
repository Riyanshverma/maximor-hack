"""Shared pytest fixtures for the backend test suite.

CI runs the whole backend/tests/ suite against a single live PostgreSQL
service container (DATABASE_URL points at one database for the entire
pytest session). Several test modules manage schema differently: some
create tables via ``Base.metadata.create_all`` against a per-test SQLite
file, others do the same directly against the shared Postgres database.
Neither of those individually establishes the schema Alembic itself is
responsible for, so whichever module happens to run first against Postgres
before any schema exists fails with "relation ... does not exist".

This fixture runs once per session and, only when DATABASE_URL points at
Postgres, resets the "public" schema and applies the Alembic migrations so
every module can rely on the full schema being present regardless of
collection order.
"""
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


def _alembic_config(db_url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _baseline_postgres_schema():
    db_url = os.getenv("DATABASE_URL")
    if not db_url or not db_url.startswith("postgresql"):
        yield
        return

    engine = create_engine(db_url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()

    command.upgrade(_alembic_config(db_url), "head")
    yield
