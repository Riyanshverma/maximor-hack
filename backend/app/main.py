"""FastAPI application entry point for TieOut close orchestrator."""
from fastapi import FastAPI
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(
    title="TieOut",
    description="Deterministic settlement close agent with proof-carrying engine",
    version="0.1.0",
)


# POST /runs — start a close run
@app.post("/runs")
async def post_runs(period: str, rules_enabled: bool = True, seed: int = 42):
    """Start a close run for a period."""
    return {"run_id": "run_001"}


# GET /runs/{id} — status + metrics
@app.get("/runs/{run_id}")
async def get_run(run_id: str):
    """Get run status and metrics."""
    return {"run_id": run_id, "status": "in_progress", "metrics": {}}


# GET /runs/{id}/stream — SSE: live activity feed
@app.get("/runs/{run_id}/stream")
async def stream_run(run_id: str):
    """Stream live run activity via Server-Sent Events."""
    async def event_generator():
        yield b'event: message\ndata: {"phase": "ingest"}\n\n'
    return StreamingResponse(event_generator(), media_type="text/event-stream")


# GET /runs/{id}/proofs — proof results
@app.get("/runs/{run_id}/proofs")
async def get_proofs(run_id: str):
    """Get proof results for a run (P1–P6)."""
    return [
        {
            "obligation": f"P{i}",
            "passed": True,
            "expected": "0.00",
            "actual": "0.00",
            "delta": "0.00",
        }
        for i in range(1, 7)
    ]


# GET /runs/{id}/exceptions — exception register
@app.get("/runs/{run_id}/exceptions")
async def get_exceptions(run_id: str, status: str | None = None):
    """Get exceptions for a run, optionally filtered by status."""
    return []


# GET /exceptions/{id} — full exception details
@app.get("/exceptions/{exc_id}")
async def get_exception(exc_id: str):
    """Get full details for an exception."""
    return {"exception_id": exc_id}


# POST /exceptions/{id}/resolve — human ruling (rationale required)
@app.post("/exceptions/{exc_id}/resolve")
async def resolve_exception(exc_id: str, decision: str, rationale: str):
    """Resolve an exception with a human ruling."""
    if not rationale or not rationale.strip():
        return JSONResponse(
            status_code=422,
            content={"detail": "Rationale is required and cannot be empty"}
        )
    return {"exception_id": exc_id, "status": "human_resolved"}


# GET /runs/{id}/journal-entries — journal entries
@app.get("/runs/{run_id}/journal-entries")
async def get_journal_entries(run_id: str):
    """Get journal entries for a run."""
    return []


# GET /rules — all learned rules
@app.get("/rules")
async def get_rules(run_id: str = None):
    """Get all learned rules, optionally filtered by run."""
    return []


# GET /runs/{id}/audit-package — close memo + evidence
@app.get("/runs/{run_id}/audit-package")
async def get_audit_package(run_id: str):
    """Get the audit package (close memo and evidence bundle)."""
    return {"run_id": run_id, "memo": "", "evidence": {}}


# GET /runs/{id}/metrics — scorecard
@app.get("/runs/{run_id}/metrics")
async def get_metrics(run_id: str):
    """Get the metrics scorecard for a run."""
    return {"run_id": run_id, "automation_rate": 0.0}
