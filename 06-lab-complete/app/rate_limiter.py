"""Redis-backed sliding-window rate limiting."""
import time

from fastapi import HTTPException, status

from app.config import settings
from app.redis_client import redis_client


def check_rate_limit(user_id: str) -> dict[str, int]:
    now_ms = int(time.time() * 1000)
    window_ms = 60_000
    key = f"rate:{user_id}"

    pipe = redis_client.pipeline()
    pipe.zremrangebyscore(key, 0, now_ms - window_ms)
    pipe.zcard(key)
    _, count = pipe.execute()

    if count >= settings.rate_limit_per_minute:
        oldest = redis_client.zrange(key, 0, 0, withscores=True)
        retry_after = 60
        if oldest:
            retry_after = max(1, int((oldest[0][1] + window_ms - now_ms) / 1000) + 1)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "error": "Rate limit exceeded",
                "limit": settings.rate_limit_per_minute,
                "window_seconds": 60,
                "retry_after_seconds": retry_after,
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(settings.rate_limit_per_minute),
                "X-RateLimit-Remaining": "0",
            },
        )

    member = f"{now_ms}:{time.perf_counter_ns()}"
    pipe = redis_client.pipeline()
    pipe.zadd(key, {member: now_ms})
    pipe.expire(key, 120)
    pipe.execute()

    remaining = settings.rate_limit_per_minute - count - 1
    return {"limit": settings.rate_limit_per_minute, "remaining": max(0, remaining)}
