"""Deterministic test data generator with planted exceptions.

This module plants known exception types into test data for August and September.
All generation is seeded for reproducibility. The manifest lists every planted
exception type, its period, and expected resolution.
"""
import random
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from backend.app.models.schema import (
    BankLine,
    CloseRun,
    Invoice,
    Payout,
    SettlementEvent,
)


class PlantedException:
    """Documents a planted exception for the manifest."""

    def __init__(
        self,
        exception_type: str,
        period: str,
        expected_resolution: str,
        description: str,
    ):
        self.exception_type = exception_type
        self.period = period
        self.expected_resolution = expected_resolution
        self.description = description
        self.ground_truth_key = f"gt_{exception_type}_{period}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "exception_type": self.exception_type,
            "period": self.period,
            "expected_resolution": self.expected_resolution,
            "description": self.description,
            "ground_truth_key": self.ground_truth_key,
        }


class TestDataGenerator:
    """Generates deterministic test data with seeded randomness."""

    def __init__(self, seed: int = 42):
        self.seed = seed
        random.seed(seed)
        self.planted_exceptions: list[PlantedException] = []

    def generate_payout(
        self,
        run_id: str,
        gross: Decimal,
        fees: Decimal,
        period: str,
        days_offset: int = 0,
    ) -> Payout:
        """Generate a payout record."""
        payout_id = str(uuid.uuid4())[:8]
        created_at = datetime(2026, int(period.split("-")[1]), 1) + timedelta(days=days_offset)

        return Payout(
            id=f"po_{payout_id}",
            run_id=run_id,
            external_id=f"ext_payout_{payout_id}",
            status="completed",
            created_at=created_at,
            settled_at=created_at + timedelta(hours=2),
            gross=gross,
            fees=fees,
            net=gross - fees,
            currency="USD",
            bank_line_id=None,
        )

    def generate_settlement_event(
        self,
        run_id: str,
        payout_id: str,
        event_type: str,
        amount: Decimal,
        occurred_at: datetime,
        fx_rate: Decimal = Decimal("1.0"),
    ) -> SettlementEvent:
        """Generate a settlement event."""
        event_id = str(uuid.uuid4())[:8]

        return SettlementEvent(
            id=f"se_{event_id}",
            run_id=run_id,
            source="seed",
            external_id=f"evt_{event_id}",
            event_type=event_type,
            payout_id=payout_id,
            order_id=f"ord_{random.randint(1000, 9999)}",
            customer_id=f"cust_{random.randint(1000, 9999)}",
            occurred_at=occurred_at,
            amount_native=amount,
            currency_native="USD",
            amount_payout=amount * fx_rate,
            currency_payout="USD",
            fx_rate=fx_rate,
            fx_source="dodo_spot_rate",
            raw={},
        )

    def generate_bank_line(
        self,
        run_id: str,
        amount: Decimal,
        posted_at: datetime,
    ) -> BankLine:
        """Generate a bank deposit line."""
        return BankLine(
            id=str(uuid.uuid4())[:8],
            run_id=run_id,
            posted_at=posted_at,
            amount=amount,
            currency="USD",
            description="Settlement deposit",
            matched_payout_id=None,
        )

    def generate_invoice(
        self,
        run_id: str,
        subtotal: Decimal,
        tax_rate: Decimal = Decimal("0.1"),
    ) -> Invoice:
        """Generate an invoice."""
        tax = (subtotal * tax_rate).quantize(Decimal("0.01"))

        return Invoice(
            id=str(uuid.uuid4())[:8],
            run_id=run_id,
            external_id=f"inv_{random.randint(100000, 999999)}",
            customer_id=f"cust_{random.randint(1000, 9999)}",
            issued_at=datetime.utcnow(),
            subtotal=subtotal,
            tax=tax,
            total=subtotal + tax,
            currency="USD",
            line_items={"sku": "PROD_001", "qty": 1},
        )

    def plant_amount_mismatch_august(self, run_id: str) -> tuple[list[Any], PlantedException]:
        """Plant AMOUNT_MISMATCH exception (sum of events != payout.net)."""
        gross = Decimal("1000.00")
        fees = Decimal("50.00")
        payout_id = f"po_{uuid.uuid4().hex[:8]}"
        net_amount = gross - fees
        occurred_at = datetime(2026, 8, 6)
        settled_at = occurred_at + timedelta(hours=2)

        payout = Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext_payout_{payout_id}",
            status="completed",
            created_at=occurred_at,
            settled_at=settled_at,
            gross=gross,
            fees=fees,
            net=net_amount,
            currency="USD",
            bank_line_id=None,
        )

        # Create events that sum to slightly more than net (sub-cent rounding)
        events = [
            self.generate_settlement_event(
                run_id, payout_id, "payment", Decimal("500.01"), occurred_at
            ),
            self.generate_settlement_event(
                run_id, payout_id, "payment", Decimal("250.00"), occurred_at + timedelta(hours=1)
            ),
            self.generate_settlement_event(
                run_id, payout_id, "payment", Decimal("200.00"), occurred_at + timedelta(hours=2)
            ),
        ]

        bank_line = self.generate_bank_line(run_id, net_amount, settled_at)

        exception = PlantedException(
            exception_type="AMOUNT_MISMATCH",
            period="2026-08",
            expected_resolution="auto_resolved_to_7490",
            description="Sum of events exceeds payout.net by 0.01; post to rounding account 7490",
        )
        self.planted_exceptions.append(exception)

        return [payout] + events + [bank_line], exception

    def plant_fx_variance_august(self, run_id: str) -> tuple[list[Any], PlantedException]:
        """Plant FX_VARIANCE exception (settlement rate differs from booked rate)."""
        gross = Decimal("2000.00")
        fees = Decimal("100.00")
        payout_id = f"po_{uuid.uuid4().hex[:8]}"
        net_amount = gross - fees
        occurred_at = datetime(2026, 8, 11)
        settled_at = occurred_at + timedelta(hours=2)
        booked_fx = Decimal("1.05")
        settled_fx = Decimal("1.08")  # 3% variance

        payout = Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext_payout_{payout_id}",
            status="completed",
            created_at=occurred_at,
            settled_at=settled_at,
            gross=gross,
            fees=fees,
            net=net_amount,
            currency="USD",
            bank_line_id=None,
        )

        events = [
            self.generate_settlement_event(
                run_id,
                payout_id,
                "payment",
                Decimal("1900.00"),
                occurred_at,
                fx_rate=settled_fx,
            ),
        ]

        bank_line = self.generate_bank_line(run_id, net_amount, settled_at)

        exception = PlantedException(
            exception_type="FX_VARIANCE",
            period="2026-08",
            expected_resolution="escalate_exceeds_250_threshold",
            description=(
                f"FX rate variance: booked {booked_fx}, settled {settled_fx}. "
                "Amount impact > $250."
            ),
        )
        self.planted_exceptions.append(exception)

        return [payout] + events + [bank_line], exception

    def plant_dispute_incomplete_september(self, run_id: str) -> tuple[list[Any], PlantedException]:
        """Plant DISPUTE_LIFECYCLE_INCOMPLETE (dispute opened in period, unresolved at end)."""
        gross = Decimal("5000.00")
        fees = Decimal("200.00")
        payout_id = f"po_{uuid.uuid4().hex[:8]}"
        net_amount = gross - fees
        occurred_at = datetime(2026, 9, 16)
        settled_at = occurred_at + timedelta(hours=2)

        payout = Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext_payout_{payout_id}",
            status="completed",
            created_at=occurred_at,
            settled_at=settled_at,
            gross=gross,
            fees=fees,
            net=net_amount,
            currency="USD",
            bank_line_id=None,
        )

        events = [
            self.generate_settlement_event(
                run_id, payout_id, "payment", Decimal("4900.00"), occurred_at
            ),
            self.generate_settlement_event(
                run_id, payout_id, "dispute_opened", Decimal("-100.00"), occurred_at
            ),
        ]

        bank_line = self.generate_bank_line(run_id, net_amount, settled_at)

        exception = PlantedException(
            exception_type="DISPUTE_LIFECYCLE_INCOMPLETE",
            period="2026-09",
            expected_resolution="escalate_always",
            description=(
                "Dispute opened on 2026-09-15, not resolved by period end. "
                "Requires loss provision."
            ),
        )
        self.planted_exceptions.append(exception)

        return [payout] + events + [bank_line], exception

    def plant_fee_anomaly_september(self, run_id: str) -> tuple[list[Any], PlantedException]:
        """Plant FEE_ANOMALY (effective fee rate outside expected band)."""
        gross = Decimal("10000.00")
        fees = Decimal("600.00")  # 6% -- unusually high
        payout_id = f"po_{uuid.uuid4().hex[:8]}"
        net_amount = gross - fees
        occurred_at = datetime(2026, 9, 21)
        settled_at = occurred_at + timedelta(hours=2)

        payout = Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext_payout_{payout_id}",
            status="completed",
            created_at=occurred_at,
            settled_at=settled_at,
            gross=gross,
            fees=fees,
            net=net_amount,
            currency="USD",
            bank_line_id=None,
        )

        events = [
            self.generate_settlement_event(
                run_id, payout_id, "payment", Decimal("9400.00"), occurred_at
            ),
            self.generate_settlement_event(
                run_id, payout_id, "processing_fee", Decimal("-300.00"), occurred_at
            ),
            self.generate_settlement_event(
                run_id, payout_id, "platform_fee", Decimal("-300.00"), occurred_at
            ),
        ]

        bank_line = self.generate_bank_line(run_id, net_amount, settled_at)

        exception = PlantedException(
            exception_type="FEE_ANOMALY",
            period="2026-09",
            expected_resolution="escalate_unexplained",
            description="Effective fee rate 6% is outside historical band (2-4%). Unexplained.",
        )
        self.planted_exceptions.append(exception)

        return [payout] + events + [bank_line], exception

    def plant_timing_cutoff_september(self, run_id: str) -> tuple[list[Any], PlantedException]:
        """Plant TIMING_CUTOFF (payout spans period boundary)."""
        gross = Decimal("3000.00")
        fees = Decimal("100.00")
        payout_id = f"po_{uuid.uuid4().hex[:8]}"
        net_amount = gross - fees
        occurred_at = datetime(2026, 9, 29)
        settled_at = datetime(2026, 10, 2)

        payout = Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext_payout_{payout_id}",
            status="completed",
            created_at=occurred_at,
            settled_at=settled_at,
            gross=gross,
            fees=fees,
            net=net_amount,
            currency="USD",
            bank_line_id=None,
        )

        events = [
            self.generate_settlement_event(
                run_id, payout_id, "payment", Decimal("2900.00"), occurred_at
            ),
        ]

        bank_line = self.generate_bank_line(run_id, net_amount, settled_at)

        exception = PlantedException(
            exception_type="TIMING_CUTOFF",
            period="2026-09",
            expected_resolution="auto_resolved_via_intransit",
            description=(
                "Payout created Sept 28, settled Oct 1 (spans boundary). "
                "Split via 1330 In-Transit."
            ),
        )
        self.planted_exceptions.append(exception)

        return [payout] + events + [bank_line], exception

    def plant_low_confidence_classification_september(
        self, run_id: str
    ) -> tuple[list[Any], PlantedException]:
        """Plant LOW_CONFIDENCE_CLASSIFICATION (classifier < 0.85 threshold)."""
        gross = Decimal("800.00")
        fees = Decimal("40.00")
        payout_id = f"po_{uuid.uuid4().hex[:8]}"
        net_amount = gross - fees
        occurred_at = datetime(2026, 9, 26)
        settled_at = occurred_at + timedelta(hours=2)

        payout = Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext_payout_{payout_id}",
            status="completed",
            created_at=occurred_at,
            settled_at=settled_at,
            gross=gross,
            fees=fees,
            net=net_amount,
            currency="USD",
            bank_line_id=None,
        )

        events = [
            self.generate_settlement_event(
                run_id, payout_id, "payment", Decimal("760.00"), occurred_at
            ),
        ]

        bank_line = self.generate_bank_line(run_id, net_amount, settled_at)

        exception = PlantedException(
            exception_type="LOW_CONFIDENCE_CLASSIFICATION",
            period="2026-09",
            expected_resolution="escalate_always",
            description=(
                "GL account assignment confidence 0.72 (below 0.85 threshold). "
                "Requires human classification."
            ),
        )
        self.planted_exceptions.append(exception)

        return [payout] + events + [bank_line], exception

    def plant_bank_unmatched_august(self, run_id: str) -> tuple[list[Any], PlantedException]:
        """Plant BANK_UNMATCHED (payout with no corresponding bank deposit)."""
        gross = Decimal("1500.00")
        fees = Decimal("75.00")
        payout_id = f"po_{uuid.uuid4().hex[:8]}"
        net_amount = gross - fees
        occurred_at = datetime(2026, 8, 13)
        settled_at = occurred_at + timedelta(hours=2)

        payout = Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext_payout_{payout_id}",
            status="completed",
            created_at=occurred_at,
            settled_at=settled_at,
            gross=gross,
            fees=fees,
            net=net_amount,
            currency="USD",
            bank_line_id=None,
        )

        events = [
            self.generate_settlement_event(
                run_id, payout_id, "payment", Decimal("1425.00"), occurred_at
            ),
        ]

        # Do NOT create matching bank line
        exception = PlantedException(
            exception_type="BANK_UNMATCHED",
            period="2026-08",
            expected_resolution="escalate_no_matching_deposit",
            description="Payout marked completed but no bank deposit found within 3-day window.",
        )
        self.planted_exceptions.append(exception)

        return [payout] + events, exception

    def generate_clean_data_august(self, run_id: str) -> list[Any]:
        """Generate clean (no exceptions) data for August baseline."""
        gross = Decimal("5000.00")
        fees = Decimal("250.00")
        payout_id = f"po_{uuid.uuid4().hex[:8]}"
        net_amount = gross - fees
        occurred_at = datetime(2026, 8, 2)
        settled_at = occurred_at + timedelta(hours=2)

        payout = Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext_payout_{payout_id}",
            status="completed",
            created_at=occurred_at,
            settled_at=settled_at,
            gross=gross,
            fees=fees,
            net=net_amount,
            currency="USD",
            bank_line_id=None,
        )

        events = [
            self.generate_settlement_event(
                run_id, payout_id, "payment", Decimal("4750.00"), occurred_at
            ),
        ]

        bank_line = self.generate_bank_line(run_id, net_amount, settled_at)

        return [payout] + events + [bank_line]

    def generate_clean_data_september(self, run_id: str) -> list[Any]:
        """Generate clean (no exceptions) data for September baseline."""
        gross = Decimal("8000.00")
        fees = Decimal("400.00")
        payout_id = f"po_{uuid.uuid4().hex[:8]}"
        net_amount = gross - fees
        occurred_at = datetime(2026, 9, 2)
        settled_at = occurred_at + timedelta(hours=2)

        payout = Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext_payout_{payout_id}",
            status="completed",
            created_at=occurred_at,
            settled_at=settled_at,
            gross=gross,
            fees=fees,
            net=net_amount,
            currency="USD",
            bank_line_id=None,
        )

        events = [
            self.generate_settlement_event(
                run_id, payout_id, "payment", Decimal("7600.00"), occurred_at
            ),
        ]

        bank_line = self.generate_bank_line(run_id, net_amount, settled_at)

        return [payout] + events + [bank_line]

    def generate_test_data(self) -> tuple[dict[str, Any], list[PlantedException]]:
        """
        Generate full test dataset with planted exceptions for August and September.
        Returns (data_by_period, planted_exceptions_manifest).
        """
        data = {"2026-08": [], "2026-09": []}

        # August: clean baseline + exceptions
        august_run_id = str(uuid.uuid4())[:8]
        august_run = CloseRun(
            id=f"run_{august_run_id}",
            period="2026-08",
            status="ingest",
            seed=self.seed,
        )
        data["2026-08"].append(("run", august_run))

        data["2026-08"].extend(self.generate_clean_data_august(f"run_{august_run_id}"))

        # Plant exceptions for August
        payout_data, _ = self.plant_amount_mismatch_august(f"run_{august_run_id}")
        data["2026-08"].extend([("record", r) for r in payout_data])

        payout_data, _ = self.plant_fx_variance_august(f"run_{august_run_id}")
        data["2026-08"].extend([("record", r) for r in payout_data])

        payout_data, _ = self.plant_bank_unmatched_august(f"run_{august_run_id}")
        data["2026-08"].extend([("record", r) for r in payout_data])

        # September: clean baseline + exceptions
        september_run_id = str(uuid.uuid4())[:8]
        september_run = CloseRun(
            id=f"run_{september_run_id}",
            period="2026-09",
            status="ingest",
            seed=self.seed,
        )
        data["2026-09"].append(("run", september_run))

        data["2026-09"].extend(self.generate_clean_data_september(f"run_{september_run_id}"))

        # Plant exceptions for September
        payout_data, _ = self.plant_dispute_incomplete_september(f"run_{september_run_id}")
        data["2026-09"].extend([("record", r) for r in payout_data])

        payout_data, _ = self.plant_fee_anomaly_september(f"run_{september_run_id}")
        data["2026-09"].extend([("record", r) for r in payout_data])

        payout_data, _ = self.plant_timing_cutoff_september(f"run_{september_run_id}")
        data["2026-09"].extend([("record", r) for r in payout_data])

        sept_run_id = f"run_{september_run_id}"
        payout_data, _ = self.plant_low_confidence_classification_september(sept_run_id)
        data["2026-09"].extend([("record", r) for r in payout_data])

        return data, self.planted_exceptions
