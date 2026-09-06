"""Policy engine: deterministic AUTO vs ESCALATE routing (spec 03)."""

from decimal import Decimal


def route(
    *,
    proofs_pass: bool,
    amount: Decimal,
    confidence: Decimal,
    has_rule_or_archetype: bool,
    touches_restricted: bool,
    rounding_cap_breached: bool,
) -> str:
    """Return AUTO only if ALL six conditions hold, else ESCALATE."""
    if not proofs_pass:
        return "ESCALATE"
    if abs(amount) >= Decimal("250.00"):
        return "ESCALATE"
    if confidence < Decimal("0.85"):
        return "ESCALATE"
    if not has_rule_or_archetype:
        return "ESCALATE"
    if touches_restricted:
        return "ESCALATE"
    if rounding_cap_breached:
        return "ESCALATE"
    return "AUTO"
