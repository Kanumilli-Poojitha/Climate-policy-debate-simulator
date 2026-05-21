from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from core.logging_config import get_logger

logger = get_logger(__name__)


class PolicyNotFoundError(FileNotFoundError):
    pass


@dataclass(frozen=True)
class PolicyDocument:
    country: str
    key_positions: list[str]
    red_lines: list[str]

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "PolicyDocument":
        return cls(
            country=str(payload.get("country", "")).strip(),
            key_positions=[str(item).strip() for item in payload.get("key_positions", []) if str(item).strip()],
            red_lines=[str(item).strip() for item in payload.get("red_lines", []) if str(item).strip()],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "country": self.country,
            "key_positions": list(self.key_positions),
            "red_lines": list(self.red_lines),
        }


class PolicyRAGService:
    def __init__(self, policies_dir: Path | None = None) -> None:
        self.policies_dir = policies_dir or Path(__file__).resolve().parent.parent / "data" / "policies"
        self._country_to_filename = {
            "usa": "usa_policy.json",
            "eu": "eu_policy.json",
            "china": "china_policy.json",
        }
        self._cache: dict[str, PolicyDocument] = {}

    def get_policy_document(self, country_code: str) -> dict[str, Any]:
        doc = self._load_policy_document(country_code)
        logger.debug("Loaded policy document", extra={"country": doc.country, "request_id": "-"})
        return doc.to_dict()

    def get_relevant_policy_points(self, country_code: str, query: str, limit: int = 4) -> list[str]:
        document = self._load_policy_document(country_code)
        query_terms = self._tokenize(query)
        scored_points: list[tuple[int, int, str]] = []
        for index, point in enumerate(document.key_positions + document.red_lines):
            score = self._score_text(point, query_terms)
            scored_points.append((score, index, point))

        if query_terms:
            scored_points.sort(key=lambda item: (-item[0], item[1]))

        selected = [point for score, _, point in scored_points if score > 0][:limit]
        if not selected:
            selected = (document.key_positions + document.red_lines)[:limit]
        return selected

    def build_context(self, country_code: str, query: str, history: list[dict[str, Any]]) -> str:
        policy_points = self.get_relevant_policy_points(country_code, query, limit=4)
        recent_history = self._format_history(history[-6:])
        policy_text = self._format_bullets(policy_points) or "- No policy points available."
        history_text = recent_history or "- No prior debate history."
        return (
            f"Country: {self._normalize_country_code(country_code)}\n"
            f"Retrieved policy points:\n{policy_text}\n\n"
            f"Recent debate history:\n{history_text}"
        )

    def _load_policy_document(self, country_code: str) -> PolicyDocument:
        normalized = country_code.lower().strip()
        filename = self._country_to_filename.get(normalized)
        if not filename:
            raise PolicyNotFoundError(f"Unsupported country code: {country_code}")

        cache_key = normalized
        if cache_key in self._cache:
            return self._cache[cache_key]

        policy_path = self.policies_dir / filename
        if not policy_path.exists():
            raise PolicyNotFoundError(f"Policy document not found for country code: {country_code}")

        with policy_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        document = PolicyDocument.from_dict(payload)
        self._cache[cache_key] = document
        logger.info("Policy document cached", extra={"country": document.country, "path": str(policy_path), "request_id": "-"})
        return document

    @staticmethod
    def _tokenize(text: str) -> set[str]:
        return {token.lower() for token in text.replace("/", " ").replace("-", " ").split() if token.strip()}

    @staticmethod
    def _score_text(text: str, query_terms: set[str]) -> int:
        text_terms = PolicyRAGService._tokenize(text)
        return len(text_terms.intersection(query_terms))

    @staticmethod
    def _format_history(history: list[dict[str, Any]]) -> str:
        lines = []
        for item in history:
            round_number = item.get("round")
            agent = item.get("agent")
            message = item.get("message")
            lines.append(f"- Round {round_number} | {agent}: {message}")
        return "\n".join(lines)

    @staticmethod
    def _format_bullets(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items)

    @staticmethod
    def _normalize_country_code(country_code: str) -> str:
        return country_code.strip().upper()
