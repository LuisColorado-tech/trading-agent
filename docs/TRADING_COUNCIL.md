# TRADING COUNCIL — Comité de Asesores de Trading

> Sistema de debate multi-agente para decisiones de trading en Arthas.
> 4 perfiles profesionales analizan cada tema y emiten veredicto vinculante.

---

## Uso rápido

```bash
cd /opt/trading && venv/bin/python3 scripts/trading_council.py "¿tema a debatir?"
```

Ejemplos:
```bash
python3 scripts/trading_council.py "¿Bajar MIN_SCORE de 65 a 60?"
python3 scripts/trading_council.py "¿Activar BUY en TREND_UP?"
python3 scripts/trading_council.py "¿Agregar SOL al Grid Bot?"
python3 scripts/trading_council.py "¿Aumentar max_concurrent_trades de 3 a 5?"
```

## Miembros del comité

| Miembro | Rol | Expertise | Vota basado en |
|---|---|---|---|
| 🤖 **QUANT** | Quantitative Analyst | Estadística, backtesting, datos DB | Evidencia numérica |
| 📊 **TECHNICAL** | Technical Analyst | Estructura de mercado, charts | Análisis técnico |
| 🛡️ **RISK** | Risk Manager | Drawdown, halts, exposición | Preservación de capital |
| 💼 **PORTFOLIO** | Portfolio Manager | Roadmap, diversificación | Objetivo 3-meses live |

## Cómo funciona

1. **Contexto automático**: el script recolecta datos del sistema en vivo (balance, DD, TM stats, DirectionGuard, halts)
2. **Análisis por miembro**: cada perfil analiza el tema desde su expertise
3. **Votación**: cada miembro vota ✅ (aprueba), ❌ (rechaza), o ⚠️ (condicional)
4. **Veredicto**: mayoría simple (3/4) aprueba. 2-2 = rechazado.
5. **Acta**: se guarda en `/opt/trading/.council/session_YYYYMMDD_NNN.json`

## Reglas

- **Quorum**: 4 miembros (siempre completo)
- **Mayoría**: 3/4 para aprobar
- **Veto del Risk Manager**: si vota ❌, se requiere unanimidad 4/4
- **Condiciones**: voto ⚠️ debe especificar condiciones
- **Apelación**: solo con datos nuevos (mínimo 72h)

## Sesiones

### Sesión #1 — Mayo 21, 2026
**Tema**: Bajar gap EMA de 0.5% a 0.2% + confirmación MACD en trend_direction

**Resultado**: 4-0 APROBADO

**Acción**: Modificado `agents/indicators.py` — trend_direction ahora usa MACD como confirmación adicional cuando EMAs son ambiguas.

**Acta**: `.council/session_20260521_001.json`

---

### Sesión #2 — Mayo 21, 2026
**Tema**: Bajar _TREND_STRENGTH_MIN de 0.12 a 0.08

**Resultado**: 3-0-1 APROBADO (QUANT=✅, TECHNICAL=⚠️, RISK=✅, PORTFOLIO=✅)

**Acción**: Modificado `core/market_regime.py` — _TREND_STRENGTH_MIN = 0.12 → 0.08

**Condiciones**:
- Si DD > 15% → revertir ambos fixes
- DirectionGuard activo (ya lo está)
- Monitoreo 72h post-fix
- Si 7 días corridos WR < 35% → convocar council para re-evaluar

**Acta**: `.council/session_20260521_002.json`

---

## Revisar actas anteriores

```bash
ls /opt/trading/.council/
cat /opt/trading/.council/session_*.json | python3 -m json.tool
```

## Filosofía del comité

El council existe para **decisiones de parámetros y estrategia**, no para bugs ni emergencias. Si algo está roto (crash loop, halt, error de código), se arregla directo. Si es una decisión de calibración que afecta el rendimiento a mediano plazo, pasa por el comité.

**No convocar para**: bugs, crashes, halts, errores de sintaxis, fallas de API.
**Sí convocar para**: cambios de parámetros, activación/desactivación de estrategias, ajustes de riesgo, nuevas features.
