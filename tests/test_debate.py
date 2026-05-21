from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agents.debater import AgentResponse, DebaterAgent, OllamaServiceError
from core.rag_service import PolicyRAGService
from main import app

client = TestClient(app)


def _mock_successful_debater(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_generate_response(self: DebaterAgent, topic: str, history: list[dict[str, Any]]) -> AgentResponse:
        stance_map = {"usa": "supportive", "eu": "neutral", "china": "opposed"}
        stance = stance_map.get(self.country_code, "neutral")
        message = f"{self.display_name} speaks on {topic} with {stance} policy alignment."
        return AgentResponse(message=message, stance=stance)

    monkeypatch.setattr(DebaterAgent, "generate_response", fake_generate_response)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize(
    ("country_code", "expected_country"),
    [("usa", "USA"), ("eu", "EU"), ("china", "China")],
)
def test_policy_endpoints(country_code: str, expected_country: str) -> None:
    response = client.get(f"/policies/{country_code}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["country"] == expected_country
    assert isinstance(payload["key_positions"], list)
    assert isinstance(payload["red_lines"], list)


def test_policy_endpoint_missing_country_returns_404() -> None:
    response = client.get("/policies/unknown")
    assert response.status_code == 404


def test_root_serves_html() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


@pytest.mark.parametrize("payload", [{"topic": "", "rounds": 2}, {"topic": "   ", "rounds": 2}])
def test_empty_topic_validation(payload: dict[str, Any]) -> None:
    response = client.post("/debate/start", json=payload)
    assert response.status_code == 422


@pytest.mark.parametrize("rounds", [0, 6])
def test_invalid_round_validation(rounds: int) -> None:
    response = client.post("/debate/start", json={"topic": "Valid topic", "rounds": rounds})
    assert response.status_code == 422


@pytest.mark.parametrize("rounds,expected_count", [(2, 6), (3, 9)])
def test_debate_message_count(monkeypatch: pytest.MonkeyPatch, rounds: int, expected_count: int) -> None:
    _mock_successful_debater(monkeypatch)
    response = client.post("/debate/start", json={"topic": "Test climate topic", "rounds": rounds})
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["messages"]) == expected_count


def test_debate_agent_order_and_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_successful_debater(monkeypatch)
    response = client.post("/debate/start", json={"topic": "Test", "rounds": 3})
    assert response.status_code == 200

    payload = response.json()
    messages = payload["messages"]
    expected_agents = ["USA", "EU", "China", "USA", "EU", "China", "USA", "EU", "China"]
    assert [message["agent"] for message in messages] == expected_agents

    for message in messages:
        assert set(message.keys()) == {"round", "agent", "message", "stance", "timestamp"}
        assert isinstance(message["round"], int)
        assert isinstance(message["agent"], str)
        assert isinstance(message["message"], str)
        assert message["message"]
        assert message["stance"] in {"supportive", "opposed", "neutral"}
        assert isinstance(message["timestamp"], str)
        parsed_timestamp = datetime.fromisoformat(message["timestamp"].replace("Z", "+00:00"))
        assert parsed_timestamp.tzinfo is not None


def test_ollama_failure_returns_503(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_ollama_error(self: DebaterAgent, topic: str, history: list[dict[str, Any]]) -> AgentResponse:
        raise OllamaServiceError("Ollama unavailable")

    monkeypatch.setattr(DebaterAgent, "generate_response", raise_ollama_error)

    response = client.post("/debate/start", json={"topic": "Test", "rounds": 1})
    assert response.status_code == 503
    assert response.json()["detail"] == "Ollama unavailable"


def test_malformed_response_is_recovered(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_call(self: DebaterAgent, prompt: str) -> str:
        return "USA should lead with more renewables and a careful industrial transition. supportive"

    monkeypatch.setattr(DebaterAgent, "_call_ollama", fake_call)

    agent = DebaterAgent("usa", rag_service=PolicyRAGService())
    response = agent.generate_response("Clean energy transition", [])
    assert response.message
    assert response.stance in {"supportive", "opposed", "neutral"}


def test_stance_extraction_from_json_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_call(self: DebaterAgent, prompt: str) -> str:
        return '{"message": "We support coordinated action.", "stance": "supportive"}'

    monkeypatch.setattr(DebaterAgent, "_call_ollama", fake_call)

    agent = DebaterAgent("eu", rag_service=PolicyRAGService())
    response = agent.generate_response("Climate financing", [])
    assert response.message == "We support coordinated action."
    assert response.stance == "supportive"
