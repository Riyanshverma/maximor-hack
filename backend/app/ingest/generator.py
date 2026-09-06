"""Deterministic test data generator with planted exceptions.

This module plants known exception types into test data for August and September.
All generation is seeded for reproducibility. The manifest lists every planted
exception type, its period, and expected resolution.
"""
import hashlib
import random
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from backend.app.models.schema import (
    BankLine,
    CloseRun,
    GLAccount,
    Invoice,
    JournalEntry,
    JournalLine,
    Payout,
    SettlementEvent,
)


def get_chart_of_accounts() -> list[GLAccount]:
    """Return the exact 17 General Ledger accounts defined in docs/01-chart-of-accounts.md."""
    return [
        GLAccount(code="1010", name="Cash — Operating Bank", type="asset", normal_side="debit"),
        GLAccount(code="1200", name="Accounts Receivable", type="asset", normal_side="debit"),
        GLAccount(code="1310", name="MoR Clearing — Dodo", type="asset", normal_side="debit"),
        GLAccount(code="1320", name="MoR Reserve Receivable", type="asset", normal_side="debit"),
        GLAccount(code="1330", name="MoR In-Transit", type="asset", normal_side="debit"),
        GLAccount(
            code="2100",
            name="Sales Tax / VAT Payable — MoR remitted",
            type="liability",
            normal_side="credit",
        ),
        GLAccount(code="2200", name="Refunds Payable", type="liability", normal_side="credit"),
        GLAccount(code="2400", name="Deferred Revenue", type="liability", normal_side="credit"),
        GLAccount(code="4010", name="Subscription Revenue", type="revenue", normal_side="credit"),
        GLAccount(
            code="4020",
            name="One-Time Product Revenue",
            type="revenue",
            normal_side="credit",
        ),
        GLAccount(
            code="4900",
            name="Refunds & Allowances",
            type="contra-revenue",
            normal_side="debit",
        ),
        GLAccount(code="5100", name="Payment Processing Fees", type="expense", normal_side="debit"),
        GLAccount(code="5110", name="MoR Platform Fees", type="expense", normal_side="debit"),
        GLAccount(
            code="6810",
            name="Chargeback & Dispute Losses",
            type="expense",
            normal_side="debit",
        ),
        GLAccount(code="6820", name="Dispute Fees", type="expense", normal_side="debit"),
        GLAccount(code="7410", name="Realized FX Gain / (Loss)", type="other", normal_side="debit"),
        GLAccount(code="7490", name="Rounding Adjustment", type="other", normal_side="debit"),
    ]


