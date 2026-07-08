"""
Agents Corp — Shared Infrastructure

Database connections, authentication, rate limiting, logging.
Used by all business units.
"""
import os
import sys
import hashlib
import secrets
import time
from datetime import datetime, timezone

import redis
from loguru import logger
from sqlalchemy import create_engine, text

# ─── Database ──────────────────────────────────────────────────────

DB_URL = (
    f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB', 'trading_agent')}"
)

engine = create_engine(DB_URL, pool_size=5, max_overflow=10)

def get_db():
    return engine

# ─── Redis ─────────────────────────────────────────────────────────

redis_client = redis.Redis(
    host=os.getenv('REDIS_HOST', 'localhost'),
    port=int(os.getenv('REDIS_PORT', 6379)),
    password=os.getenv('REDIS_PASSWORD') or None,
    decode_responses=True,
)

# ─── Authentication (API Keys) ─────────────────────────────────────

def generate_api_key() -> str:
    return 'ak_' + secrets.token_hex(16)

def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()

def validate_api_key(key: str) -> dict | None:
    """Returns user dict if valid, None if invalid."""
    hashed = hash_api_key(key)
    with engine.connect() as conn:
        row = conn.execute(text(
            "SELECT id, plan, tokens_used, tokens_limit FROM api_users WHERE api_key_hash = :h AND active = true"
        ), {'h': hashed}).fetchone()
    if row:
        return dict(row._mapping)
    return None

# ─── Rate Limiting ─────────────────────────────────────────────────

def check_rate_limit(key: str, max_requests: int = 100, window_seconds: int = 3600) -> bool:
    """Returns True if allowed, False if rate limited."""
    current = redis_client.get(f'ratelimit:{key}')
    if current is None:
        redis_client.setex(f'ratelimit:{key}', window_seconds, 1)
        return True
    count = int(current)
    if count >= max_requests:
        return False
    redis_client.incr(f'ratelimit:{key}')
    return True

def track_token_usage(user_id: str, tokens: int):
    """Increment token usage for billing."""
    with engine.begin() as conn:
        conn.execute(text(
            "UPDATE api_users SET tokens_used = tokens_used + :tokens WHERE id = :id"
        ), {'tokens': tokens, 'id': user_id})
    redis_client.incrby(f'usage:{user_id}', tokens)

# ─── Logging ───────────────────────────────────────────────────────

def setup_logger(name: str, log_file: str = None):
    """Configure structured logging for a business unit."""
    logger.remove()
    logger.add(
        sys.stderr,
        format=f'<green>{{time:HH:mm:ss}}</green> | <level>{{level: <8}}</level> | <cyan>{name}</cyan> | {{message}}',
        level='INFO',
    )
    if log_file:
        logger.add(log_file, rotation='1 day', retention='30 days', level='DEBUG')
    return logger
