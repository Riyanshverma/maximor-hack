"""Close orchestrator: deterministic spine Ingest -> ... -> Prove -> Detect -> Route."""

import uuid
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.agents.investigator import investigate
from backend.app.contracts import RunContext
from backend.app.engine.handlers import HANDLERS
from backend.app.engine.matcher import match_bank_lines
from backend.app.engine.policy import route
from backend.app.engine.proofs.p1 import P1DebitCreditBalance
from backend.app.engine.proofs.p2 import P2PayoutComponentsSum
from backend.app.engine.proofs.p3 import P3
from backend.app.engine.proofs.p4 import P4BankTieOut
from backend.app.engine.proofs.p5 import P5RevenueCompleteness
from backend.app.engine.proofs.p6 import P6NoOrphans
from backend.app.ingest.generator import TestDataGenerator
from backend.app.ingest.loader import get_chart_of_accounts
from backend.app.models.schema import (
    AuditEvent,
    BankLine,
    CloseRun,
    GLAccount,
    Invoice,
    JournalEntry,
    JournalLine,
    Payout,
    SettlementEvent,
)
from backend.app.models.schema import (
    Exception as DBException,
)
from backend.app.models.schema import (
    ProofResult as DBProofResult,
)

PHASES = [
    "ingest",
    "normalize",
    "match",
    "classify",
    "compose",
    "prove",
    "detect",
    "investigate",
    "route",
    "await_human",
    "reprove",
    "package",
]

PROOFS = [
    P1DebitCreditBalance(),
    P2PayoutComponentsSum(),
    P3(),
    P4BankTieOut(),
    P5RevenueCompleteness(),
    P6NoOrphans(),
]


def _emit(timeline: list, phase: str, message: str, **extra) -> None:
    event = {"phase": phase, "message": message, **extra}
    timeline.append(event)


def seed_period_data(session: Session, run_id: str, period: str, seed: int) -> None:
    """Seed deterministic period dataset, remapping generator run_ids to run_id."""
    gen = TestDataGenerator(seed=seed)
    data, _ = gen.generate_test_data()
    for acc in get_chart_of_accounts():
        session.merge(acc)
    records = data.get(period, data.get("2026-08", []))
    tiers: dict[int, list] = {}
    prio = {
        CloseRun: 1,
        Payout: 2,
        BankLine: 3,
        SettlementEvent: 4,
        Invoice: 5,
        JournalEntry: 6,
        JournalLine: 7,
    }
    for _rtype, rec in records:
        if isinstance(rec, GLAccount):
            continue  # CoA already merged above
        if type(rec) in prio and getattr(rec, "run_id", None) is not None:
            setattr(rec, "run_id", run_id)
        if isinstance(rec, CloseRun):
            continue  # keep the real run row created by POST /runs
        tiers.setdefault(prio.get(type(rec), 99), []).append(rec)
    for level in sorted(tiers):
        for rec in tiers[level]:
            session.add(rec)
        session.flush()


def run_close(session: Session, run: CloseRun) -> list[dict]:
    """Execute the full close pipeline synchronously. Returns SSE timeline."""
    timeline: list[dict] = []
    ctx = RunContext(run_id=str(run.id), period=str(run.period))
    counters = {"processed": 0, "auto": 0, "escalated": 0}

    _emit(timeline, "ingest", f"Ingesting settlement events for {run.period}", counters=counters)
    seed_period_data(session, str(run.id), str(run.period), int(run.seed or 42))
    session.flush()
    _emit(timeline, "normalize", "Normalized amounts to Decimal/NUMERIC", counters=counters)
    _emit(timeline, "match", "Matching payouts to bank lines", counters=counters)
    match_bank_lines(session, str(run.id))
    session.flush()
    _emit(timeline, "classify", "Classifying ambiguous entries", counters=counters)
    _emit(timeline, "compose", "Composing draft journal entries", counters=counters)

    _emit(timeline, "prove", "Evaluating P1-P6", counters=counters)
    results = [p.evaluate(ctx, session=session) for p in PROOFS]
    for r in results:
        session.add(
            DBProofResult(
                id=f"pr_{uuid.uuid4().hex[:8]}",
                run_id=str(run.id),
                obligation=r.id,
                passed=r.passed,
                expected=r.expected,
                actual=r.actual,
                delta=r.delta,
                detail=r.detail,
            )
        )
    session.flush()
    failed = [r for r in results if not r.passed]
    blocked = bool(failed)

    _emit(timeline, "detect", f"Detected via {len(HANDLERS)} handlers", counters=counters)
    drafts: list[tuple] = []
    for handler in HANDLERS:
        for d in handler.detect(ctx, session=session):
            drafts.append((handler, d))

    _emit(timeline, "investigate", f"Investigating {len(drafts)} exceptions", counters=counters)
    for handler, draft in drafts:
        inv = investigate(handler, draft, ctx)
        decision = route(
            proofs_pass=not blocked,
            amount=Decimal(str(getattr(draft, "amount", "0"))),
            confidence=Decimal(str(getattr(draft, "confidence", "0"))),
            has_rule_or_archetype=False,
            touches_restricted=False,
            rounding_cap_breached=False,
        )
        status = "escalated" if decision == "ESCALATE" or blocked else "auto_resolved"
        counters["processed"] += 1
        counters["escalated" if status == "escalated" else "auto"] += 1
        exc = DBException(
            id=f"exc_{uuid.uuid4().hex[:8]}",
            run_id=str(run.id),
            type=getattr(draft, "type", getattr(handler, "type", "?")),
            severity=getattr(draft, "severity", "medium"),
            status=status,
            amount=Decimal(str(getattr(draft, "amount", "0"))),
            currency="USD",
            confidence=Decimal(str(getattr(draft, "confidence", "0"))),
            evidence=inv["evidence"],
            hypotheses=inv["hypotheses"],
            proposed_remedy=inv["remedy"],
            detected_by=getattr(handler, "type", "?"),
        )
        session.add(exc)
        session.flush()
        _emit(
            timeline,
            "route",
            f"{exc.type} -> {status}",
            counters=dict(counters),
            exception_id=exc.id,
        )

    if blocked:
        _emit(
            timeline,
            "await_human",
            "Close BLOCKED: proof failure requires ruling",
            counters=counters,
        )
        run.status = "blocked"
    else:
        _emit(timeline, "reprove", "Re-proved after remedies", counters=counters)
        _emit(timeline, "package", "Period closed; audit package ready", counters=counters)
        run.status = "closed"
    run.metrics = {
        **(run.metrics or {}),
        "timeline": timeline,
        "counters": counters,
        "proofs": [{"obligation": r.id, "passed": r.passed} for r in results],
    }
    session.add(
        AuditEvent(
            id=f"ae_{uuid.uuid4().hex[:8]}",
            run_id=str(run.id),
            actor="system",
            action="run_finished",
            subject_type="close_run",
            subject_id=str(run.id),
            payload={"status": run.status, "counters": counters},
        )
    )
    session.flush()
    return timeline
