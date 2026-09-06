"""Phase 5 tests: policy routing, investigator, orchestrator end-to-end, SSE."""
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from backend.app.agents.investigator import investigate
from backend.app.contracts import RunContext
from backend.app.engine.policy import route
from backend.app.models.base import Base


def test_route_requires_all_six():
    ok = dict(proofs_pass=True, amount=Decimal("10.00"), confidence=Decimal("0.90"),
              has_rule_or_archetype=True, touches_restricted=False, rounding_cap_breached=False)
    assert route(**ok) == "AUTO"
    for key, bad in [
        ("proofs_pass", False),
        ("amount", Decimal("4812.50")),
        ("confidence", Decimal("0.50")),
        ("has_rule_or_archetype", False),
        ("touches_restricted", True),
        ("rounding_cap_breached", True),
    ]:
        args = dict(ok)
        args[key] = bad
        assert route(**args) == "ESCALATE"


def test_investigator_uses_handler_tools():
    from backend.app.engine.handlers.amount_mismatch import AmountMismatchHandler

    h = AmountMismatchHandler()
    draft = type("D", (), {"type": h.type, "amount": Decimal("5.00")})()
    out = investigate(h, draft, RunContext(run_id="r", period="2026-08"))
    assert set(out) == {"evidence", "hypotheses", "remedy"}


def _client(tmp_path, monkeypatch):
    db_url = f"sqlite:///{tmp_path}/phase5.db"
    monkeypatch.setenv("DATABASE_URL", db_url)
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    from backend.app.main import app

    return TestClient(app)


def test_post_runs_august_lands_blocked(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    resp = client.post("/runs", json={"period": "2026-08", "rules_enabled": True, "seed": 42})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "blocked"
    assert "prove" in data["phases"]
    proofs = client.get(f"/runs/{data['run_id']}/proofs").json()
    assert len(proofs) == 6
    assert any(not p["passed"] for p in proofs)
    for p in proofs:  # money serialized as strings, never floats
        assert isinstance(p["expected"], str) and isinstance(p["delta"], str)
    excs = client.get(f"/runs/{data['run_id']}/exceptions").json()
    assert len(excs) > 0


def test_sse_stream_replays_phases(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    run_id = client.post("/runs", json={"period": "2026-08"}).json()["run_id"]
    resp = client.get(f"/runs/{run_id}/stream")
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]
    assert "prove" in resp.text
    assert "await_human" in resp.text or "package" in resp.text
