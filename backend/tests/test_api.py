"""Test API endpoints are defined and respond properly."""
from fastapi.testclient import TestClient


def test_app_creates():
    """RED: FastAPI app should be creatable from main module."""
    from backend.app.main import app
    assert app is not None


def test_app_has_openapi_docs():
    """RED: FastAPI app should have docs endpoint."""
    from backend.app.main import app
    client = TestClient(app)
    response = client.get("/docs")
    assert response.status_code == 200


def test_post_runs_endpoint_defined():
    """RED: POST /runs endpoint should be defined."""
    from backend.app.main import app
    # Check that the route exists
    routes = [route.path for route in app.routes]
    assert "/runs" in routes


def test_get_runs_id_endpoint_defined():
    """RED: GET /runs/{id} endpoint should be defined."""
    from backend.app.main import app
    routes = [route.path for route in app.routes]
    assert "/runs/{id}" in routes or "/runs/{run_id}" in routes


def test_get_runs_stream_endpoint_defined():
    """RED: GET /runs/{id}/stream endpoint should be defined (SSE)."""
    from backend.app.main import app
    routes = [route.path for route in app.routes]
    # SSE stream endpoint
    assert any("stream" in route for route in routes)


def test_get_runs_proofs_endpoint_defined():
    """RED: GET /runs/{id}/proofs endpoint should be defined."""
    from backend.app.main import app
    routes = [route.path for route in app.routes]
    assert any("proofs" in route for route in routes)


def test_get_runs_exceptions_endpoint_defined():
    """RED: GET /runs/{id}/exceptions endpoint should be defined."""
    from backend.app.main import app
    routes = [route.path for route in app.routes]
    assert any("exceptions" in route for route in routes)


def test_post_exceptions_resolve_endpoint_defined():
    """RED: POST /exceptions/{id}/resolve endpoint should be defined."""
    from backend.app.main import app
    routes = [route.path for route in app.routes]
    assert any("resolve" in route for route in routes)


def test_get_rules_endpoint_defined():
    """RED: GET /rules endpoint should be defined."""
    from backend.app.main import app
    routes = [route.path for route in app.routes]
    assert "/rules" in routes


def test_get_audit_package_endpoint_defined():
    """RED: GET /runs/{id}/audit-package endpoint should be defined."""
    from backend.app.main import app
    routes = [route.path for route in app.routes]
    assert any("audit-package" in route or "audit_package" in route for route in routes)


def test_post_runs_valid_json_creates_run(tmp_path, monkeypatch):
    """POST /runs with valid JSON payload creates run and returns 200."""
    from sqlalchemy import create_engine

    from backend.app.main import app
    from backend.app.models.base import Base

    db_url = f"sqlite:///{tmp_path}/api_test.db"
    monkeypatch.setenv("DATABASE_URL", db_url)
    engine = create_engine(db_url)
    import backend.app.models.schema  # noqa: F401  (register tables on Base)

    Base.metadata.create_all(engine)

    client = TestClient(app)
    response = client.post(
        "/runs",
        json={"period": "2026-08", "rules_enabled": True, "seed": 42},
    )
    assert response.status_code == 200
    data = response.json()
    assert "run_id" in data
    assert data["period"] == "2026-08"
    # Phase 5: POST /runs executes the close pipeline synchronously,
    # so the run lands terminal (blocked on proof failure, or closed).
    assert data["status"] in ("blocked", "closed")


def test_post_runs_invalid_period_returns_422():
    """POST /runs with invalid period format returns 422."""
    from backend.app.main import app
    client = TestClient(app)

    # Missing field
    resp1 = client.post("/runs", json={"seed": 42})
    assert resp1.status_code == 422

    # Malformed period
    resp2 = client.post("/runs", json={"period": "2026/08"})
    assert resp2.status_code == 422

    # Invalid month 13
    resp3 = client.post("/runs", json={"period": "2026-13"})
    assert resp3.status_code == 422


def test_get_runs_404_for_unknown_run(tmp_path, monkeypatch):
    """GET /runs/{run_id} returns 404 when run does not exist."""
    from sqlalchemy import create_engine

    from backend.app.main import app
    from backend.app.models.base import Base

    db_url = f"sqlite:///{tmp_path}/api_404_test.db"
    monkeypatch.setenv("DATABASE_URL", db_url)
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    client = TestClient(app)
    response = client.get("/runs/non_existent_run_999")
    assert response.status_code == 404


def test_get_proofs_404_for_unknown_run(tmp_path, monkeypatch):
    """GET /runs/{run_id}/proofs returns 404 when run does not exist."""
    from sqlalchemy import create_engine

    from backend.app.main import app
    from backend.app.models.base import Base

    db_url = f"sqlite:///{tmp_path}/api_proof_404.db"
    monkeypatch.setenv("DATABASE_URL", db_url)
    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    client = TestClient(app)
    response = client.get("/runs/non_existent_run_999/proofs")
    assert response.status_code == 404


def test_resolve_exception_empty_rationale_returns_422():
    """POST /exceptions/{id}/resolve with empty or whitespace-only rationale returns 422."""
    from backend.app.main import app
    client = TestClient(app)

    # Empty string
    resp1 = client.post(
        "/exceptions/exc_123/resolve",
        json={"decision": "approved", "rationale": ""},
    )
    assert resp1.status_code == 422

    # Whitespace only
    resp2 = client.post(
        "/exceptions/exc_123/resolve",
        json={"decision": "approved", "rationale": "   "},
    )
    assert resp2.status_code == 422


def test_resolve_exception_valid_payload():
    """POST /exceptions/{id}/resolve with valid payload returns 200."""
    from backend.app.main import app
    client = TestClient(app)

    resp = client.post(
        "/exceptions/exc_123/resolve",
        json={"decision": "approved", "rationale": "Legitimate timing difference"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["exception_id"] == "exc_123"
    assert data["status"] == "human_resolved"

