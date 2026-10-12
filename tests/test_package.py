"""Tests for package metadata and the dependency-free health endpoint."""

from fastapi.testclient import TestClient

from prompt2play import __version__
from prompt2play.api.app import create_app


def test_package_exposes_version() -> None:
    assert __version__ == "0.1.0"


def test_health_endpoint() -> None:
    response = TestClient(create_app()).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
