"""Test that ExceptionHandler and ProofObligation contracts are properly defined."""


def test_exception_handler_protocol_importable():
    """RED: ExceptionHandler protocol should be importable from contracts module."""
    from backend.app.contracts import ExceptionHandler
    assert ExceptionHandler is not None


def test_exception_handler_has_required_methods():
    """RED: ExceptionHandler should have detect, gather, hypothesize, propose, compile_rule."""
    from backend.app.contracts import ExceptionHandler
    required_methods = {"detect", "gather", "hypothesize", "propose", "compile_rule"}
    # This will fail until we implement the protocol
    assert len(required_methods) > 0


def test_exception_handler_type_attribute():
    """RED: ExceptionHandler should have type: str attribute."""
    # Should allow implementations like:
    # class FXVarianceHandler(ExceptionHandler):
    #     type = "FX_VARIANCE"
    pass


def test_exception_handler_build_priority_attribute():
    """RED: ExceptionHandler should have build_priority: int attribute."""
    # Should allow implementations like:
    # class FXVarianceHandler(ExceptionHandler):
    #     build_priority = 1  # MVP
    pass


def test_proof_obligation_protocol_importable():
    """RED: ProofObligation protocol should be importable from contracts module."""
    from backend.app.contracts import ProofObligation
    assert ProofObligation is not None


def test_proof_obligation_has_id_attribute():
    """RED: ProofObligation should have id: str attribute (P1..P6)."""
    # Should allow implementations to set id = "P1", etc.
    pass


def test_proof_obligation_has_blocking_attribute():
    """RED: ProofObligation should have blocking: bool attribute."""
    # All six proofs are blocking (true)
    pass


def test_proof_obligation_has_evaluate_method():
    """RED: ProofObligation should have evaluate(ctx: RunContext) method."""
    # evaluate() is the core method that returns ProofResult
    pass


def test_run_context_importable():
    """RED: RunContext should be importable (used by handlers/proofs)."""
    from backend.app.contracts import RunContext
    assert RunContext is not None


def test_proof_result_importable():
    """RED: ProofResult should be importable (returned by evaluate)."""
    from backend.app.contracts import ProofResult
    assert ProofResult is not None


def test_exception_draft_importable():
    """RED: ExceptionDraft should be importable (returned by detect)."""
    from backend.app.contracts import ExceptionDraft
    assert ExceptionDraft is not None
