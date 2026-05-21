from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    OLLAMA_BASE_URL: str = Field("http://ollama:11434", env="OLLAMA_BASE_URL")
    LLM_MODEL_NAME: str = Field("phi3", env="LLM_MODEL_NAME")
    API_TITLE: str = Field("AI-Powered Climate Policy Debate Simulator", env="API_TITLE")
    DEBUG: bool = Field(False, env="DEBUG")
    OLLAMA_TIMEOUT: int = Field(300, env="OLLAMA_TIMEOUT")
    OLLAMA_RETRIES: int = Field(1, env="OLLAMA_RETRIES")

    class Config:
        env_file = ".env"


settings = Settings()
