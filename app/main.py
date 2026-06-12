"""Production-ready FastAPI agent for the Day 12 lab."""
import json
import logging
import re
import signal
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import uvicorn

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, estimate_cost, record_usage
from app.rate_limiter import check_rate_limit
from app.redis_client import ping_redis, redis_client
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        return json.dumps(payload)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logging.basicConfig(level=settings.log_level.upper(), handlers=[handler], force=True)
logger = logging.getLogger("agent")

START_TIME = time.time()
INSTANCE_ID = f"agent-{uuid.uuid4().hex[:8]}"
is_ready = False
request_count = 0
error_count = 0


class AskRequest(BaseModel):
    user_id: str = Field(default="default", min_length=1, max_length=80)
    question: str = Field(..., min_length=1, max_length=2000)


class AskResponse(BaseModel):
    user_id: str
    question: str
    answer: str
    model: str
    served_by: str
    usage: dict[str, Any]
    timestamp: str


def history_key(user_id: str) -> str:
    return f"history:{user_id}"


def load_history(user_id: str) -> list[dict[str, str]]:
    raw_messages = redis_client.lrange(history_key(user_id), 0, -1)
    return [json.loads(message) for message in raw_messages]


def append_history(user_id: str, role: str, content: str) -> None:
    message = {
        "role": role,
        "content": content,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    key = history_key(user_id)
    redis_client.rpush(key, json.dumps(message))
    redis_client.ltrim(key, -settings.max_history_messages, -1)
    redis_client.expire(key, settings.history_ttl_seconds)


def answer_with_context(question: str, history: list[dict[str, str]]) -> str:
    question_lower = question.lower()
    if "my name" in question_lower or "what is my name" in question_lower:
        for message in reversed(history):
            if message["role"] != "user":
                continue
            match = re.search(r"\bmy name is\s+([A-Za-z][A-Za-z .'-]{0,50})", message["content"], re.I)
            if match:
                name = match.group(1).strip(" .")
                return f"You told me your name is {name}."
    return llm_ask(question)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global is_ready
    logger.info(json.dumps({"event": "startup", "instance": INSTANCE_ID}))
    ping_redis()
    is_ready = True
    logger.info(json.dumps({"event": "ready", "storage": "redis"}))
    yield
    is_ready = False
    logger.info(json.dumps({"event": "shutdown", "instance": INSTANCE_ID}))


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def request_logging(request: Request, call_next):
    global request_count, error_count
    start = time.time()
    request_count += 1
    try:
        response: Response = await call_next(request)
    except Exception:
        error_count += 1
        logger.exception(json.dumps({"event": "request_failed", "path": request.url.path}))
        raise

    duration_ms = round((time.time() - start) * 1000, 2)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Instance-ID"] = INSTANCE_ID
    logger.info(json.dumps({
        "event": "request",
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "duration_ms": duration_ms,
    }))
    return response


@app.get("/")
def root():
    return {
        "app": settings.app_name,
        "version": settings.app_version,
        "endpoints": ["/health", "/ready", "/ask"],
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "version": settings.app_version,
        "instance": INSTANCE_ID,
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": request_count,
        "error_count": error_count,
    }


@app.get("/ready")
def ready():
    if not is_ready:
        raise HTTPException(status_code=503, detail="Application is not ready")
    try:
        ping_redis()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Redis is not ready") from exc
    return {"ready": True, "storage": "redis", "instance": INSTANCE_ID}


@app.post("/ask", response_model=AskResponse)
def ask_agent(body: AskRequest, _: str = Depends(verify_api_key)):
    check_rate_limit(body.user_id)
    history = load_history(body.user_id)

    input_tokens = max(1, len(body.question.split()) * 2)
    estimated = estimate_cost(input_tokens, 80)
    check_budget(body.user_id, estimated)

    append_history(body.user_id, "user", body.question)
    answer = answer_with_context(body.question, history)
    append_history(body.user_id, "assistant", answer)

    output_tokens = max(1, len(answer.split()) * 2)
    usage = record_usage(body.user_id, input_tokens, output_tokens)

    logger.info(json.dumps({
        "event": "agent_response",
        "user_id": body.user_id,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "served_by": INSTANCE_ID,
    }))

    return AskResponse(
        user_id=body.user_id,
        question=body.question,
        answer=answer,
        model=settings.llm_model,
        served_by=INSTANCE_ID,
        usage=usage,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/history/{user_id}")
def get_user_history(user_id: str, _: str = Depends(verify_api_key)):
    history = load_history(user_id)
    return {"user_id": user_id, "messages": history, "count": len(history)}


@app.get("/metrics")
def metrics(_: str = Depends(verify_api_key)):
    return {
        "uptime_seconds": round(time.time() - START_TIME, 1),
        "total_requests": request_count,
        "error_count": error_count,
        "instance": INSTANCE_ID,
    }


def handle_sigterm(signum, _frame) -> None:
    logger.info(json.dumps({"event": "graceful_shutdown_signal", "signal": signum}))


signal.signal(signal.SIGTERM, handle_sigterm)


if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.environment == "development",
        timeout_graceful_shutdown=30,
    )
