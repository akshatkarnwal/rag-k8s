"""
Test suite for the rag-k8s FastAPI service.

The RAG chain is a single object whose invoke() returns
{"question", "answer", "docs"} (one retrieval per request).

Setup:
  1. Save this file as tests/test_main.py
  2. Install test deps: uv add --dev pytest pytest-mock httpx
  3. Run: uv run pytest -v

Nothing here touches a real Postgres or the real Gemini API: build_rag_chain,
ingest_documents and the DB engine are mocked, so these tests are fast, free,
and don't burn your Gemini quota.
"""

from dotenv import load_dotenv
load_dotenv()

import re
import pytest
from fastapi.testclient import TestClient
from app.auth import create_access_token
from app.main import app
import app.auth as auth_module

CONTENT_TYPE_LATEST_PREFIX = "text/plain"  # prometheus_client's CONTENT_TYPE_LATEST


class FakeRagChain:
    def invoke(self, question):
        return {
            "question": question,
            "answer": "Run systemctl restart dnif-worker as root.",
            "docs": ["DNIF worker restart: run systemctl restart dnif-worker."],
        }


def metric_value(metrics_text: str, status: str) -> float:
    """Read rag_query_total{status="..."} from the /metrics text (0 if absent)."""
    pattern = rf'^rag_query_total\{{status="{status}"\}}\s+([0-9.eE+-]+)'
    match = re.search(pattern, metrics_text, re.MULTILINE)
    return float(match.group(1)) if match else 0.0


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
    mocker.patch("app.main.build_rag_chain", return_value=FakeRagChain())
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


class TestReadyEndpoint:
    def test_ready_returns_200_when_db_reachable(self, test_client, mocker):
        mocker.patch("app.main.get_engine")  # MagicMock supports `with ... connect()`
        response = test_client.get("/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"

    def test_ready_returns_503_when_db_down(self, test_client, mocker):
        engine = mocker.patch("app.main.get_engine")
        engine.return_value.connect.side_effect = Exception("db down")
        response = test_client.get("/ready")
        assert response.status_code == 503
        assert "db down" not in response.text  # don't leak internals

    def test_ready_returns_503_when_chain_missing(self, test_client, mocker):
        mocker.patch("app.main.get_engine")
        mocker.patch.object(app.state, "rag_chain", None)
        response = test_client.get("/ready")
        assert response.status_code == 503


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
        # and raises HTTPException(400); this is distinct from the 422
        # pydantic gives for a missing field entirely.
        response = test_client.post("/query", json={"question": "   "}, headers=auth_headers)
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_query_happy_path_returns_full_response_shape(self, test_client, auth_headers):
        response = test_client.post(
            "/query", json={"question": "How do I restart the DNIF worker?"},
            headers=auth_headers,
        )
        assert response.status_code == 200

        body = response.json()
        assert body["question"] == "How do I restart the DNIF worker?"
        assert body["answer"] == "Run systemctl restart dnif-worker as root."
        assert body["chunks_retrieved"] == 1  # len() of the fake docs list
        assert body["latency_ms"] >= 0

    def test_query_retrieves_only_once(self, test_client, auth_headers, mocker):
        # Regression guard for the double-retrieval bug: one chain call per request.
        spy = mocker.spy(app.state.rag_chain, "invoke")
        response = test_client.post("/query", json={"question": "anything"}, headers=auth_headers)
        assert response.status_code == 200
        assert spy.call_count == 1

    def test_query_error_path_returns_500_and_increments_error_count(
        self, test_client, mocker, auth_headers
    ):
        mocker.patch.object(
            app.state.rag_chain, "invoke", side_effect=RuntimeError("pgvector down")
        )
        before = metric_value(test_client.get("/metrics").text, "error")
        response = test_client.post("/query", json={"question": "anything"}, headers=auth_headers)
        after = metric_value(test_client.get("/metrics").text, "error")

        assert response.status_code == 500
        assert after == before + 1

    def test_query_500_does_not_leak_exception_text(self, test_client, mocker, auth_headers):
        mocker.patch.object(
            app.state.rag_chain, "invoke", side_effect=RuntimeError("secret internal detail")
        )
        response = test_client.post("/query", json={"question": "anything"}, headers=auth_headers)
        assert response.status_code == 500
        assert "secret internal detail" not in response.text

    def test_query_quota_error_returns_503_with_retry_after(
        self, test_client, mocker, auth_headers
    ):
        mocker.patch.object(
            app.state.rag_chain,
            "invoke",
            side_effect=Exception("429 RESOURCE_EXHAUSTED: quota exceeded"),
        )
        response = test_client.post("/query", json={"question": "anything"}, headers=auth_headers)
        assert response.status_code == 503
        assert response.headers["retry-after"] == "60"

    def test_query_increments_success_counter(self, test_client, auth_headers):
        # Regression guard for QUERY_COUNT.labels(status="success").inc().
        # Reads the success counter itself, so a 500 can't make this pass.
        before = metric_value(test_client.get("/metrics").text, "success")
        response = test_client.post(
            "/query", json={"question": "test question"}, headers=auth_headers
        )
        after = metric_value(test_client.get("/metrics").text, "success")
        assert response.status_code == 200
        assert after == before + 1