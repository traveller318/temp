"""Offline endpoint tests: use the mock provider and a simulated provider failure."""
import os

os.environ["LLM_PROVIDER"] = "mock"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import rag_pipeline  # noqa: E402
from app import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["rag_loaded"] and body["indexed_chunks"] > 0


def test_supported_question(client):
    resp = client.post("/ask", json={"question": "How do I request a refund?"})
    body = resp.json()
    assert resp.status_code == 200
    assert body["intent"] == "returns_refunds"
    assert not body["is_fallback"] and body["retry_count"] == 0
    assert body["latency_ms"] > 0 and body["sources"] and body["request_id"]


def test_unsupported_question_falls_back(client):
    body = client.post("/ask", json={"question": "Do you sell home insurance?"}).json()
    assert body["is_fallback"] and body["retry_count"] == 1 and body["sources"] == []
    assert body["answer"] == rag_pipeline.SAFE_FALLBACK_REPLY


@pytest.mark.parametrize("payload", [{"question": "   "}, {"question": "x" * 1001}, {}, {"question": 42}])
def test_invalid_input_rejected(client, payload):
    resp = client.post("/ask", json=payload)
    assert resp.status_code == 422
    assert "x" * 50 not in resp.text  # input is not echoed back


def test_malformed_json_rejected(client):
    resp = client.post("/ask", content="not json", headers={"Content-Type": "application/json"})
    assert resp.status_code == 422 and resp.json()["detail"][0]["field"] == "body"


def test_provider_failure_is_hidden(client, monkeypatch):
    def broken(_prompt):
        raise rag_pipeline.LLMServiceError("provider returned HTTP 401")

    monkeypatch.setitem(rag_pipeline.PROVIDERS, "mock", broken)
    resp = client.post("/ask", json={"question": "How do I request a refund?"})
    assert resp.status_code == 503
    assert "401" not in resp.text and resp.json()["request_id"]


def test_groq_without_key_raises(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "")
    with pytest.raises(rag_pipeline.LLMServiceError):
        rag_pipeline.call_groq("hi")
