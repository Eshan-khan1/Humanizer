"""Security helpers for the local Humanizer API."""

from __future__ import annotations

import json
import os
import re
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path
from typing import Any, Iterable

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# --- Limits (override via env) ---

MAX_TEXT_CHARS = int(os.environ.get("HUMANIZER_MAX_TEXT_CHARS", "50000"))
MAX_PROMPT_CHARS = int(os.environ.get("HUMANIZER_MAX_PROMPT_CHARS", "2000"))
MAX_NOTES_CHARS = int(os.environ.get("HUMANIZER_MAX_NOTES_CHARS", "5000"))
MAX_PROFILE_FIELD_CHARS = int(os.environ.get("HUMANIZER_MAX_PROFILE_FIELD_CHARS", "500"))
MAX_CONTEXT_JSON_BYTES = int(os.environ.get("HUMANIZER_MAX_CONTEXT_JSON_BYTES", "32768"))
MAX_CONTEXT_DEPTH = int(os.environ.get("HUMANIZER_MAX_CONTEXT_DEPTH", "6"))
MAX_CONTEXT_STRING_CHARS = int(os.environ.get("HUMANIZER_MAX_CONTEXT_STRING_CHARS", "4000"))
MAX_REQUEST_BODY_BYTES = int(os.environ.get("HUMANIZER_MAX_REQUEST_BODY_BYTES", "262144"))
MAX_AI_API_KEY_CHARS = int(os.environ.get("HUMANIZER_MAX_AI_API_KEY_CHARS", "512"))
RATE_LIMIT_REQUESTS = int(os.environ.get("HUMANIZER_RATE_LIMIT_REQUESTS", "120"))
RATE_LIMIT_WINDOW_SEC = int(os.environ.get("HUMANIZER_RATE_LIMIT_WINDOW_SEC", "60"))

LOCAL_API_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
DEFAULT_CORS_ORIGINS = (
    "http://127.0.0.1:8000",
    "http://localhost:8000",
)
CHROME_EXTENSION_ORIGIN_RE = re.compile(r"^chrome-extension://[a-p]{32}$")

GENERIC_SERVER_ERROR = "An internal error occurred. Try again later."
GENERIC_AUTH_ERROR = "Unauthorized"

API_TOKEN = os.environ.get("HUMANIZER_API_TOKEN", "").strip()
REQUIRE_AUTH = os.environ.get("HUMANIZER_REQUIRE_AUTH", "").lower() in ("1", "true", "yes")
if REQUIRE_AUTH and not API_TOKEN:
    API_TOKEN = secrets.token_urlsafe(32)

EXPOSE_INTERNAL_ERRORS = os.environ.get("HUMANIZER_DEBUG", "").lower() in ("1", "true", "yes")


def cors_allowed_origins() -> list[str]:
    raw = os.environ.get("HUMANIZER_CORS_ORIGINS", "").strip()
    if not raw:
        return list(DEFAULT_CORS_ORIGINS)
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


def safe_error_detail(exc: Exception) -> str:
    if EXPOSE_INTERNAL_ERRORS:
        return str(exc)
    return GENERIC_SERVER_ERROR


def assert_text_length(value: str, *, field: str, limit: int = MAX_TEXT_CHARS) -> str:
    text = (value or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail=f"{field} must not be empty")
    if len(text) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"{field} exceeds maximum length of {limit} characters",
        )
    return text


def assert_optional_text_length(
    value: str | None,
    *,
    field: str,
    limit: int,
) -> str | None:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"{field} exceeds maximum length of {limit} characters",
        )
    return text


def _validate_context_node(node: Any, depth: int = 0) -> None:
    if depth > MAX_CONTEXT_DEPTH:
        raise HTTPException(status_code=413, detail="context nesting is too deep")
    if node is None or isinstance(node, (bool, int, float)):
        return
    if isinstance(node, str):
        if len(node) > MAX_CONTEXT_STRING_CHARS:
            raise HTTPException(status_code=413, detail="context string value is too long")
        return
    if isinstance(node, list):
        if len(node) > 64:
            raise HTTPException(status_code=413, detail="context list is too long")
        for item in node:
            _validate_context_node(item, depth + 1)
        return
    if isinstance(node, dict):
        if len(node) > 64:
            raise HTTPException(status_code=413, detail="context object has too many keys")
        for key, value in node.items():
            if not isinstance(key, str) or len(key) > 128:
                raise HTTPException(status_code=400, detail="context keys must be short strings")
            _validate_context_node(value, depth + 1)
        return
    raise HTTPException(status_code=400, detail="context contains unsupported value types")


