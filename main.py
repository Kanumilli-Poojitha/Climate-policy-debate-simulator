from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from agents.debater import DebaterAgent, OllamaServiceError
from core.rag_service import PolicyNotFoundError, PolicyRAGService
from core.config import settings
from core.logging_config import configure_logging, get_logger
from core.middleware import RequestLoggingMiddleware

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

configure_logging(debug=settings.DEBUG)
logger = get_logger(__name__)

app = FastAPI(
    title=settings.API_TITLE,
    version="1.0.0",
    description="A local-first multi-agent climate policy debate simulator powered by FastAPI and Ollama.",
)
app.add_middleware(RequestLoggingMiddleware)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

routing = APIRouter(prefix="/api/v1")

rag_service = PolicyRAGService()
DEBATE_ORDER = ["usa", "eu", "china"]
ALLOWED_STANCES = {"supportive", "opposed", "neutral"}


class DebateRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    topic: str = Field(min_length=1, description="The debate topic.")
    rounds: int = Field(ge=1, le=5, description="Number of debate rounds.")


class DebateMessage(BaseModel):
    round: int
    agent: str
    message: str
    stance: Literal["supportive", "opposed", "neutral"]
    timestamp: str


class DebateResponse(BaseModel):
    messages: list[DebateMessage]


@app.get("/", tags=["Frontend"], summary="Serve the debate interface")
def root() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", media_type="text/html")


@app.get("/health", tags=["Health"], summary="Health check endpoint")
def health() -> dict[str, str]:
    return {"status": "ok"}


@routing.get("/policies/{country_code}", tags=["Policies"], summary="Get a country policy document")
@app.get("/policies/{country_code}", tags=["Policies"], summary="Get a country policy document")
def get_policy(country_code: str) -> dict[str, object]:
    try:
        return rag_service.get_policy_document(country_code)
    except PolicyNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Failed to load policy document")
        raise HTTPException(status_code=500, detail=f"Failed to load policy document: {exc}") from exc


@routing.post("/debate/start", response_model=DebateResponse, tags=["Debate"], summary="Run a debate simulation")
@app.post("/debate/start", response_model=DebateResponse, tags=["Debate"], summary="Run a debate simulation")
def start_debate(request: DebateRequest, http_request: Request) -> DebateResponse:
    messages: list[DebateMessage] = []
    debate_history: list[dict[str, object]] = []
    request_id = getattr(http_request.state, "request_id", "-")
    logger.info("Starting debate", extra={"request_id": request_id, "topic": request.topic, "rounds": request.rounds})

    for round_number in range(1, request.rounds + 1):
        for country_code in DEBATE_ORDER:
            try:
                agent = DebaterAgent(country_code=country_code, rag_service=rag_service)
                agent_response = agent.generate_response(topic=request.topic, history=debate_history)
            except PolicyNotFoundError as exc:
                raise HTTPException(status_code=500, detail=str(exc)) from exc
            except OllamaServiceError as exc:
                logger.error("Ollama failed during debate", exc_info=exc, extra={"request_id": request_id})
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            except Exception as exc:
                logger.exception("Debate generation failed", extra={"request_id": request_id})
                raise HTTPException(status_code=500, detail=f"Debate generation failed for {country_code.upper()}: {exc}") from exc

            timestamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            message = DebateMessage(
                round=round_number,
                agent=agent.display_name,
                message=agent_response.message.strip() or "Policy-driven response unavailable.",
                stance=agent_response.stance if agent_response.stance in ALLOWED_STANCES else "neutral",
                timestamp=timestamp,
            )
            messages.append(message)
            debate_history.append(message.model_dump())
            logger.info("Round generated", extra={"request_id": request_id, "round": round_number, "agent": agent.display_name})

    return DebateResponse(messages=messages)


app.include_router(routing)
