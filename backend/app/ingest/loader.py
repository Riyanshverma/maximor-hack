"""Load generated test data into the database."""
import os
from typing import Any, cast

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.app.ingest.generator import (
    PlantedException,
    TestDataGenerator,
    get_chart_of_accounts,
)
from backend.app.models.base import Base
from backend.app.models.schema import (
    BankLine,
    CloseRun,
    GLAccount,
    Invoice,
    JournalEntry,
    JournalLine,
    Payout,
    ProofResult,
    SettlementEvent,
)
from backend.app.models.schema import (
    Exception as ExceptionModel,
)


def get_db_url() -> str:
    """Get database URL from environment or use local Docker Postgres."""
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        db_url = "postgresql://tieout:tieout_dev@localhost:5432/tieout"
    return db_url


def _cleanup_run(session: Session, run_id: str) -> None:
    """Remove existing records for a run in reverse dependency order."""
    je_subquery = select(JournalEntry.id).where(JournalEntry.run_id == run_id)
    session.query(JournalLine).filter(JournalLine.entry_id.in_(je_subquery)).delete(
        synchronize_session=False
    )
    session.query(JournalEntry).filter(JournalEntry.run_id == run_id).delete(
        synchronize_session=False
    )
    session.query(ProofResult).filter(ProofResult.run_id == run_id).delete(
        synchronize_session=False
    )
    session.query(SettlementEvent).filter(SettlementEvent.run_id == run_id).delete(
        synchronize_session=False
    )
    # Break circular FK between Payout and BankLine before deletion
    session.query(BankLine).filter(BankLine.run_id == run_id).update(
        {BankLine.matched_payout_id: None}, synchronize_session=False
    )
    session.query(Payout).filter(Payout.run_id == run_id).update(
        {Payout.bank_line_id: None}, synchronize_session=False
    )
    session.query(BankLine).filter(BankLine.run_id == run_id).delete(
        synchronize_session=False
    )
    session.query(Payout).filter(Payout.run_id == run_id).delete(
        synchronize_session=False
    )
    session.query(Invoice).filter(Invoice.run_id == run_id).delete(
        synchronize_session=False
    )
    session.query(ExceptionModel).filter(ExceptionModel.run_id == run_id).delete(
        synchronize_session=False
    )
    session.query(CloseRun).filter(CloseRun.id == run_id).delete(
        synchronize_session=False
    )


def _load_with_session(
    session: Session,
    seed: int = 42,
) -> tuple[dict[str, Any], list[PlantedException]]:
    generator = TestDataGenerator(seed=seed)
    data, manifest = generator.generate_test_data()

    # 1. Seed Chart of Accounts
    for acc in get_chart_of_accounts():
        session.merge(acc)

    # 2. Collect runs to clean up idempotently
    run_ids: set[str] = set()
    for _period, records in data.items():
        for _record_type, record in records:
            if isinstance(record, CloseRun):
                run_ids.add(cast(str, record.id))

    for rid in run_ids:
        _cleanup_run(session, rid)
    session.flush()

    # 3. Sort records by dependency order
    type_priority = {
        CloseRun: 1,
        Payout: 2,
        BankLine: 3,
        SettlementEvent: 4,
        Invoice: 5,
        JournalEntry: 6,
        JournalLine: 7,
    }

    all_records = []
    for _period, records in data.items():
        for _record_type, record in records:
            if isinstance(record, GLAccount):
                continue
            all_records.append(record)

    all_records.sort(key=lambda r: type_priority.get(type(r), 99))

    for rec in all_records:
        session.add(rec)

    session.flush()
    return data, manifest


def load_test_data(
    seed: int = 42,
    engine: Engine | None = None,
    session: Session | None = None,
) -> tuple[dict[str, Any], list[PlantedException]]:
    """Generate and load test data into the database.

    Loads in a single transaction with dependency order and rollback on error.
    Idempotent across multiple runs.
    """
    if session is not None:
        return _load_with_session(session, seed)

    if engine is None:
        db_url = get_db_url()
        engine = create_engine(db_url, echo=False)

    Base.metadata.create_all(engine)

    with Session(engine) as sess:
        try:
            result = _load_with_session(sess, seed)
            sess.commit()
            return result
        except Exception:
            sess.rollback()
            raise


if __name__ == "__main__":
    _, manifest = load_test_data()
    print("\n--- Planted Exceptions Manifest ---")
    for exc in manifest:
        print(f"\n{exc.exception_type} ({exc.period}):")
        print(f"  Expected resolution: {exc.expected_resolution}")
        print(f"  Description: {exc.description}")
        print(f"  Ground truth key: {exc.ground_truth_key}")
