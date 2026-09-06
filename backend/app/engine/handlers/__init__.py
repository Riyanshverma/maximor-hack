"""Exception handlers (Phase 4)."""

from backend.app.engine.handlers.amount_mismatch import AmountMismatchHandler
from backend.app.engine.handlers.bank_unmatched import BankUnmatchedHandler
from backend.app.engine.handlers.dispute_lifecycle import DisputeLifecycleHandler
from backend.app.engine.handlers.fx_variance import FXVarianceHandler
from backend.app.engine.handlers.low_confidence_classification import (
    LowConfidenceClassificationHandler,
)
from backend.app.engine.handlers.policy_violation import PolicyViolationHandler
from backend.app.engine.handlers.timing_cutoff import TimingCutoffHandler

HANDLERS = [
    AmountMismatchHandler(),
    FXVarianceHandler(),
    DisputeLifecycleHandler(),
    TimingCutoffHandler(),
    BankUnmatchedHandler(),
    LowConfidenceClassificationHandler(),
    PolicyViolationHandler(),
]

HANDLER_TYPES = [h.type for h in HANDLERS]

__all__ = [
    "HANDLERS",
    "HANDLER_TYPES",
    "AmountMismatchHandler",
    "FXVarianceHandler",
    "DisputeLifecycleHandler",
    "TimingCutoffHandler",
    "BankUnmatchedHandler",
    "LowConfidenceClassificationHandler",
    "PolicyViolationHandler",
]
