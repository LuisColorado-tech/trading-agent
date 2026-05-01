# PLAN DE EXPANSIÓN AUTOMATIZADO — 5 Líneas en 14 Días

> **Orquestador**: OpenCode v1.14.31 con `opencode run`
> **Triggers**: Cron jobs → Telegram aviso → OpenCode ejecuta
> **Meta**: 2% mensual compuesto entre todos los agentes

---

## Infraestructura de automatización

```
cron (horario UTC)
  │
  ├── Día 1, 08:00 → Telegram "🚀 Fase 1: Grid Stable Pairs"
  │                  + opencode run --phase grid_stable
  │
  ├── Día 3, 08:00 → Telegram "🚀 Fase 2: Basis Trade"
  │                  + opencode run --phase basis_trade
  │
  ├── Día 5, 08:00 → Telegram "🚀 Fase 3: VIX Mean Reversion"
  │                  + opencode run --phase vix
  │
  ├── Día 8, 08:00 → Telegram "🚀 Fase 4: Pairs Trading"
  │                  + opencode run --phase pairs
  │
  ├── Día 11, 08:00 → Telegram "🚀 Fase 5: Earnings Strangle"
  │                  + opencode run --phase earnings
  │
  └── Día 14, 08:00 → Telegram "📊 Reporte Final Consolidado"
                     + opencode run --phase final_report
```

## Cronograma comprimido (14 días)

| Día | Fecha | Hora UTC | Fase | Entregables |
|---|---|---|---|---|
| 1 | May 3 | 08:00 | Grid Stable Pairs | 6 archivos + backtest ETH/BTC 2Y + dashboard |
| 3 | May 5 | 08:00 | Basis Trade | 6 archivos + backtest funding rates 2Y + dashboard |
| 5 | May 7 | 08:00 | VIX Mean Reversion | 5 archivos + backtest VIX 5Y + dashboard |
| 8 | May 10 | 08:00 | Pairs Trading | 6 archivos + backtest cointegración 5Y + dashboard |
| 11 | May 13 | 08:00 | Earnings Strangle | 6 archivos + backtest earnings 3Y + dashboard |
| 14 | May 16 | 08:00 | Reporte Final | Dashboard consolidado + Telegram + git push |

---

## Mecanismo de ejecución

Cada trigger de cron ejecuta:

```bash
#!/bin/bash
# 1. Telegram: "🚀 Inicia Fase X"
curl -s -X POST "https://api.telegram.org/bot{TOKEN}/sendMessage" \
  -d "chat_id={CHAT}" \
  -d "text=🚀 <b>FASE X INICIADA</b>%0A%0AImplementando: [nombre]%0AArchivos a crear: [lista]%0ABacktest: [script]%0A%0A⏱️ Tiempo estimado: [X] minutos" \
  -d "parse_mode=HTML"

# 2. Ejecutar OpenCode con el prompt de la fase
cd /opt/trading
opencode run "$(cat /opt/trading/scripts/phases/phase_X_prompt.txt)"

# 3. Telegram: "✅ Fase X completada"  
curl -s -X POST "https://api.telegram.org/bot{TOKEN}/sendMessage" \
  -d "chat_id={CHAT}" \
  -d "text=✅ <b>FASE X COMPLETADA</b>%0A%0AArchivos creados: [count]%0ABacktest: [resultado]%0ADashboard: actualizado%0A%0APróxima fase: [nombre] — [fecha] 08:00 UTC" \
  -d "parse_mode=HTML"
```

---

## Archivos del orquestador

```
scripts/
  orchestrator.sh              ← Script maestro que despacha fases
  phases/
    phase_1_grid_stable.txt    ← Prompt detallado para OpenCode
    phase_2_basis_trade.txt
    phase_3_vix.txt
    phase_4_pairs.txt
    phase_5_earnings.txt
    phase_6_final_report.txt
```

## Cron entries

```cron
0 8 3 5 * /opt/trading/scripts/orchestrator.sh grid_stable
0 8 5 5 * /opt/trading/scripts/orchestrator.sh basis_trade
0 8 7 5 * /opt/trading/scripts/orchestrator.sh vix
0 8 10 5 * /opt/trading/scripts/orchestrator.sh pairs
0 8 13 5 * /opt/trading/scripts/orchestrator.sh earnings
0 8 16 5 * /opt/trading/scripts/orchestrator.sh final_report
```
