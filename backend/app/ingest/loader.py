"""Load generated test data into the database."""
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.ingest.generator import TestDataGenerator
from backend.app.models.base import Base
from backend.app.models.schema import (
    BankLine,
    CloseRun,
    Invoice,
    Payout,
    SettlementEvent,
)


def get_db_url() -> str:
    """Get database URL from environment or use local Docker Postgres."""
    import os
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        db_url = "postgresql://tieout_user:tieout_pass@localhost:5432/tieout_db"
    return db_url


def load_test_data(seed: int = 42) -> None:
    """Generate and load test data into the database."""
    db_url = get_db_url()
    engine = create_engine(db_url, echo=False)

    # Create tables if they don't exist
    Base.metadata.create_all(engine)

    # Generate test data
    generator = TestDataGenerator(seed=seed)
    data, manifest = generator.generate_test_data()

    # Load into database
    with Session(engine) as session:
        for period, records in data.items():
            print(f"Loading {period}...")
            for record_type, record in records:
                if record_type == "run":
                    session.add(record)
                elif isinstance(record, (CloseRun, SettlementEvent, Payout, BankLine, Invoice)):
                    session.add(record)

        session.commit()
        print("Data loaded successfully!")

    # Print manifest
    print("\n--- Planted Exceptions Manifest ---")
    for exc in manifest:
        print(f"\n{exc.exception_type} ({exc.period}):")
        print(f"  Expected resolution: {exc.expected_resolution}")
        print(f"  Description: {exc.description}")
        print(f"  Ground truth key: {exc.ground_truth_key}")


if __name__ == "__main__":
    load_test_data()
