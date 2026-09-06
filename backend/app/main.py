"""FastAPI application entry point for TieOut close orchestrator."""
import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.contracts import RunContext
from backend.app.engine.matcher import match_bank_lines
from backend.app.engine.proofs.p1 import P1DebitCreditBalance
from backend.app.engine.proofs.p2 import P2PayoutComponentsSum
from backend.app.engine.proofs.p3 import P3
from backend.app.engine.proofs.p4 import P4BankTieOut
from backend.app.engine.proofs.p5 import P5RevenueCompleteness
from backend.app.engine.proofs.p6 import P6NoOrphans
from backend.app.ingest.loader import get_db_url
from backend.app.models.schema import (
    CloseRun,
    HumanRuling,
    JournalEntry,
    Rule,
)
from backend.app.models.schema import (
    Exception as DBException,
)

app = FastAPI(
    title="TieOut",
    description="Deterministic settlement close agent with proof-carrying engine",
    version="0.1.0",
)


class CreateRunRequest(BaseModel):
    """Request payload to initiate a close run."""
    period: str = Field(..., pattern=r"^\d{4}-(?:0[1-9]|1[0-2])$")
    rules_enabled: bool = True
    seed: int = 42


class ResolveExceptionRequest(BaseModel):
    """Request payload to resolve an exception with a human ruling."""
    decision: str
    rationale: str

    @field_validator("rationale")
    @classmethod
    def validate_rationale(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Rationale is required and cannot be empty")
        return v


# POST /runs — start a close run
@app.post("/runs", status_code=status.HTTP_200_OK)
async def post_runs(payload: CreateRunRequest):
    """Start a close run for a period."""
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    engine = create_engine(get_db_url())
    with Session(engine) as session:
        run = CloseRun(
            id=run_id,
            period=payload.period,
            status="in_progress",
            rules_enabled=payload.rules_enabled,
            seed=payload.seed,
        )
        session.add(run)
        session.commit()
    return {
        "run_id": run_id,
        "period": payload.period,
        "status": "in_progress",
        "rules_enabled": payload.rules_enabled,
        "seed": payload.seed,
    }


# GET /runs/{id} — status + metrics
@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    """Get run status and metrics."""
    engine = create_engine(get_db_url())
    with Session(engine) as session:
        run = session.get(CloseRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        return {
            "run_id": run.id,
            "period": run.period,
            "status": run.status,
            "metrics": run.metrics or {},
        }


# GET /runs/{id}/stream — SSE: live activity feed
@app.get("/runs/{run_id}/stream")
async def stream_run(run_id: str):
    """Stream live run activity via Server-Sent Events."""
    engine = create_engine(get_db_url())
    with Session(engine) as session:
        run = session.get(CloseRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    async def event_generator():
        data_bytes = f'{{"phase": "ingest", "run_id": "{run_id}", "status": "started"}}'.encode()
        yield b'event: message\ndata: ' + data_bytes + b'\n\n'

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# GET /runs/{id}/proofs — proof results
@app.get("/runs/{run_id}/proofs")
async def get_proofs(run_id: str):
    """Get proof results for a run (P1–P6) with strict string money serialization."""
    engine = create_engine(get_db_url())
    with Session(engine) as session:
        run = session.get(CloseRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

        # Run matcher first to ensure bank line links are established
        match_bank_lines(session, run_id)
        session.commit()

        ctx = RunContext(run_id=str(run.id), period=str(run.period))
        results = [
            P1DebitCreditBalance().evaluate(ctx, session=session),
            P2PayoutComponentsSum().evaluate(ctx, session=session),
            P3().evaluate(ctx, session=session),
            P4BankTieOut().evaluate(ctx, session=session),
            P5RevenueCompleteness().evaluate(ctx, session=session),
            P6NoOrphans().evaluate(ctx, session=session),
        ]
        return [
            {
                "obligation": r.id,
                "passed": r.passed,
                "expected": str(r.expected),
                "actual": str(r.actual),
                "delta": str(r.delta),
                "detail": r.detail,
            }
            for r in results
        ]


# GET /runs/{id}/exceptions — exception register
@app.get("/runs/{run_id}/exceptions")
async def get_exceptions(run_id: str, status: Optional[str] = None):
    """Get exceptions for a run, optionally filtered by status."""
    engine = create_engine(get_db_url())
    with Session(engine) as session:
        run = session.get(CloseRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        query = select(DBException).where(DBException.run_id == run_id)
        if status:
            query = query.where(DBException.status == status)
        exceptions = session.scalars(query).all()
        return [
            {
                "id": exc.id,
                "run_id": exc.run_id,
                "type": exc.type,
                "severity": exc.severity,
                "status": exc.status,
                "amount": str(exc.amount),
                "currency": exc.currency,
                "confidence": str(exc.confidence),
                "detected_by": exc.detected_by,
            }
            for exc in exceptions
        ]


# GET /exceptions/{id} — full exception details
@app.get("/exceptions/{exc_id}")
async def get_exception(exc_id: str):
    """Get full details for an exception."""
    engine = create_engine(get_db_url())
    with Session(engine) as session:
        exc = session.get(DBException, exc_id)
        if exc is None:
            raise HTTPException(status_code=404, detail=f"Exception {exc_id} not found")
        return {
            "id": exc.id,
            "run_id": exc.run_id,
            "type": exc.type,
            "severity": exc.severity,
            "status": exc.status,
            "amount": str(exc.amount),
            "currency": exc.currency,
            "confidence": str(exc.confidence),
            "evidence": exc.evidence,
            "hypotheses": exc.hypotheses,
            "proposed_remedy": exc.proposed_remedy,
            "detected_by": exc.detected_by,
        }


# POST /exceptions/{id}/resolve — human ruling (rationale required)
@app.post("/exceptions/{exc_id}/resolve")
async def resolve_exception(exc_id: str, payload: ResolveExceptionRequest):
    """Resolve an exception with a human ruling."""
    engine = create_engine(get_db_url())
    with Session(engine) as session:
        exc = session.get(DBException, exc_id)
        if exc is not None:
            setattr(exc, "status", "human_resolved")
            ruling_id = f"hr_{uuid.uuid4().hex[:8]}"
            ruling = HumanRuling(
                id=ruling_id,
                exception_id=exc.id,
                decision=payload.decision,
                rationale=payload.rationale,
                decided_by="human",
            )
            session.add(ruling)
            session.commit()

    return {
        "exception_id": exc_id,
        "status": "human_resolved",
        "decision": payload.decision,
        "rationale": payload.rationale,
    }


# GET /runs/{id}/journal-entries — journal entries
@app.get("/runs/{run_id}/journal-entries")
async def get_journal_entries(run_id: str):
    """Get journal entries for a run."""
    engine = create_engine(get_db_url())
    with Session(engine) as session:
        run = session.get(CloseRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        entries = session.scalars(
            select(JournalEntry).where(JournalEntry.run_id == run_id)
        ).all()
        result = []
        for je in entries:
            posted = getattr(je, "posted_at", None)
            result.append(
                {
                    "id": je.id,
                    "run_id": je.run_id,
                    "period": je.period,
                    "memo": je.memo,
                    "posted_at": posted.isoformat() if posted is not None else None,
                    "status": je.status,
                    "created_by": je.created_by,
                }
            )
        return result


# GET /rules — all learned rules
@app.get("/rules")
async def get_rules(run_id: Optional[str] = None):
    """Get all learned rules, optionally filtered by run."""
    engine = create_engine(get_db_url())
    with Session(engine) as session:
        rules = session.scalars(select(Rule)).all()
        return [
            {
                "id": r.id,
                "name": r.name,
                "version": r.version,
                "predicate": r.predicate,
                "action": r.action,
                "active": r.active,
            }
            for r in rules
        ]


# GET /runs/{id}/audit-package — close memo + evidence
@app.get("/runs/{run_id}/audit-package")
async def get_audit_package(run_id: str):
    """Get the audit package (close memo and evidence bundle)."""
    engine = create_engine(get_db_url())
    with Session(engine) as session:
        run = session.get(CloseRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        return {
            "run_id": run_id,
            "period": run.period,
            "memo": f"Close package for period {run.period}",
            "evidence": {},
        }


# GET /runs/{id}/metrics — scorecard
@app.get("/runs/{run_id}/metrics")
async def get_metrics(run_id: str):
    """Get the metrics scorecard for a run."""
    engine = create_engine(get_db_url())
    with Session(engine) as session:
        run = session.get(CloseRun, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
        return {
            "run_id": run_id,
            "period": run.period,
            "automation_rate": 0.0,
            "metrics": run.metrics or {},
        }

