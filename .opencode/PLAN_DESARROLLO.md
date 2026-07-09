# PLAN DE DESARROLLO — Agents Corp

## Sprint 1: Infraestructura Compartida (VP Development)
**Due: 48 horas**

- [ ] Crear `/opt/agents-corp/` con estructura de directorios
- [ ] Módulo shared/db.py — conexión PostgreSQL unificada
- [ ] Módulo shared/auth.py — generación/validación de API keys
- [ ] Módulo shared/rate_limit.py — rate limiting con Redis
- [ ] Módulo shared/logging.py — logging estructurado con Loguru
- [ ] Venv unificado: `/opt/agents-corp/venv/`
- [ ] Script de deploy: `systemd` para cada servicio en puertos 9000-9010

## Sprint 2: DeepAPI MVP (CEO DeepAPI + VP Dev)
**Due: 3 días**

- [ ] API Gateway FastAPI (puerto 9001)
- [ ] Endpoint `/v1/chat/completions` compatible con OpenAI SDK
- [ ] Rate limiting por API key (Redis)
- [ ] Tracking de uso (tokens consumidos por usuario)
- [ ] Registro de usuarios + generación de API keys
- [ ] Documentación simple (README.md con ejemplos curl/python)
- [ ] Planes: Free (100 req/día), Pro ($10/mes 500K tokens), Business ($30/mes 2M)

## Sprint 3: PriceGuard MVP (CEO PriceGuard + VP Dev)
**Due: 3 días**

- [ ] Scraper MercadoLibre Argentina (productos electrónicos)
- [ ] Detección de cambios de precio >15%
- [ ] Almacenamiento en PostgreSQL (histórico de precios)
- [ ] Alertas vía Telegram
- [ ] Dashboard web simple (FastAPI puerto 9002)
- [ ] Free tier: 5 productos. Pro tier: 100 productos ($30/mes)

## Sprint 4: ViralBot MVP (CEO ViralBot + VP Dev)
**Due: 3 días**

- [ ] Scraper de noticias financieras (5 fuentes)
- [ ] Generación de contenido con DeepSeek (threads, posts)
- [ ] Cola de revisión (archivos markdown para que el Presidente revise)
- [ ] Publicación vía Twitter API v2
- [ ] Métricas: seguidores, engagement

## Sprint 5: LeadGen MVP (CEO LeadGen + VP Dev)
**Due: 3 días**

- [ ] Scraper Google Maps (negocios por categoría)
- [ ] Email finder (Hunter.io API o similar)
- [ ] AI scoring de leads (DeepSeek)
- [ ] Export CSV
- [ ] Fiverr gig creado

## Sprint 6: Go-to-Market (VP Marketing)
**Due: Continua desde Sprint 2**

- [ ] Landing pages por unidad de negocio
- [ ] GitHub repos open-source (DeepAPI SDK)
- [ ] Contenido YouTube: 3 tutoriales
- [ ] Presencia en comunidades (WhatsApp, Reddit, dev.to)
- [ ] Campañas de referidos

## Métricas de Éxito (30 días)

| Business Unit | Métrica | Target |
|---|---|---|
| DeepAPI | Usuarios registrados | 50 |
| DeepAPI | Usuarios pagos | 5 ($50 MRR) |
| PriceGuard | Productos monitoreados | 500 |
| PriceGuard | Usuarios pagos | 3 ($90 MRR) |
| ViralBot | Seguidores Twitter | 500 |
| LeadGen | Leads vendidos | 2 ($198) |
| **TOTAL** | **MRR proyectado** | **$338** |
