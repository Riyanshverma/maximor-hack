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
