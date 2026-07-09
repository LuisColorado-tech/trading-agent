-- Hermes Agent — Tablas locales PostgreSQL
-- Schema: public (misma DB trading_agent)
-- Reemplaza Supabase para datos de Arthas/OpenClaw

-- Sesiones de conversación
CREATE TABLE IF NOT EXISTS hermes_sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      VARCHAR(100) UNIQUE NOT NULL,
    user_id         VARCHAR(100),
    platform        VARCHAR(20) DEFAULT 'telegram',
    title           VARCHAR(500),
    message_count   INTEGER DEFAULT 0,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    ended_at        TIMESTAMPTZ,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_hermes_sessions_user ON hermes_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_hermes_sessions_started ON hermes_sessions(started_at DESC);

-- Mensajes individuales
CREATE TABLE IF NOT EXISTS hermes_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      VARCHAR(100) NOT NULL REFERENCES hermes_sessions(session_id),
    role            VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content         TEXT,
    tool_calls      JSONB,
    token_count     INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_hermes_messages_session ON hermes_messages(session_id, created_at);

-- Memoria persistente (reemplaza Supabase para USER.md, MEMORY.md)
CREATE TABLE IF NOT EXISTS hermes_memories (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category        VARCHAR(50) NOT NULL DEFAULT 'general',
    key             VARCHAR(200) NOT NULL,
    value           TEXT NOT NULL,
    embedding       TEXT,
    importance      INTEGER DEFAULT 5 CHECK (importance BETWEEN 1 AND 10),
    source          VARCHAR(50) DEFAULT 'manual',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(category, key)
);

CREATE INDEX IF NOT EXISTS idx_hermes_memories_category ON hermes_memories(category);

-- Perfil de usuario (reemplaza Supabase para user profiles)
CREATE TABLE IF NOT EXISTS hermes_user_profile (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         VARCHAR(100) DEFAULT 'default',
    field           VARCHAR(100) NOT NULL,
    value           TEXT NOT NULL,
    source          VARCHAR(50) DEFAULT 'manual',
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(user_id, field)
);

-- Tareas programadas (cron jobs de Hermes)
CREATE TABLE IF NOT EXISTS hermes_cron_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(100) UNIQUE NOT NULL,
    schedule        VARCHAR(100) NOT NULL,
    platform        VARCHAR(20) DEFAULT 'telegram',
    prompt          TEXT NOT NULL,
    enabled         BOOLEAN DEFAULT true,
    last_run        TIMESTAMPTZ,
    next_run        TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Migración: datos existentes de OpenClaw desde archivos MD
INSERT INTO hermes_memories (category, key, value, source)
VALUES
    ('identity', 'user_name', 'Luis Colorado', 'openclaw_migration'),
    ('identity', 'user_location', 'Medellín, Colombia', 'openclaw_migration'),
    ('identity', 'timezone', 'America/Bogota', 'openclaw_migration'),
    ('trading', 'role', 'Sistema de trading algorítmico paper — 6 agentes activos', 'openclaw_migration')
ON CONFLICT (category, key) DO NOTHING;

-- Versión del schema
COMMENT ON TABLE hermes_sessions IS 'Hermes Agent v1 — sesiones de conversación';
COMMENT ON TABLE hermes_messages IS 'Hermes Agent v1 — mensajes';
COMMENT ON TABLE hermes_memories IS 'Hermes Agent v1 — memoria persistente';
COMMENT ON TABLE hermes_user_profile IS 'Hermes Agent v1 — perfil de usuario';
COMMENT ON TABLE hermes_cron_jobs IS 'Hermes Agent v1 — tareas programadas';