def validate_context(context: dict[str, Any] | None) -> dict[str, Any] | None:
    if context is None:
        return None
    if not isinstance(context, dict):
        raise HTTPException(status_code=400, detail="context must be an object")
    try:
        encoded = json.dumps(context, ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="context must be JSON-serializable") from exc
    if len(encoded) > MAX_CONTEXT_JSON_BYTES:
        raise HTTPException(status_code=413, detail="context payload is too large")
    _validate_context_node(context)
    return context


def sanitize_profile_fields(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    if not isinstance(profile, dict):
        raise HTTPException(status_code=400, detail="profile must be an object")
    cleaned: dict[str, Any] = {}
    for key, value in profile.items():
        if not isinstance(key, str) or len(key) > 64:
            continue
        if value is None:
            continue
        if not isinstance(value, str):
            value = str(value)
        value = value.strip()
        if not value:
            continue
        if len(value) > MAX_PROFILE_FIELD_CHARS:
            raise HTTPException(
                status_code=413,
                detail=f"profile field '{key}' exceeds maximum length",
            )
        cleaned[key] = value
    return cleaned or None


def verify_api_token(request: Request) -> None:
    if not API_TOKEN:
        return
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=GENERIC_AUTH_ERROR)
    token = auth_header[7:].strip()
    if not token or not secrets.compare_digest(token, API_TOKEN):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=GENERIC_AUTH_ERROR)


def client_host(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host
    return ""


def is_local_client(request: Request) -> bool:
    return client_host(request) in LOCAL_API_HOSTS


def require_local_client(request: Request) -> None:
    if not is_local_client(request):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


def resolve_debug_log_path(default_relative: str = ".cursor/debug.log") -> Path:
    raw = os.environ.get("HUMANIZER_DEBUG_LOG", "").strip()
    if raw:
        candidate = Path(raw).expanduser()
    else:
        candidate = Path(__file__).resolve().parent / default_relative
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = Path(__file__).resolve().parent / default_relative
    project_root = Path(__file__).resolve().parent
    if project_root not in resolved.parents and resolved != project_root:
        resolved = project_root / default_relative
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Permissions-Policy"] = "interest-cohort=()"
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
            except ValueError:
                return JSONResponse(
                    {"detail": "Invalid Content-Length header"},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            if size > MAX_REQUEST_BODY_BYTES:
                return JSONResponse(
                    {"detail": "Request body too large"},
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                )
        return await call_next(request)


class LocalClientMiddleware(BaseHTTPMiddleware):
    """Reject non-local clients — defense in depth for localhost-bound server."""

    async def dispatch(self, request: Request, call_next):
        if not is_local_client(request):
            return JSONResponse({"detail": "Forbidden"}, status_code=status.HTTP_403_FORBIDDEN)
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, limit: int = RATE_LIMIT_REQUESTS, window_sec: int = RATE_LIMIT_WINDOW_SEC):
        super().__init__(app)
        self.limit = limit
        self.window_sec = window_sec
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def _rate_key(self, request: Request) -> str:
        host = client_host(request) or "unknown"
        return f"{host}:{request.method}:{request.url.path}"

    async def dispatch(self, request: Request, call_next):
        if request.method == "GET" and request.url.path == "/health":
            return await call_next(request)

        now = time.monotonic()
        key = self._rate_key(request)
        bucket = self._events[key]
        while bucket and now - bucket[0] > self.window_sec:
            bucket.popleft()
        if len(bucket) >= self.limit:
            return JSONResponse(
                {"detail": "Too many requests. Slow down and try again."},
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            )
        bucket.append(now)
        return await call_next(request)


def sanitize_ai_config(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise HTTPException(status_code=400, detail="ai must be an object")
    provider = str(raw.get("provider") or raw.get("aiProvider") or "local").strip().lower()
    if provider in {"", "local", "ollama"}:
        return None
    if provider not in {"groq", "openai"}:
        raise HTTPException(status_code=400, detail="ai.provider must be groq or openai")
    api_key = str(raw.get("api_key") or raw.get("apiKey") or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="ai.apiKey is required for cloud providers")
    if len(api_key) > MAX_AI_API_KEY_CHARS:
        raise HTTPException(status_code=413, detail="ai.apiKey is too long")
    model = str(raw.get("model") or "").strip()
    if model and len(model) > 128:
        raise HTTPException(status_code=413, detail="ai.model is too long")
    cleaned: dict[str, Any] = {"provider": provider, "api_key": api_key}
    if model:
        cleaned["model"] = model
    return cleaned


def origin_allowed(origin: str, allowed_origins: Iterable[str]) -> bool:
    if not origin:
        return True
    if origin in allowed_origins:
        return True
    return bool(CHROME_EXTENSION_ORIGIN_RE.match(origin))
