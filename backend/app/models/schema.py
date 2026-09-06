"""Database schema models for TieOut."""
from datetime import datetime

from sqlalchemy import (
    JSON,
    NUMERIC,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
)

from backend.app.models.base import Base


class CloseRun(Base):
    """A single close run for a period."""
    __tablename__ = "close_run"

    id = Column(String(36), primary_key=True)
    period = Column(String(7), nullable=False, index=True)  # e.g. '2026-08'
    status = Column(String(20), nullable=False)  # pending, ingest, normalize, match, compose, prove, detect, investigate, route, reprove, package, closed
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime, nullable=True)
    rules_enabled = Column(Boolean, default=True)
    seed = Column(Integer, default=42)
    metrics = Column(JSON, default={})


class SettlementEvent(Base):
    """Settlement event from Dodo breakup-details."""
    __tablename__ = "settlement_event"

    id = Column(String(36), primary_key=True)
    run_id = Column(String(36), ForeignKey("close_run.id"), nullable=False, index=True)
    source = Column(String(20), nullable=False)  # 'dodo' or 'seed'
    external_id = Column(String(255), nullable=True)
    event_type = Column(String(50), nullable=False)  # payment, refund, fee, dispute, tax, reserve, fx_adjustment, payout
    payout_id = Column(String(36), nullable=True, index=True)
    order_id = Column(String(255), nullable=True)
    customer_id = Column(String(255), nullable=True)
    occurred_at = Column(DateTime, nullable=False)
    amount_native = Column(NUMERIC(18, 4), nullable=False)
    currency_native = Column(String(3), nullable=False)
    amount_payout = Column(NUMERIC(18, 4), nullable=False)
    currency_payout = Column(String(3), nullable=False)
    fx_rate = Column(NUMERIC(18, 8), nullable=True)
    fx_source = Column(String(50), nullable=True)
    raw = Column(JSON, nullable=True)


class Payout(Base):
    """Payout from Dodo."""
    __tablename__ = "payout"

    id = Column(String(36), primary_key=True)
    run_id = Column(String(36), ForeignKey("close_run.id"), nullable=False, index=True)
    external_id = Column(String(255), nullable=False, unique=True)
    status = Column(String(20), nullable=False)  # pending, completed, failed
    created_at = Column(DateTime, nullable=False)
    settled_at = Column(DateTime, nullable=True)
    gross = Column(NUMERIC(18, 4), nullable=False)
    fees = Column(NUMERIC(18, 4), nullable=False)
    net = Column(NUMERIC(18, 4), nullable=False)
    currency = Column(String(3), nullable=False)
    bank_line_id = Column(String(36), ForeignKey("bank_line.id"), nullable=True)


class BankLine(Base):
    """Bank deposit line."""
    __tablename__ = "bank_line"

    id = Column(String(36), primary_key=True)
    run_id = Column(String(36), ForeignKey("close_run.id"), nullable=False, index=True)
    posted_at = Column(DateTime, nullable=False)
    amount = Column(NUMERIC(18, 4), nullable=False)
    currency = Column(String(3), nullable=False)
    description = Column(String(500), nullable=True)
    matched_payout_id = Column(String(36), ForeignKey("payout.id"), nullable=True)


class Invoice(Base):
    """Customer invoice."""
    __tablename__ = "invoice"

    id = Column(String(36), primary_key=True)
    run_id = Column(String(36), ForeignKey("close_run.id"), nullable=False, index=True)
    external_id = Column(String(255), nullable=False)
    customer_id = Column(String(255), nullable=False)
    issued_at = Column(DateTime, nullable=False)
    subtotal = Column(NUMERIC(18, 4), nullable=False)
    tax = Column(NUMERIC(18, 4), nullable=False)
    total = Column(NUMERIC(18, 4), nullable=False)
    currency = Column(String(3), nullable=False)
    line_items = Column(JSON, nullable=True)


class GLAccount(Base):
    """General ledger account."""
    __tablename__ = "gl_account"

    code = Column(String(10), primary_key=True)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)  # asset, liability, equity, revenue, expense
    normal_side = Column(String(6), nullable=False)  # debit or credit
    is_restricted = Column(Boolean, default=False)


