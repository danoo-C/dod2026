from fastapi.testclient import TestClient

from dod.main import create_app


def test_health():
    with TestClient(create_app()) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_every_app_is_new():
    assert create_app() is not create_app()
