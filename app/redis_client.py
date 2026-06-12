"""Shared Redis connection helpers."""
import redis

from app.config import settings


redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)


def ping_redis() -> bool:
    return bool(redis_client.ping())
