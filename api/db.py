"""Conexión a PostgreSQL compartida con el trading agent."""
import os
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        url = (
            f"postgresql://{os.getenv('POSTGRES_USER', 'trading')}:"
            f"{os.getenv('POSTGRES_PASSWORD', 'Tr4d1ng_Ag3nt_2026!')}@"
            f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
            f"{os.getenv('POSTGRES_PORT', '5432')}/"
            f"{os.getenv('POSTGRES_DB', 'trading_agent')}"
        )
        _engine = create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=10)
    return _engine


def q(sql: str, params: dict = None) -> list[dict]:
    """Ejecuta SQL y retorna lista de dicts."""
    with get_engine().connect() as conn:
        rows = conn.execute(text(sql), params or {}).fetchall()
    return [dict(r._mapping) for r in rows]


def q_one(sql: str, params: dict = None) -> dict | None:
    rows = q(sql, params)
    return rows[0] if rows else None
