"""Tests for test data generator."""
from decimal import Decimal

from backend.app.ingest.generator import PlantedException, TestDataGenerator


def test_generator_initialization():
    """Test that generator initializes with seed."""
    gen = TestDataGenerator(seed=42)
    assert gen.seed == 42


def test_payout_generation():
    """Test payout generation produces correct structure."""
    gen = TestDataGenerator(seed=42)
    payout = gen.generate_payout(
        run_id="run_test",
        gross=Decimal("1000.00"),
        fees=Decimal("50.00"),
        period="2026-08",
    )

    assert payout.run_id == "run_test"
    assert payout.gross == Decimal("1000.00")
    assert payout.fees == Decimal("50.00")
    assert payout.net == Decimal("950.00")
    assert payout.currency == "USD"
    assert payout.status == "completed"


def test_settlement_event_generation():
    """Test settlement event generation."""
    gen = TestDataGenerator(seed=42)
    from datetime import datetime

    occurred_at = datetime.utcnow()
    event = gen.generate_settlement_event(
        run_id="run_test",
        payout_id="po_test",
        event_type="payment",
        amount=Decimal("500.00"),
        occurred_at=occurred_at,
        fx_rate=Decimal("1.05"),
    )

    assert event.run_id == "run_test"
    assert event.payout_id == "po_test"
    assert event.event_type == "payment"
    assert event.amount_native == Decimal("500.00")
    assert event.amount_payout == Decimal("525.00")  # 500 * 1.05
    assert event.fx_rate == Decimal("1.05")
    assert event.source == "seed"


def test_bank_line_generation():
    """Test bank line generation."""
    gen = TestDataGenerator(seed=42)
    from datetime import datetime

    posted_at = datetime.utcnow()
    bank_line = gen.generate_bank_line(
        run_id="run_test",
        amount=Decimal("950.00"),
        posted_at=posted_at,
    )

    assert bank_line.run_id == "run_test"
    assert bank_line.amount == Decimal("950.00")
    assert bank_line.currency == "USD"
    assert bank_line.matched_payout_id is None


def test_invoice_generation():
    """Test invoice generation."""
    gen = TestDataGenerator(seed=42)

    invoice = gen.generate_invoice(
        run_id="run_test",
        subtotal=Decimal("1000.00"),
        tax_rate=Decimal("0.1"),
    )

    assert invoice.run_id == "run_test"
    assert invoice.subtotal == Decimal("1000.00")
    assert invoice.tax == Decimal("100.00")
    assert invoice.total == Decimal("1100.00")
    assert invoice.currency == "USD"


def test_amount_mismatch_planting():
    """Test AMOUNT_MISMATCH exception planting."""
    gen = TestDataGenerator(seed=42)
    records, exception = gen.plant_amount_mismatch_august("run_test")

    assert len(records) >= 5  # payout + 3 events + bank line
    assert exception.exception_type == "AMOUNT_MISMATCH"
    assert exception.period == "2026-08"
    assert exception.ground_truth_key.startswith("gt_")


def test_fx_variance_planting():
    """Test FX_VARIANCE exception planting."""
    gen = TestDataGenerator(seed=42)
    records, exception = gen.plant_fx_variance_august("run_test")

    assert len(records) >= 3  # payout + event + bank line
    assert exception.exception_type == "FX_VARIANCE"
    assert exception.period == "2026-08"


def test_planted_exception_dict():
    """Test PlantedException converts to dict correctly."""
    exc = PlantedException(
        exception_type="TEST_TYPE",
        period="2026-08",
        expected_resolution="test_resolution",
        description="Test description",
    )

    exc_dict = exc.to_dict()
    assert exc_dict["exception_type"] == "TEST_TYPE"
    assert exc_dict["period"] == "2026-08"
    assert exc_dict["expected_resolution"] == "test_resolution"
    assert "ground_truth_key" in exc_dict


def test_full_test_data_generation():
    """Test full test data generation for both periods."""
    gen = TestDataGenerator(seed=42)
    data, manifest = gen.generate_test_data()

    # Check both periods exist
    assert "2026-08" in data
    assert "2026-09" in data

    # Check manifest has entries
    assert len(manifest) > 0

    # Check that August has 3 planted exceptions
    august_exceptions = [e for e in manifest if e.period == "2026-08"]
    assert len(august_exceptions) == 3  # AMOUNT_MISMATCH, FX_VARIANCE, BANK_UNMATCHED

    # Check that September has 4 planted exceptions
    september_exceptions = [e for e in manifest if e.period == "2026-09"]
    assert len(september_exceptions) == 4  # DISPUTE, FEE_ANOMALY, TIMING_CUTOFF, LOW_CONFIDENCE


