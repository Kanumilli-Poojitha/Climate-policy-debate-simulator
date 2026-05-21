from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import requests

from core.rag_service import PolicyRAGService
from core.config import settings
from core.logging_config import get_logger
import time
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = get_logger(__name__)


@dataclass(frozen=True)
class AgentResponse:
    message: str
    stance: str


class OllamaServiceError(RuntimeError):
    pass


class DebaterAgent:
    def __init__(self, country_code: str, rag_service: PolicyRAGService) -> None:
        self.country_code = country_code.lower().strip()
        self.display_name = self._display_name(country_code)
        self.rag_service = rag_service
        self.ollama_base_url = settings.OLLAMA_BASE_URL.rstrip("/")
        self.model_name = settings.LLM_MODEL_NAME
        self.timeout = settings.OLLAMA_TIMEOUT
        self.retries = settings.OLLAMA_RETRIES
        self.session = requests.Session()
        retry_strategy = Retry(total=max(0, int(self.retries)), backoff_factor=0.5, status_forcelist=[429, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def generate_response(self, topic: str, history: list[dict[str, Any]]) -> AgentResponse:
        policy_context = self.rag_service.build_context(self.country_code, topic, history)
        prompt = self._build_prompt(topic, history, policy_context)
        raw_text = self._call_ollama(prompt)
        return self._parse_response(raw_text, topic, history, policy_context)

    def _call_ollama(self, prompt: str) -> str:
        url = f"{self.ollama_base_url}/api/generate"
        payload = {
            "model": self.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.5,
                "top_p": 0.9,
                "repeat_penalty": 1.15,
                "num_predict": 80,
            },
        }
        start = time.time()
        try:
            response = self.session.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            body = response.json()
        except requests.RequestException as exc:
            logger.error("Ollama request failed", exc_info=exc, extra={"request_id": "-"})
            raise OllamaServiceError(f"Unable to reach Ollama at {url}: {exc}") from exc
        except ValueError as exc:
            logger.error("Ollama returned non-JSON", exc_info=exc, extra={"request_id": "-"})
            raise OllamaServiceError("Ollama returned a non-JSON response.") from exc

        elapsed = time.time() - start
        logger.info("Ollama generate completed", extra={"request_id": "-", "model": self.model_name, "elapsed": elapsed})

        raw_response = str(body.get("response", "")).strip()
        if not raw_response:
            logger.warning("Ollama returned empty response", extra={"request_id": "-"})
            raise OllamaServiceError("Ollama response was empty.")
        return raw_response

    def _build_prompt(self, topic: str, history: list[dict[str, Any]], policy_context: str) -> str:
        history_text = self._format_history(history)
        return (
            f"System role: You are the climate policy representative for {self.display_name}.\n"
            f"Debate topic: {topic}\n\n"
            f"Debate history so far:\n{history_text}\n\n"
            f"Retrieved policy grounding:\n{policy_context}\n\n"
            f"Response contract:\n"
            f"- Stay in character and speak for {self.display_name}.\n"
            f"- Be diplomatic, concrete, and concise.\n"
            f"- Avoid repeating wording from prior turns unless necessary.\n"
            f"- Use only the policy grounding above; do not introduce unsupported claims.\n"
            f"- Return a single JSON object with keys message and stance.\n"
            f"- message must be one paragraph and non-empty.\n"
            f"- stance must be exactly one of supportive, opposed, neutral.\n"
            f"- Do not wrap the JSON in markdown fences or additional commentary.\n"
        )

    def _parse_response(
        self,
        raw_text: str,
        topic: str,
        history: list[dict[str, Any]],
        policy_context: str,
    ) -> AgentResponse:
        candidate = raw_text.strip()
        json_candidate = self._extract_json_fragment(candidate)
        if json_candidate is not None:
            try:
                payload = json.loads(json_candidate)
                message = self._normalize_message(str(payload.get("message", "")))
                stance = self._normalize_stance(str(payload.get("stance", "")).strip())
                if message and stance:
                    return AgentResponse(message=message, stance=stance)
            except json.JSONDecodeError:
                pass

        stance = self._extract_stance(candidate) or self._infer_stance_from_country()
        message = self._extract_message(candidate)
        if not message:
            message = self._default_message(topic, history, policy_context)
        return AgentResponse(message=message, stance=stance)

    def _default_message(self, topic: str, history: list[dict[str, Any]], policy_context: str) -> str:
        return (
            f"On {topic}, {self.display_name} will respond with a policy-focused position grounded in the retrieved evidence."
        )

    def _extract_message(self, text: str) -> str:
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL)
        match = re.search(r'"message"\s*:\s*"(.*?)"\s*(?:,\s*"stance"\s*:|\})', text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return self._normalize_message(match.group(1))

        match = re.search(r"message\s*[:=]\s*(.+?)(?:stance\s*[:=]|$)", text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return self._normalize_message(match.group(1))
        return self._normalize_message(text)

    def _extract_stance(self, text: str) -> str:
        match = re.search(r'"stance"\s*:\s*"(supportive|opposed|neutral)"', text, flags=re.IGNORECASE)
        if match:
            return self._normalize_stance(match.group(1))

        match = re.search(r"\b(supportive|opposed|neutral)\b", text, flags=re.IGNORECASE)
        if match:
            return self._normalize_stance(match.group(1))
        return ""

    def _infer_stance_from_country(self) -> str:
        default_map = {
            "usa": "supportive",
            "eu": "supportive",
            "china": "neutral",
        }
        return default_map.get(self.country_code, "neutral")

    @staticmethod
    def _normalize_stance(stance: str) -> str:
        allowed = {"supportive", "opposed", "neutral"}
        normalized = stance.lower().strip()
        return normalized if normalized in allowed else "neutral"

    @staticmethod
    def _normalize_message(message: str) -> str:
        collapsed = re.sub(r"\s+", " ", message).strip()
        return collapsed.strip('"').strip("'")

    @staticmethod
    def _extract_json_fragment(text: str) -> str | None:
        candidate = text.strip()
        fenced = re.search(r"```json\s*(\{.*?\})\s*```", candidate, flags=re.IGNORECASE | re.DOTALL)
        if fenced:
            return fenced.group(1)
        if candidate.startswith("{") and candidate.endswith("}"):
            return candidate
        return None

    @staticmethod
    def _display_name(country_code: str) -> str:
        mapping = {"usa": "USA", "eu": "EU", "china": "China"}
        return mapping.get(country_code.lower().strip(), country_code.upper())

    @staticmethod
    def _format_history(history: list[dict[str, Any]]) -> str:
        if not history:
            return "No previous debate turns."
        lines = []
        for entry in history:
            lines.append(f"Round {entry.get('round')}, {entry.get('agent')}: {entry.get('message')}")
        return "\n".join(lines)