def record_type_for(record: Any) -> str:
    """Return the record type string for a given model instance."""
    if isinstance(record, CloseRun):
        return "run"
    if isinstance(record, GLAccount):
        return "gl_account"
    if isinstance(record, Payout):
        return "payout"
    if isinstance(record, BankLine):
        return "bank_line"
    if isinstance(record, SettlementEvent):
        return "settlement_event"
    if isinstance(record, Invoice):
        return "invoice"
    if isinstance(record, JournalEntry):
        return "journal_entry"
    if isinstance(record, JournalLine):
        return "journal_line"
    return "record"


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

    __test__ = False

    def __init__(self, seed: int = 42):
        self.seed = seed
        self._counter = 0
        self.rng = random.Random(seed)
        self.planted_exceptions: list[PlantedException] = []

    def _next_hex(self, tag: str) -> str:
        self._counter += 1
        raw = f"{self.seed}:{tag}:{self._counter}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:8]

    def get_chart_of_accounts(self) -> list[GLAccount]:
        return get_chart_of_accounts()

    def generate_payout(
        self,
        run_id: str,
        gross: Decimal,
        fees: Decimal,
        period: str,
        days_offset: int = 0,
    ) -> Payout:
        """Generate a payout record."""
        payout_id = self._next_hex("payout")
        month = int(period.split("-")[1])
        created_at = datetime(2026, month, 1, 10, 0, 0) + timedelta(days=days_offset)

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
        amount_payout: Decimal | None = None,
        raw: dict[str, Any] | None = None,
    ) -> SettlementEvent:
        """Generate a settlement event."""
        event_id = self._next_hex("event")
        cust_id = self._next_hex("cust")
        ord_id = self._next_hex("order")

        computed_payout_amount = (
            amount_payout if amount_payout is not None else amount * fx_rate
        )

        return SettlementEvent(
            id=f"se_{event_id}",
            run_id=run_id,
            source="seed",
            external_id=f"evt_{event_id}",
            event_type=event_type,
            payout_id=payout_id,
            order_id=f"ord_{ord_id}",
            customer_id=f"cust_{cust_id}",
            occurred_at=occurred_at,
            amount_native=amount,
            currency_native="USD",
            amount_payout=computed_payout_amount,
            currency_payout="USD",
            fx_rate=fx_rate,
            fx_source="dodo_spot_rate",
            raw=raw or {},
        )

    def generate_bank_line(
        self,
        run_id: str,
        amount: Decimal,
        posted_at: datetime,
    ) -> BankLine:
        """Generate a bank deposit line."""
        bl_id = self._next_hex("bank_line")
        return BankLine(
            id=f"bl_{bl_id}",
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
        issued_at: datetime | None = None,
    ) -> Invoice:
        """Generate an invoice."""
        inv_id = self._next_hex("invoice")
        cust_id = self._next_hex("cust")
        tax = (subtotal * tax_rate).quantize(Decimal("0.01"))
        if issued_at is None:
            issued_at = datetime(2026, 8, 1, 10, 0, 0)

        return Invoice(
            id=f"inv_{inv_id}",
            run_id=run_id,
            external_id=f"inv_ext_{inv_id}",
            customer_id=f"cust_{cust_id}",
            issued_at=issued_at,
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
        payout_id = f"po_{self._next_hex('payout_mismatch_aug')}"
        net_amount = gross - fees
        occurred_at = datetime(2026, 8, 6, 10, 0, 0)
        settled_at = occurred_at + timedelta(hours=2)

        payout = Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext_payout_{payout_id[3:]}",
            status="completed",
            created_at=occurred_at,
            settled_at=settled_at,
            gross=gross,
            fees=fees,
            net=net_amount,
            currency="USD",
            bank_line_id=None,
        )

        # Create events that sum to slightly more than net ($950.01 vs $950.00)
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
        """Plant FX_VARIANCE exception (settlement rate differs from booked rate, impact > $250)."""
        gross = Decimal("4000.00")
        fees = Decimal("200.00")
        payout_id = f"po_{self._next_hex('payout_fx_aug')}"
        net_amount = gross - fees  # 3800.00
        occurred_at = datetime(2026, 8, 11, 10, 0, 0)
        settled_at = occurred_at + timedelta(hours=2)
        booked_fx = Decimal("1.00")
        settled_fx = Decimal("1.08")  # rate variance

        payout = Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext_payout_{payout_id[3:]}",
            status="completed",
            created_at=occurred_at,
            settled_at=settled_at,
            gross=gross,
            fees=fees,
            net=net_amount,
            currency="USD",
            bank_line_id=None,
        )

        # Settlement event in payout currency equals net_amount to isolate FX variance
        events = [
            self.generate_settlement_event(
                run_id,
                payout_id,
                "payment",
                net_amount,
                occurred_at,
                fx_rate=settled_fx,
                amount_payout=net_amount,
                raw={
                    "booked_fx_rate": str(booked_fx),
                    "settled_fx_rate": str(settled_fx),
                    "variance_amount": "304.00",
                },
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
        payout_id = f"po_{self._next_hex('payout_dispute_sep')}"
        net_amount = gross - fees  # 4800.00
        occurred_at = datetime(2026, 9, 16, 10, 0, 0)
        settled_at = occurred_at + timedelta(hours=2)

        payout = Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext_payout_{payout_id[3:]}",
            status="completed",
            created_at=occurred_at,
            settled_at=settled_at,
            gross=gross,
            fees=fees,
            net=net_amount,
            currency="USD",
            bank_line_id=None,
        )

        # Payment $4,900 - Dispute $100 = $4,800 == net_amount
        events = [
            self.generate_settlement_event(
                run_id, payout_id, "payment", Decimal("4900.00"), occurred_at
            ),
            self.generate_settlement_event(
                run_id,
                payout_id,
                "dispute_opened",
                Decimal("-100.00"),
                occurred_at,
                raw={"dispute_status": "opened", "dispute_id": "dp_planted_001"},
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
        """Plant FEE_ANOMALY (effective fee rate 6% outside expected band 2-4%)."""
        gross = Decimal("10000.00")
        fees = Decimal("600.00")  # 6% -- unusually high
        payout_id = f"po_{self._next_hex('payout_fee_sep')}"
        net_amount = gross - fees  # 9400.00
        occurred_at = datetime(2026, 9, 21, 10, 0, 0)
        settled_at = occurred_at + timedelta(hours=2)

        payout = Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext_payout_{payout_id[3:]}",
            status="completed",
            created_at=occurred_at,
            settled_at=settled_at,
            gross=gross,
            fees=fees,
            net=net_amount,
            currency="USD",
            bank_line_id=None,
        )

        # Gross payment $10,000 - $300 processing - $300 platform = $9,400 == net_amount
        events = [
            self.generate_settlement_event(
                run_id, payout_id, "payment", Decimal("10000.00"), occurred_at
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
        payout_id = f"po_{self._next_hex('payout_timing_sep')}"
        net_amount = gross - fees  # 2900.00
        occurred_at = datetime(2026, 9, 28, 10, 0, 0)
        settled_at = datetime(2026, 10, 1, 14, 0, 0)

        payout = Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext_payout_{payout_id[3:]}",
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

        bank_line = self.generate_bank_line(
            run_id, net_amount, datetime(2026, 10, 1, 15, 0, 0)
        )

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
        payout_id = f"po_{self._next_hex('payout_lowconf_sep')}"
        net_amount = gross - fees  # 760.00
        occurred_at = datetime(2026, 9, 26, 10, 0, 0)
        settled_at = occurred_at + timedelta(hours=2)

        payout = Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext_payout_{payout_id[3:]}",
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
                Decimal("760.00"),
                occurred_at,
                raw={"confidence": 0.72, "gl_account": "4010", "suggested_account": "4010"},
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
        payout_id = f"po_{self._next_hex('payout_bank_unmatched_aug')}"
        net_amount = gross - fees  # 1425.00
        occurred_at = datetime(2026, 8, 13, 10, 0, 0)
        settled_at = occurred_at + timedelta(hours=2)

        payout = Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext_payout_{payout_id[3:]}",
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
        payout_id = f"po_{self._next_hex('payout_clean_aug')}"
        net_amount = gross - fees  # 4750.00
        occurred_at = datetime(2026, 8, 2, 10, 0, 0)
        settled_at = occurred_at + timedelta(hours=2)

        payout = Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext_payout_{payout_id[3:]}",
            status="completed",
            created_at=occurred_at,
            settled_at=settled_at,
            gross=gross,
            fees=fees,
            net=net_amount,
            currency="USD",
            bank_line_id=None,
        )

        event = self.generate_settlement_event(
            run_id, payout_id, "payment", Decimal("4750.00"), occurred_at
        )

        bank_line = self.generate_bank_line(run_id, net_amount, settled_at)

        invoice = self.generate_invoice(
            run_id=run_id,
            subtotal=Decimal("4750.00"),
            tax_rate=Decimal("0.00"),
            issued_at=occurred_at,
        )

        # Balanced journal entries for clean data
        je_payment_id = f"je_{self._next_hex('je_clean_pay_aug')}"
        je_payment = JournalEntry(
            id=je_payment_id,
            run_id=run_id,
            period="2026-08",
            memo="Clean payment entry",
            posted_at=occurred_at,
            status="posted",
            created_by="system",
        )
        jl_payment_dr = JournalLine(
            id=f"jl_{self._next_hex('jl_clean_pay_dr_aug')}",
            entry_id=je_payment_id,
            account_code="1310",
            debit=Decimal("4750.00"),
            credit=Decimal("0.00"),
            currency="USD",
            settlement_event_id=event.id,
        )
        jl_payment_cr = JournalLine(
            id=f"jl_{self._next_hex('jl_clean_pay_cr_aug')}",
            entry_id=je_payment_id,
            account_code="4010",
            debit=Decimal("0.00"),
            credit=Decimal("4750.00"),
            currency="USD",
            settlement_event_id=None,
        )

        je_payout_id = f"je_{self._next_hex('je_clean_po_aug')}"
        je_payout = JournalEntry(
            id=je_payout_id,
            run_id=run_id,
            period="2026-08",
            memo="Clean payout entry",
            posted_at=settled_at,
            status="posted",
            created_by="system",
        )
        jl_payout_dr = JournalLine(
            id=f"jl_{self._next_hex('jl_clean_po_dr_aug')}",
            entry_id=je_payout_id,
            account_code="1330",
            debit=Decimal("4750.00"),
            credit=Decimal("0.00"),
            currency="USD",
            settlement_event_id=None,
        )
        jl_payout_cr = JournalLine(
            id=f"jl_{self._next_hex('jl_clean_po_cr_aug')}",
            entry_id=je_payout_id,
            account_code="1310",
            debit=Decimal("0.00"),
            credit=Decimal("4750.00"),
            currency="USD",
            settlement_event_id=None,
        )

        je_bank_id = f"je_{self._next_hex('je_clean_bank_aug')}"
        je_bank = JournalEntry(
            id=je_bank_id,
            run_id=run_id,
            period="2026-08",
            memo="Clean bank deposit entry",
            posted_at=settled_at,
            status="posted",
            created_by="system",
        )
        jl_bank_dr = JournalLine(
            id=f"jl_{self._next_hex('jl_clean_bank_dr_aug')}",
            entry_id=je_bank_id,
            account_code="1010",
            debit=Decimal("4750.00"),
            credit=Decimal("0.00"),
            currency="USD",
            settlement_event_id=None,
        )
        jl_bank_cr = JournalLine(
            id=f"jl_{self._next_hex('jl_clean_bank_cr_aug')}",
            entry_id=je_bank_id,
            account_code="1330",
            debit=Decimal("0.00"),
            credit=Decimal("4750.00"),
            currency="USD",
            settlement_event_id=None,
        )

        return [
            payout,
            event,
            bank_line,
            invoice,
            je_payment,
            jl_payment_dr,
            jl_payment_cr,
            je_payout,
            jl_payout_dr,
            jl_payout_cr,
            je_bank,
            jl_bank_dr,
            jl_bank_cr,
        ]

    def generate_clean_data_september(self, run_id: str) -> list[Any]:
        """Generate clean (no exceptions) data for September baseline."""
        gross = Decimal("8000.00")
        fees = Decimal("400.00")
        payout_id = f"po_{self._next_hex('payout_clean_sep')}"
        net_amount = gross - fees  # 7600.00
        occurred_at = datetime(2026, 9, 2, 10, 0, 0)
        settled_at = occurred_at + timedelta(hours=2)

        payout = Payout(
            id=payout_id,
            run_id=run_id,
            external_id=f"ext_payout_{payout_id[3:]}",
            status="completed",
            created_at=occurred_at,
            settled_at=settled_at,
            gross=gross,
            fees=fees,
            net=net_amount,
            currency="USD",
            bank_line_id=None,
        )

        event = self.generate_settlement_event(
            run_id, payout_id, "payment", Decimal("7600.00"), occurred_at
        )

        bank_line = self.generate_bank_line(run_id, net_amount, settled_at)

        invoice = self.generate_invoice(
            run_id=run_id,
            subtotal=Decimal("7600.00"),
            tax_rate=Decimal("0.00"),
            issued_at=occurred_at,
        )

        je_payment_id = f"je_{self._next_hex('je_clean_pay_sep')}"
        je_payment = JournalEntry(
            id=je_payment_id,
            run_id=run_id,
            period="2026-09",
            memo="Clean payment entry",
            posted_at=occurred_at,
            status="posted",
            created_by="system",
        )
        jl_payment_dr = JournalLine(
            id=f"jl_{self._next_hex('jl_clean_pay_dr_sep')}",
            entry_id=je_payment_id,
            account_code="1310",
            debit=Decimal("7600.00"),
            credit=Decimal("0.00"),
            currency="USD",
            settlement_event_id=event.id,
        )
        jl_payment_cr = JournalLine(
            id=f"jl_{self._next_hex('jl_clean_pay_cr_sep')}",
            entry_id=je_payment_id,
            account_code="4010",
            debit=Decimal("0.00"),
            credit=Decimal("7600.00"),
            currency="USD",
            settlement_event_id=None,
        )

        je_payout_id = f"je_{self._next_hex('je_clean_po_sep')}"
        je_payout = JournalEntry(
            id=je_payout_id,
            run_id=run_id,
            period="2026-09",
            memo="Clean payout entry",
            posted_at=settled_at,
            status="posted",
            created_by="system",
        )
        jl_payout_dr = JournalLine(
            id=f"jl_{self._next_hex('jl_clean_po_dr_sep')}",
            entry_id=je_payout_id,
            account_code="1330",
            debit=Decimal("7600.00"),
            credit=Decimal("0.00"),
            currency="USD",
            settlement_event_id=None,
        )
        jl_payout_cr = JournalLine(
            id=f"jl_{self._next_hex('jl_clean_po_cr_sep')}",
            entry_id=je_payout_id,
            account_code="1310",
            debit=Decimal("0.00"),
            credit=Decimal("7600.00"),
            currency="USD",
            settlement_event_id=None,
        )

        je_bank_id = f"je_{self._next_hex('je_clean_bank_sep')}"
        je_bank = JournalEntry(
            id=je_bank_id,
            run_id=run_id,
            period="2026-09",
            memo="Clean bank deposit entry",
            posted_at=settled_at,
            status="posted",
            created_by="system",
        )
        jl_bank_dr = JournalLine(
            id=f"jl_{self._next_hex('jl_clean_bank_dr_sep')}",
            entry_id=je_bank_id,
            account_code="1010",
            debit=Decimal("7600.00"),
            credit=Decimal("0.00"),
            currency="USD",
            settlement_event_id=None,
        )
        jl_bank_cr = JournalLine(
            id=f"jl_{self._next_hex('jl_clean_bank_cr_sep')}",
            entry_id=je_bank_id,
            account_code="1330",
            debit=Decimal("0.00"),
            credit=Decimal("7600.00"),
            currency="USD",
            settlement_event_id=None,
        )

        return [
            payout,
            event,
            bank_line,
            invoice,
            je_payment,
            jl_payment_dr,
            jl_payment_cr,
            je_payout,
            jl_payout_dr,
            jl_payout_cr,
            je_bank,
            jl_bank_dr,
            jl_bank_cr,
        ]

    def generate_test_data(
        self,
    ) -> tuple[dict[str, list[tuple[str, Any]]], list[PlantedException]]:
        """
        Generate full test dataset with planted exceptions for August and September.
        Returns (data_by_period, planted_exceptions_manifest).
        Every record in data_by_period[period] is a (record_type, obj) tuple.
        """
        data: dict[str, list[tuple[str, Any]]] = {"2026-08": [], "2026-09": []}

        # Seed chart of accounts
        coa = self.get_chart_of_accounts()
        for acc in coa:
            data["2026-08"].append(("gl_account", acc))

        # August: clean baseline + exceptions
        august_run_id = f"run_{self._next_hex('august_run')}"
        august_run = CloseRun(
            id=august_run_id,
            period="2026-08",
            status="ingest",
            seed=self.seed,
        )
        data["2026-08"].append(("run", august_run))

        for r in self.generate_clean_data_august(august_run_id):
            data["2026-08"].append((record_type_for(r), r))

        # Plant exceptions for August
        payout_data, _ = self.plant_amount_mismatch_august(august_run_id)
        for r in payout_data:
            data["2026-08"].append((record_type_for(r), r))

        payout_data, _ = self.plant_fx_variance_august(august_run_id)
        for r in payout_data:
            data["2026-08"].append((record_type_for(r), r))

        payout_data, _ = self.plant_bank_unmatched_august(august_run_id)
        for r in payout_data:
            data["2026-08"].append((record_type_for(r), r))

        # September: clean baseline + exceptions
        september_run_id = f"run_{self._next_hex('september_run')}"
        september_run = CloseRun(
            id=september_run_id,
            period="2026-09",
            status="ingest",
            seed=self.seed,
        )
        data["2026-09"].append(("run", september_run))

        for r in self.generate_clean_data_september(september_run_id):
            data["2026-09"].append((record_type_for(r), r))

        # Plant exceptions for September
        payout_data, _ = self.plant_dispute_incomplete_september(september_run_id)
        for r in payout_data:
            data["2026-09"].append((record_type_for(r), r))

        payout_data, _ = self.plant_fee_anomaly_september(september_run_id)
        for r in payout_data:
            data["2026-09"].append((record_type_for(r), r))

        payout_data, _ = self.plant_timing_cutoff_september(september_run_id)
        for r in payout_data:
            data["2026-09"].append((record_type_for(r), r))

        payout_data, _ = self.plant_low_confidence_classification_september(september_run_id)
        for r in payout_data:
            data["2026-09"].append((record_type_for(r), r))

        return data, self.planted_exceptions
