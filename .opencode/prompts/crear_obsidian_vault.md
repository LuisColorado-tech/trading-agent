@AGENTS.md @specs/SPEC_SYSTEM.md @specs/SPEC_TREND_MOMENTUM.md @specs/SPEC_STOCKS.md

Creá un vault de Obsidian para el sistema de trading Arthas. Necesito dos cosas:

## 1. Notas de agentes (una nota por agente activo)

Para cada agente (Trading, Stocks, Options, PolySnipe, Grid Stable, Pairs, VIX), creá una nota con esta estructura:

```markdown
# [[Agente]] — Estado: 🟢/🟡/🔴

## Servicio
- systemctl: `nombre-servicio`
- Entry point: `scripts/run_xxx.py`

## Pipeline de ejecución
1. Paso 1 → Paso 2 → ...

## Comandos de diagnóstico
```bash
# Ver estado
systemctl status nombre-servicio
# Ver trades
...
# Ver errores
journalctl -u nombre-servicio --since today | grep ERROR
```

## Parámetros clave
| Parámetro | Valor | No tocar sin Council |
|-----------|-------|---------------------|
| ...       | ...   | ...                 |

## Historial de fixes
| Fecha | Problema | Fix |
```

## 2. Manual de comandos

Una nota central `[[00 - Manual de Comandos]]` con TODOS los comandos organizados por categoría:
- Sistema: `systemctl status`, `journalctl`, `spec_check.py`
- Diagnóstico: `tm_pulse.py`, `spec_check.py --agent`, `trading_council.py`
- DB queries: sesiones, trades, portfolio
- Redis: halts, cooldowns, direction_guard
- Backtesting: comandos para cada estrategia

## 3. Prompt de sistema (para futuras sesiones de IA)

La nota `[[Prompt - Revisar Sistema]]` con el texto exacto que debo pegar en una nueva sesión de OpenCode para que la IA revise el sistema correctamente.

---

Usá links de Obsidian `[[doble corchete]]` para conectar notas entre sí. 
El vault debe ser autocontenido: si abro Obsidian en esta carpeta, puedo navegar entre agentes, specs y comandos sin salir.
