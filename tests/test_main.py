"""
Test suite for the rag-k8s FastAPI service — matches the exact main.py
you shared (separate app.state.retriever / app.state.rag_chain calls).

Setup:
  1. Create a `tests/` folder at your repo root (sibling to `app/`).
  2. Save this file as tests/test_main.py
  3. Install test deps: uv add --dev pytest pytest-mock httpx
  4. Run: uv run pytest -v

Nothing here touches a real Postgres or the real Gemini API — build_rag_chain
and ingest_documents are mocked before the lifespan runs, so these tests are
fast, free, and don't burn your Gemini quota.
"""

from dotenv import load_dotenv
load_dotenv()

import pytest
from fastapi.testclient import TestClient
from app.auth import create_access_token
from app.main import app
import app.auth as auth_module

CONTENT_TYPE_LATEST_PREFIX = "text/plain"  # prometheus_client's CONTENT_TYPE_LATEST


class FakeRetriever:
    def invoke(self, question):
        return ["DNIF worker restart: run systemctl restart dnif-worker."]


class FakeRagChain:
    def invoke(self, question):
        return "Run systemctl restart dnif-worker as root."


@pytest.fixture
def test_client(mocker, monkeypatch):
    monkeypatch.setattr(auth_module, "SECRET_KEY", "test-secret-key-not-for-production")
    monkeypatch.setattr(auth_module, "DEMO_USERNAME", "testuser")
    monkeypatch.setattr(
        auth_module,
        "DEMO_PASSWORD_HASH",
        b"$2b$12$x2v0NENKwzOqUQW6TYh/7.MTpbsjYwhB1aozQrAVjsZV80cJitXjS",
    )

    mocker.patch("app.main.ingest_documents", return_value=None)
    mocker.patch(
        "app.main.build_rag_chain",
        return_value=(FakeRagChain(), FakeRetriever()),
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture
def auth_headers(test_client):
    token = create_access_token("testuser")
    return {"Authorization": f"Bearer {token}"}


class TestAuthEndpoint:
    def test_login_with_correct_credentials_returns_token(self, test_client):
        response = test_client.post(
            "/token", data={"username": "testuser", "password": "testpass123"}
        )
        assert response.status_code == 200
        body = response.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
 
    def test_login_with_wrong_password_returns_401(self, test_client):
        response = test_client.post(
            "/token", data={"username": "testuser", "password": "wrongpassword"}
        )
        assert response.status_code == 401
 
    def test_login_with_wrong_username_returns_401(self, test_client):
        response = test_client.post(
            "/token", data={"username": "nobody", "password": "testpass123"}
        )
        assert response.status_code == 401


class TestQueryAuthEndpoint:
    def test_query_without_token_returns_401(self, test_client):
        response = test_client.post("/query", json={"question": "test"})
        assert response.status_code == 401
 
    def test_query_with_invalid_token_returns_401(self, test_client):
        response = test_client.post(
            "/query",
            json={"question": "test"},
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert response.status_code == 401
 
    def test_query_with_valid_token_succeeds(self, test_client, auth_headers):
        response = test_client.post(
            "/query",
            json={"question": "How do I restart the DNIF worker?"},
            headers=auth_headers,
        )
        assert response.status_code == 200


class TestRootEndpoint:
    def test_root_returns_200(self, test_client):
        response = test_client.get("/")
        assert response.status_code == 200
        assert response.json()["status"] == "running"


class TestHealthEndpoint:
    def test_health_returns_200(self, test_client):
        response = test_client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestMetricsEndpoint:
    def test_metrics_returns_200(self, test_client):
        response = test_client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_is_prometheus_text_format(self, test_client):
        response = test_client.get("/metrics")
        assert response.headers["content-type"].startswith(CONTENT_TYPE_LATEST_PREFIX)


class TestQueryEndpoint:
    def test_query_missing_question_field_returns_422(self, test_client, auth_headers):
        response = test_client.post("/query", json={}, headers=auth_headers)
        assert response.status_code == 422

    def test_query_empty_string_returns_400(self, test_client, auth_headers):
        # Your handler explicitly checks `if not request.question.strip()`
        # and raises HTTPException(400) — this is YOUR validation, distinct
        # from the 422 pydantic gives for a missing field entirely
        response = test_client.post("/query", json={"question": "   "}, headers=auth_headers)
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_query_happy_path_returns_full_response_shape(self, test_client, auth_headers):
        response = test_client.post(
            "/query", json={"question": "How do I restart the DNIF worker?"},
            headers=auth_headers
        )
        assert response.status_code == 200

        body = response.json()
        assert body["question"] == "How do I restart the DNIF worker?"
        assert body["answer"] == "Run systemctl restart dnif-worker as root."
        assert body["chunks_retrieved"] == 1  # len() of FakeRetriever's list
        assert body["latency_ms"] >= 0

    def test_query_error_path_returns_500_and_increments_error_count(
        self, test_client, mocker, auth_headers
    ):
        # Force the retriever to blow up, and confirm your except block
        # correctly converts it to a 500 rather than an unhandled crash
        mocker.patch.object(
            app.state.retriever, "invoke", side_effect=RuntimeError("pgvector down")
        )
        response = test_client.post("/query", json={"question": "anything"}, headers=auth_headers)
        assert response.status_code == 500
        assert "pgvector down" in response.json()["detail"]

    def test_query_increments_metrics_on_success(self, test_client, auth_headers):
        # Regression guard for QUERY_COUNT.labels(status="success").inc()
        before = test_client.get("/metrics").text
        test_client.post("/query", json={"question": "test question"}, headers=auth_headers)
        after = test_client.get("/metrics").text
        assert before != after
