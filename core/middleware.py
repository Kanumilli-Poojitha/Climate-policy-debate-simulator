from __future__ import annotations

import logging
import time
import uuid
from typing import Callable

from fastapi import Request
from starlette.types import ASGIApp


def request_id() -> str:
    return uuid.uuid4().hex


class RequestLoggingMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        request = Request(scope, receive=receive)
        rid = request_id()
        scope.setdefault("state", {})["request_id"] = rid
        start = time.time()
        logger = logging.getLogger("app.request")
        response = None
        try:
            await self.app(scope, receive, send)
        finally:
            elapsed = time.time() - start
            logger.info(f"{request.method} {request.url.path} completed in {elapsed:.3f}s", extra={"request_id": rid})
