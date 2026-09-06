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
        occurred_at=datetime.utcnow(),
    )
    assert isinstance(event.amount_native, Decimal)
    assert isinstance(event.amount_payout, Decimal)
    assert isinstance(event.fx_rate, Decimal)
