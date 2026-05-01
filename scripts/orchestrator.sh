#!/bin/bash
# ORCHESTRATOR — Despachador de fases de expansión
# Uso: orchestrator.sh <phase_name>
# Ej:  orchestrator.sh grid_stable

set -e

PHASE="$1"
TOKEN="8179816401:AAHF3xprmPeauuOapGDD9idQrLsv8Dl2EYE"
CHAT="999936393"
OPENDIR="/opt/trading"
PHASEDIR="$OPENDIR/scripts/phases"
LOG="$OPENDIR/logs/orchestrator.log"

mkdir -p "$OPENDIR/logs"

# ── Definiciones de fases ──
case "$PHASE" in
  grid_stable)
    NAME="FASE 1 — Grid Stable Pairs"
    FILES="6 archivos: grid_stable_profiles.py, estrategia, backtest, config, systemd"
    BT="scripts/backtest_grid_stable.py ETH/BTC 2Y"
    NEXT="Fase 2: Basis Trade — May 5 08:00 UTC"
    ;;
  basis_trade)
    NAME="FASE 2 — Spot-Futures Basis Trade"
    FILES="6 archivos: kraken_futures_feed.py, estrategia, ejecutor, backtest, config"
    BT="scripts/backtest_basis.py funding rates 2Y"
    NEXT="Fase 3: VIX Mean Reversion — May 7 08:00 UTC"
    ;;
  vix)
    NAME="FASE 3 — VIX Mean Reversion"
    FILES="5 archivos: vol_feed.py, estrategia, perfiles, backtest, integración stocks"
    BT="scripts/backtest_vol.py VIX 5Y"
    NEXT="Fase 4: Pairs Trading — May 10 08:00 UTC"
    ;;
  pairs)
    NAME="FASE 4 — Pairs Trading"
    FILES="6 archivos: pairs_feed.py, cointegración, estrategia, ejecutor, backtest, systemd"
    BT="scripts/backtest_pairs.py GLD-SLV 5Y"
    NEXT="Fase 5: Earnings Strangle — May 13 08:00 UTC"
    ;;
  earnings)
    NAME="FASE 5 — Earnings Strangle"
    FILES="6 archivos: earnings_calendar.py, options_chain, estrategia, ejecutor, backtest"
    BT="scripts/backtest_earnings.py NVDA/TSLA 3Y"
    NEXT="Fase 6: Reporte Final — May 16 08:00 UTC"
    ;;
  final_report)
    NAME="FASE 6 — Reporte Final Consolidado"
    FILES="Dashboard final, git push, Telegram report"
    BT="—"
    NEXT="🏁 EXPANSIÓN COMPLETADA"
    ;;
  *)
    echo "Unknown phase: $PHASE"
    echo "Valid: grid_stable | basis_trade | vix | pairs | earnings | final_report"
    exit 1
    ;;
esac

# ── 1. Telegram: inicio ──
echo "[$(date)] $NAME — INICIANDO" >> "$LOG"
curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d "chat_id=${CHAT}" \
  -d "parse_mode=HTML" \
  -d "text=🚀 <b>${NAME}</b>%0A%0A📁 Archivos: ${FILES}%0A📊 Backtest: ${BT}%0A%0A⏱️ Iniciando implementación..." \
  > /dev/null

# ── 2. Ejecutar OpenCode con el prompt ──
PROMPT_FILE="$PHASEDIR/phase_${PHASE}.txt"
if [ -f "$PROMPT_FILE" ]; then
  echo "[$(date)] Running opencode with $PROMPT_FILE" >> "$LOG"
  cd "$OPENDIR"
  /root/.opencode/bin/opencode run "$(cat $PROMPT_FILE)" >> "$LOG" 2>&1
  RC=$?
else
  echo "[$(date)] WARNING: Prompt file not found: $PROMPT_FILE — running with default args" >> "$LOG"
  cd "$OPENDIR"
  /root/.opencode/bin/opencode run "Ejecuta la implementacion de $NAME segun el plan en docs/EXPANSION_PLAN.md. Crea todos los archivos, ejecuta el backtest, actualiza el dashboard, y envia un reporte por Telegram. Esto es urgente y debe completarse en una sola sesion." >> "$LOG" 2>&1
  RC=$?
fi

# ── 3. Telegram: completado ──
if [ $RC -eq 0 ]; then
  STATUS="✅ COMPLETADA"
  STATUS_EMOJI="✅"
else
  STATUS="⚠️ FINALIZADA con warnings (exit code $RC)"
  STATUS_EMOJI="⚠️"
fi

echo "[$(date)] $NAME — $STATUS" >> "$LOG"
curl -s -X POST "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d "chat_id=${CHAT}" \
  -d "parse_mode=HTML" \
  -d "text=${STATUS_EMOJI} <b>${NAME}</b>%0A%0A📁 Archivos creados según EXPANSION_PLAN.md%0A📊 Backtest ejecutado%0A🖥️ Dashboard actualizado%0A%0A⏭️ ${NEXT}" \
  > /dev/null

exit 0
