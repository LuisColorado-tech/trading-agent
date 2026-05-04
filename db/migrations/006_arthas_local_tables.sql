-- Migración Supabase → Local PostgreSQL para Arthas/Arthas-bot
-- Tablas usadas por personality_sync.py, profile_sync.py, compact_to_supabase.py, etc.

-- Perfil de hechos (datos de personas: madre, lucho, etc.)
CREATE TABLE IF NOT EXISTS perfil_hechos (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id      UUID,
    categoria       VARCHAR(100) NOT NULL,
    clave           VARCHAR(200) NOT NULL,
    valor           TEXT NOT NULL,
    fuente          VARCHAR(50) DEFAULT 'manual',
    confianza       REAL DEFAULT 1.0,
    activo          BOOLEAN DEFAULT true,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(persona_id, categoria, clave)
);
CREATE INDEX IF NOT EXISTS idx_perfil_hechos_persona ON perfil_hechos(persona_id, categoria, activo);

-- Personas registradas
CREATE TABLE IF NOT EXISTS personas (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    nombre          VARCHAR(200) NOT NULL,
    relacion        VARCHAR(100),
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_personas_nombre ON personas(nombre);

-- Rasgos de personalidad (para personality_sync.py)
CREATE TABLE IF NOT EXISTS rasgos_personalidad (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id      UUID REFERENCES personas(id),
    rasgo           VARCHAR(100) NOT NULL,
    puntuacion      REAL DEFAULT 0.5,
    confianza       REAL DEFAULT 1.0,
    fuente          VARCHAR(50) DEFAULT 'manual',
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_rasgos_persona ON rasgos_personalidad(persona_id);

-- Sesiones compactadas (antes en Supabase, ahora local)
CREATE TABLE IF NOT EXISTS sesiones_compactas (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      VARCHAR(100),
    resumen          TEXT NOT NULL,
    mensajes_count   INTEGER DEFAULT 0,
    fecha            DATE NOT NULL DEFAULT CURRENT_DATE,
    metadata         JSONB DEFAULT '{}',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sesiones_fecha ON sesiones_compactas(fecha DESC);

-- Aprendizaje de personalidad (interacciones analizadas)
CREATE TABLE IF NOT EXISTS aprendizaje_personalidad (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    persona_id      UUID REFERENCES personas(id),
    mensaje_usuario TEXT,
    respuesta_arthas TEXT,
    rasgos_afectados JSONB DEFAULT '[]',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Seed: persona de Arthas (necesaria para personality_sync)
INSERT INTO personas (id, nombre, relacion) VALUES
    ('00000000-0000-0000-0000-000000000001', 'Arthas', 'asistente')
ON CONFLICT (id) DO NOTHING;

INSERT INTO perfil_hechos (persona_id, categoria, clave, valor, fuente)
VALUES
    ('00000000-0000-0000-0000-000000000001', 'comunicacion', 'estilo', 'directo, informal, colombiano', 'foundation'),
    ('00000000-0000-0000-0000-000000000001', 'comunicacion', 'formalidad', 'informal', 'foundation'),
    ('00000000-0000-0000-0000-000000000001', 'comunicacion', 'idioma', 'español colombiano con jerga paisa', 'foundation'),
    ('00000000-0000-0000-0000-000000000001', 'personaje', 'arquetipo', 'paladín paisa caballero de la muerte', 'foundation'),
    ('00000000-0000-0000-0000-000000000001', 'personaje', 'energia', 'protector, firme, leal', 'foundation'),
    ('00000000-0000-0000-0000-000000000001', 'personaje', 'humor', 'sarcástico pero amable', 'foundation')
ON CONFLICT (persona_id, categoria, clave) DO NOTHING;
