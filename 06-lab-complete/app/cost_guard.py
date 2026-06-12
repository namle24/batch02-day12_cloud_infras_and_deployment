"""Redis-backed monthly budget protection."""
from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.config import settings
from app.redis_client import redis_client


def estimate_cost(input_tokens: int, output_tokens: int = 0) -> float:
    input_cost = input_tokens / 1000 * settings.input_price_per_1k_tokens
    output_cost = output_tokens / 1000 * settings.output_price_per_1k_tokens
    return round(input_cost + output_cost, 8)


def monthly_budget_key(user_id: str) -> str:
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    return f"budget:{user_id}:{month}"


def check_budget(user_id: str, estimated_cost: float) -> float:
    key = monthly_budget_key(user_id)
    current = float(redis_client.get(key) or 0)
    if current + estimated_cost > settings.monthly_budget_usd:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "Monthly budget exceeded",
                "used_usd": round(current, 6),
                "budget_usd": settings.monthly_budget_usd,
            },
        )
    return current


def record_usage(user_id: str, input_tokens: int, output_tokens: int) -> dict[str, float | int]:
    cost = estimate_cost(input_tokens, output_tokens)
    check_budget(user_id, cost)
    key = monthly_budget_key(user_id)
    new_total = redis_client.incrbyfloat(key, cost)
    redis_client.expire(key, 60 * 60 * 24 * 32)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "request_cost_usd": cost,
        "month_cost_usd": round(float(new_total), 6),
        "monthly_budget_usd": settings.monthly_budget_usd,
    }
