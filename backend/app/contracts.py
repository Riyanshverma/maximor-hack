"""Frozen contracts for Phase 1: ExceptionHandler and ProofObligation protocols."""
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional, Protocol


@dataclass
class RunContext:
    """Context passed to all handlers and proof evaluators."""
    run_id: str
    period: str


@dataclass
class ExceptionDraft:
    """Exception detected by a handler."""
    type: str
    severity: str
    amount: Decimal
    confidence: Decimal
    evidence: dict[str, Any]


@dataclass
class ProofResult:
    """Result of a proof obligation evaluation."""
    id: str
    passed: bool
    expected: Decimal
    actual: Decimal
    delta: Decimal
    detail: dict[str, Any]


class ExceptionHandler(Protocol):
    """Protocol for exception handlers.

    Each handler detects, gathers evidence for, hypothesizes root causes of,
    and proposes remedies for specific exception types. Handlers are pure
    functions until propose; they never decide autonomy or touch journal entries.
    """
    type: str
    build_priority: int

    def detect(self, ctx: "RunContext") -> list["ExceptionDraft"]:
        """Detect exceptions of this type in the current run."""
        ...

    def gather(self, exc: "ExceptionDraft", ctx: "RunContext") -> dict[str, Any]:
        """Gather evidence about this exception (deterministic only)."""
        ...

    def hypothesize(self, exc: "ExceptionDraft", evidence: dict[str, Any]) -> list[dict[str, Any]]:
        """Form hypotheses about root cause (may use LLM for structure only)."""
        ...

    def propose(self, exc: "ExceptionDraft", hypothesis: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Propose a remedy for this exception (may use LLM, but amounts from tools only)."""
        ...

    def compile_rule(self, exc: "ExceptionDraft", ruling: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Compile a human ruling into a reusable rule."""
        ...


class ProofObligation(Protocol):
    """Protocol for the six proof obligations (P1–P6).

    Pure functions over committed data—no LLM, no network, no mocking.
    Must be runnable standalone against a database snapshot. All six are blocking.
    """
    id: str
    blocking: bool

    def evaluate(self, ctx: RunContext) -> ProofResult:
        """Evaluate this proof obligation against the current run."""
        ...