class JournalEntry(Base):
    """Posted journal entry."""
    __tablename__ = "journal_entry"

    id = Column(String(36), primary_key=True)
    run_id = Column(String(36), ForeignKey("close_run.id"), nullable=False, index=True)
    period = Column(String(7), nullable=False)
    memo = Column(String(500), nullable=True)
    posted_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="draft")  # draft, posted, reversed
    source_exception_id = Column(String(36), ForeignKey("exception.id"), nullable=True)
    created_by = Column(String(20), nullable=False)  # agent, human, rule
    rule_id = Column(String(36), ForeignKey("rule.id"), nullable=True)


class JournalLine(Base):
    """Line in a journal entry."""
    __tablename__ = "journal_line"
    __table_args__ = (
        CheckConstraint("(debit > 0 AND credit = 0) OR (debit = 0 AND credit > 0)"),
    )

    id = Column(String(36), primary_key=True)
    entry_id = Column(String(36), ForeignKey("journal_entry.id"), nullable=False, index=True)
    account_code = Column(String(10), ForeignKey("gl_account.code"), nullable=False)
    debit = Column(NUMERIC(18, 4), nullable=False, default=0)
    credit = Column(NUMERIC(18, 4), nullable=False, default=0)
    currency = Column(String(3), nullable=False)
    settlement_event_id = Column(String(36), ForeignKey("settlement_event.id"), nullable=True)


class Exception(Base):
    """Detected exception in the close process."""
    __tablename__ = "exception"

    id = Column(String(36), primary_key=True)
    run_id = Column(String(36), ForeignKey("close_run.id"), nullable=False, index=True)
    type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False)  # low, medium, high, critical
    status = Column(String(30), default="open")  # open, auto_resolved, escalated, human_resolved
    amount = Column(NUMERIC(18, 4), nullable=False)
    currency = Column(String(3), nullable=False)
    confidence = Column(NUMERIC(4, 3), nullable=False)
    evidence = Column(JSON, nullable=True)
    hypotheses = Column(JSON, nullable=True)
    proposed_remedy = Column(JSON, nullable=True)
    detected_by = Column(String(50), nullable=False)  # handler type
    matched_rule_id = Column(String(36), ForeignKey("rule.id"), nullable=True)
    ground_truth_key = Column(String(255), nullable=True)  # for metrics only, write-once


class HumanRuling(Base):
    """Human decision on an exception."""
    __tablename__ = "human_ruling"

    id = Column(String(36), primary_key=True)
    exception_id = Column(String(36), ForeignKey("exception.id"), nullable=False, index=True)
    decision = Column(String(20), nullable=False)  # approved, rejected, needs_investigation
    rationale = Column(String(2000), nullable=False)
    decided_by = Column(String(255), nullable=False)
    decided_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class Rule(Base):
    """Learned rule from a human ruling."""
    __tablename__ = "rule"

    id = Column(String(36), primary_key=True)
    name = Column(String(255), nullable=False)
    version = Column(Integer, default=1)
    predicate = Column(JSON, nullable=False)
    action = Column(JSON, nullable=False)
    rationale = Column(String(2000), nullable=True)
    source_ruling_id = Column(String(36), ForeignKey("human_ruling.id"), nullable=True)
    active = Column(Boolean, default=True)
    times_applied = Column(Integer, default=0)


class ProofResult(Base):
    """Result of a proof obligation evaluation."""
    __tablename__ = "proof_result"

    id = Column(String(36), primary_key=True)
    run_id = Column(String(36), ForeignKey("close_run.id"), nullable=False, index=True)
    obligation = Column(String(3), nullable=False)  # P1, P2, P3, P4, P5, P6
    passed = Column(Boolean, nullable=False)
    expected = Column(NUMERIC(18, 4), nullable=False)
    actual = Column(NUMERIC(18, 4), nullable=False)
    delta = Column(NUMERIC(18, 4), nullable=False)
    detail = Column(JSON, nullable=True)
    evaluated_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class AuditEvent(Base):
    """Append-only audit trail."""
    __tablename__ = "audit_event"

    id = Column(String(36), primary_key=True)
    run_id = Column(String(36), ForeignKey("close_run.id"), nullable=False, index=True)
    actor = Column(String(20), nullable=False)  # agent, human, rule, system
    action = Column(String(100), nullable=False)
    subject_type = Column(String(50), nullable=False)
    subject_id = Column(String(36), nullable=False)
    payload = Column(JSON, nullable=True)
    at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