def test_deterministic_generation():
    """Test that same seed produces same data."""
    gen1 = TestDataGenerator(seed=42)
    data1, manifest1 = gen1.generate_test_data()

    gen2 = TestDataGenerator(seed=42)
    data2, manifest2 = gen2.generate_test_data()

    # Check manifest entries match (in terms of structure)
    assert len(manifest1) == len(manifest2)
    for e1, e2 in zip(manifest1, manifest2):
        assert e1.exception_type == e2.exception_type
        assert e1.period == e2.period


def test_decimal_preservation():
    """Test that Decimal types are preserved throughout."""
    gen = TestDataGenerator(seed=42)

    # Test payout
    payout = gen.generate_payout(
        run_id="run_test",
        gross=Decimal("1000.00"),
        fees=Decimal("50.00"),
        period="2026-08",
    )
    assert isinstance(payout.gross, Decimal)
    assert isinstance(payout.fees, Decimal)
    assert isinstance(payout.net, Decimal)

    # Test settlement event
    from datetime import datetime
    event = gen.generate_settlement_event(
        run_id="run_test",
        payout_id="po_test",
        event_type="payment",
        amount=Decimal("500.00"),
        occurred_at=datetime(2026, 8, 1, 10, 0, 0),
    )
    assert isinstance(event.amount_native, Decimal)
    assert isinstance(event.amount_payout, Decimal)
    assert isinstance(event.fx_rate, Decimal)


def test_generator_not_collected_as_test():
    """TestDataGenerator must have __test__ = False to prevent pytest warnings."""
    assert TestDataGenerator.__test__ is False


def test_chart_of_accounts_has_17_accounts():
    """get_chart_of_accounts must return the exact 17 accounts from 01-chart-of-accounts.md."""
    from backend.app.ingest.generator import get_chart_of_accounts

    accounts = get_chart_of_accounts()
    assert len(accounts) == 17

    codes = {acc.code for acc in accounts}
    expected_codes = {
        "1010", "1200", "1310", "1320", "1330",
        "2100", "2200", "2400",
        "4010", "4020", "4900",
        "5100", "5110", "6810", "6820",
        "7410", "7490",
    }
    assert codes == expected_codes


def test_records_are_standardized_tuples():
    """All records returned by generate_test_data must be (record_type, obj) tuples."""
    gen = TestDataGenerator(seed=42)
    data, _ = gen.generate_test_data()

    for period in ("2026-08", "2026-09"):
        for item in data[period]:
            assert isinstance(item, tuple)
            assert len(item) == 2
            record_type, obj = item
            assert isinstance(record_type, str)
            assert hasattr(obj, "__tablename__")


def test_exact_determinism_across_runs():
    """Identical seeds must produce byte-for-byte identical IDs and attributes."""
    gen1 = TestDataGenerator(seed=42)
    data1, _ = gen1.generate_test_data()

    gen2 = TestDataGenerator(seed=42)
    data2, _ = gen2.generate_test_data()

    for period in ("2026-08", "2026-09"):
        records1 = data1[period]
        records2 = data2[period]
        assert len(records1) == len(records2)
        for (t1, r1), (t2, r2) in zip(records1, records2):
            assert t1 == t2
            if hasattr(r1, "id") and hasattr(r2, "id"):
                assert r1.id == r2.id

    # Different seeds must produce different IDs
    gen3 = TestDataGenerator(seed=99)
    data3, _ = gen3.generate_test_data()
    ids1 = [r.id for _, r in data1["2026-08"] if hasattr(r, "id")]
    ids3 = [r.id for _, r in data3["2026-08"] if hasattr(r, "id")]
    assert ids1 != ids3


def test_loader_idempotent():
    """load_test_data must succeed and be safely re-runnable."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from backend.app.ingest.loader import load_test_data
    from backend.app.models.schema import CloseRun, GLAccount

    engine = create_engine("sqlite:///:memory:")
    # First load
    load_test_data(seed=42, engine=engine)

    with Session(engine) as session:
        runs = session.query(CloseRun).all()
        assert len(runs) == 2
        accounts = session.query(GLAccount).all()
        assert len(accounts) == 17

    # Second load with same seed should cleanly reload without unique constraint error
    load_test_data(seed=42, engine=engine)

    with Session(engine) as session:
        runs = session.query(CloseRun).all()
        assert len(runs) == 2
        accounts = session.query(GLAccount).all()
        assert len(accounts) == 17

