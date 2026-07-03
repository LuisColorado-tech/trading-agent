#!/usr/bin/env python3
"""
Health Check — Watchdog del Trading Agent.
Verifica que el sistema funciona correctamente y envía alertas por Telegram.

Se ejecuta vía systemd timer cada 5 minutos.
Si detecta problemas, envía alerta inmediata.
Cada 3 horas envía un resumen de estado (heartbeat).

Checks:
  1. Servicio trading-agent activo
  2. Ciclos completándose (no stale >5 min)
  3. Errores SQL/Python en logs recientes
  4. Conectividad a PostgreSQL
  5. Datos de mercado frescos (<15 min)
  6. Dashboard accesible
  7. Drawdown dentro de límites
  8. Trades abiertos coherentes
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import psycopg2
import requests
from dotenv import load_dotenv

load_dotenv('/opt/trading/config/.env')

# ── Config ──
TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8179816401:AAHF3xprmPeauuOapGDD9idQrLsv8Dl2EYE')
TELEGRAM_CHAT = os.getenv('TELEGRAM_CHAT_ID', '999936393')
# Fallback: token del bot Hermes (@kwok_hermes_ai_assistant_bot) si el principal está bloqueado
TELEGRAM_FALLBACK_TOKEN = os.getenv('TELEGRAM_FALLBACK_TOKEN', '8356550917:AAGGEkzg06Hrc3Hjb3Sa1jkGVDOdU_lYy2Q')
TELEGRAM_FALLBACK_CHAT = os.getenv('TELEGRAM_FALLBACK_CHAT_ID', '999936393')
STATE_FILE = Path('/opt/trading/.health_state.json')
HEARTBEAT_HOURS = 3
MAX_CYCLE_AGE_MIN = 5
MAX_DATA_AGE_MIN = 300  # Fase 5: 15→300 (4h candles, nueva vela cada 4h)
MAX_DRAWDOWN_WARN = 0.05
MAX_DRAWDOWN_CRIT = 0.10
FAILURE_ALERT_REPEAT_MIN = 30
RISK_HALT_ALERT_REPEAT_MIN = 180

DB_CONFIG = {
    'dbname': os.getenv('POSTGRES_DB', 'trading_agent'),
    'user': os.getenv('POSTGRES_USER', 'trading'),
    'password': os.getenv('POSTGRES_PASSWORD', 'Tr4d1ng_Ag3nt_2026!'),
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': os.getenv('POSTGRES_PORT', '5432'),
}


def _try_send(token: str, chat: str, message: str, silent: bool) -> bool:
    """Intenta enviar con un token. Retorna True si éxito."""
    try:
        r = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={
                'chat_id': chat,
                'text': message,
                'parse_mode': 'HTML',
                'disable_notification': silent,
            },
            timeout=10,
        )
        if r.status_code == 200:
            return True
        if r.status_code == 403:
            print(f'[WARN] Telegram token blocked (403) — trying fallback')
        else:
            print(f'[WARN] Telegram send failed: {r.status_code} {r.text[:100]}')
        return False
    except Exception as e:
        print(f'[ERROR] Telegram send exception: {e}')
        return False


def send_telegram(message: str, silent: bool = False):
    """Envía mensaje por Telegram con fallback automático al token de Hermes."""
    if _try_send(TELEGRAM_TOKEN, TELEGRAM_CHAT, message, silent):
        return
    if TELEGRAM_FALLBACK_TOKEN and TELEGRAM_FALLBACK_TOKEN != TELEGRAM_TOKEN:
        if _try_send(TELEGRAM_FALLBACK_TOKEN, TELEGRAM_FALLBACK_CHAT, message, silent):
            print('[INFO] Sent via Hermes fallback token')
            return
    print('[ERROR] All Telegram tokens failed')


def load_state() -> dict:
    """Carga estado previo del health check."""
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {'last_heartbeat': '', 'last_errors': [], 'consecutive_failures': 0}


def save_state(state: dict):
    """Guarda estado del health check."""
    STATE_FILE.write_text(json.dumps(state, default=str))


def run_cmd(cmd: str) -> tuple:
    """Ejecuta comando shell y devuelve (returncode, stdout)."""
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=15,
    )
    return result.returncode, result.stdout.strip()


def get_service_started_at() -> datetime | None:
    """Devuelve la hora de arranque del servicio si systemd la expone."""
    code, out = run_cmd('systemctl show -p ActiveEnterTimestamp --value trading-agent.service')
    if code != 0 or not out:
        return None
    try:
        return datetime.strptime(out, '%a %Y-%m-%d %H:%M:%S %Z').replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def get_recent_journal_since(minutes: int = 5) -> str:
    """Calcula la ventana efectiva para leer logs tras un restart limpio."""
    recent_floor = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    service_started_at = get_service_started_at()
    if service_started_at is not None:
        recent_floor = max(recent_floor, service_started_at)
    return recent_floor.strftime('%Y-%m-%d %H:%M:%S UTC')


def is_risk_halt_only(failures: list[tuple[str, str]]) -> bool:
    """Detecta si el único fallo actual es el halt por drawdown."""
    return (
        len(failures) == 1
        and failures[0][0] == '📉 Drawdown'
        and 'mantener halt' in failures[0][1].lower()
    )


def build_failure_signature(failures: list[tuple[str, str]]) -> str:
    """Genera una firma estable para deduplicar alertas repetidas."""
    return '|'.join(f'{name}:{msg}' for name, msg in failures)


def should_send_failure_alert(state: dict, failures: list[tuple[str, str]], now: datetime) -> bool:
    """Limita alertas repetidas del mismo problema."""
    signature = build_failure_signature(failures)
    last_signature = state.get('last_alert_signature')
    last_sent_at = state.get('last_alert_sent_at')

    if signature != last_signature or not last_sent_at:
        return True

    try:
        last_sent_dt = datetime.fromisoformat(last_sent_at)
    except (ValueError, TypeError):
        return True

    repeat_minutes = RISK_HALT_ALERT_REPEAT_MIN if is_risk_halt_only(failures) else FAILURE_ALERT_REPEAT_MIN
    elapsed_minutes = (now - last_sent_dt).total_seconds() / 60
    return elapsed_minutes >= repeat_minutes


def build_failure_alert(now: datetime, failures: list[tuple[str, str]], consecutive_failures: int) -> str:
    """Construye el mensaje de alerta según el tipo de fallo."""
    if is_risk_halt_only(failures):
        _, msg = failures[0]
        return '\n'.join([
            '🛑 <b>HALT DE RIESGO ACTIVO</b>',
            '',
            msg,
            'Servicio sano, operativa pausada por protección de capital.',
            f'⏱️ {now.strftime("%Y-%m-%d %H:%M UTC")}',
            f'Revisiones consecutivas en halt: {consecutive_failures}',
            f'Frecuencia de reaviso: cada {RISK_HALT_ALERT_REPEAT_MIN} min si no cambia el estado',
        ])

    alert_lines = ['🚨 <b>ALERTA Trading Agent</b>', '']
    for name, msg in failures:
        alert_lines.append(f'{name}: {msg}')
    alert_lines.append(f'')
    alert_lines.append(f'⏱️ {now.strftime("%Y-%m-%d %H:%M UTC")}')
    alert_lines.append(f'Fallos consecutivos: {consecutive_failures}')
    alert_lines.append(f'Reaviso si persiste: cada {FAILURE_ALERT_REPEAT_MIN} min')
    return '\n'.join(alert_lines)


def check_service_active() -> tuple:
    """Check 1: ¿El servicio está activo?"""
    code, out = run_cmd('systemctl is-active trading-agent.service')
    if code == 0 and out == 'active':
        return True, 'Servicio activo'
    return False, f'Servicio NO activo: {out}'


def check_recent_cycles() -> tuple:
    """Check 2: ¿Hay ciclos completados recientemente?"""
    since = get_recent_journal_since(MAX_CYCLE_AGE_MIN)
    code, out = run_cmd(
        f'journalctl -u trading-agent.service --since "{since}" '
        '--no-pager -o cat 2>/dev/null | grep -c "Cycle.*complete"'
    )
    n = int(out) if out.isdigit() else 0
    if n > 0:
        return True, f'{n} ciclos en últimos {MAX_CYCLE_AGE_MIN} min'
    return False, f'Sin ciclos completados en {MAX_CYCLE_AGE_MIN} min — posible crash loop'


AGENT_SERVICES = [
    'trading-agent',
    'grid-stable',
]


def check_log_errors() -> tuple:
    """Check 3: ¿Hay errores en los logs recientes de TODOS los agentes?"""
    since = get_recent_journal_since(5)
    total_errors = 0
    agent_errors = []
    # Ruido conocido: no necesita atencion
    NOISE = (
        'possibly delisted',
        'Yahoo error',
        'No data found, symbol may be delisted',
        'Temporary failure in name resolution',
        'NameResolutionError',
        'ConnectTimeoutError',
        'Max retries exceeded',
        'RemoteDisconnected',
        'Read timed out',
        'does not have market symbol',
    )
    noise_filter = ' | '.join(f'grep -v "{p}"' for p in NOISE)
    for svc in AGENT_SERVICES:
        code, out = run_cmd(
            f'journalctl -u {svc}.service --since "{since}" '
            f'--no-pager -o cat 2>/dev/null | grep -iE "ERROR|SyntaxError|Exception|Traceback" {noise_filter} | grep -ciE "ERROR|SyntaxError|Exception|Traceback"'
        )
        n = int(out) if out.isdigit() else 0
        if n > 0:
            total_errors += n
            # Obtener el último error de este agente
            _, last_err = run_cmd(
                f'journalctl -u {svc}.service --since "{since}" '
                '--no-pager -o cat 2>/dev/null | grep -iE "ERROR|SyntaxError|Exception" | tail -1'
            )
            agent_errors.append(f'{svc}:{n} errs')
    if total_errors == 0:
        return True, 'Sin errores en logs'
    err_summary = ', '.join(agent_errors)
    return False, f'{total_errors} errores en 5 min ({err_summary})'


def check_db_connection() -> tuple:
    """Check 4: ¿PostgreSQL accesible?"""
    try:
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=5)
        cur = conn.cursor()
        cur.execute('SELECT 1')
        conn.close()
        return True, 'DB accesible'
    except Exception as e:
        return False, f'DB inaccesible: {str(e)[:150]}'


def check_market_data_fresh() -> tuple:
    """Check 5: ¿Datos de mercado frescos?"""
    try:
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=5)
        cur = conn.cursor()
        cur.execute(
            "SELECT asset, MAX(timestamp) as latest FROM market_data "
            "GROUP BY asset ORDER BY latest DESC LIMIT 1"
        )
        row = cur.fetchone()
        conn.close()
        if not row:
            return False, 'Sin datos de mercado'
        asset, latest = row
        age = datetime.now(timezone.utc) - latest
        age_min = age.total_seconds() / 60
        if age_min <= MAX_DATA_AGE_MIN:
            return True, f'Datos frescos ({asset}: {age_min:.0f} min)'
        return False, f'Datos STALE: {asset} tiene {age_min:.0f} min de antigüedad (límite: {MAX_DATA_AGE_MIN})'
    except Exception as e:
        return False, f'Error al verificar datos: {str(e)[:150]}'


def check_dashboard() -> tuple:
    """Check 6: ¿Dashboard accesible?"""
    try:
        r = requests.get('http://localhost:3000', timeout=5)
        if r.status_code == 200:
            return True, 'Dashboard OK (HTTP 200)'
        return False, f'Dashboard HTTP {r.status_code}'
    except Exception as e:
        return False, f'Dashboard inaccesible: {str(e)[:100]}'


def check_drawdown() -> tuple:
    """Check 7: ¿Drawdown dentro de límites?"""
    try:
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=5)
        cur = conn.cursor()
        cur.execute(
            "SELECT started_at FROM paper_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1"
        )
        active_session = cur.fetchone()
        session_start = active_session[0] if active_session else None
        cur.execute(
            'SELECT total_balance, peak_balance, drawdown_pct '
            'FROM portfolio WHERE (%s IS NULL OR timestamp >= %s) '
            'ORDER BY timestamp DESC LIMIT 1',
            (session_start, session_start),
        )
        row = cur.fetchone()
        cur.execute(
            'SELECT COALESCE(MAX(GREATEST(total_balance, COALESCE(peak_balance, total_balance))), 0) '
            'FROM portfolio WHERE (%s IS NULL OR timestamp >= %s)',
            (session_start, session_start),
        )
        historical_peak = float(cur.fetchone()[0] or 0)
        conn.close()
        if not row:
            return True, 'Sin datos de portfolio'
        balance = float(row[0])
        peak = max(float(row[1]), historical_peak)
        dd = (peak - balance) / peak if peak > 0 else 0.0
        dd_pct = dd * 100
        if dd >= MAX_DRAWDOWN_CRIT:
            return False, (
                f'⚠️ DD CRÍTICO: {dd_pct:.1f}% '
                f'(balance ${balance:,.2f}, peak ${peak:,.2f}) → mantener halt'
            )
        if dd >= MAX_DRAWDOWN_WARN:
            return True, f'⚠️ DD elevado: {dd_pct:.1f}% (precaución)'
        return True, f'DD OK: {dd_pct:.1f}% (balance ${balance:,.2f})'
    except Exception as e:
        return False, f'Error verificando drawdown: {str(e)[:150]}'


def check_trades_coherent() -> tuple:
    """Check 8: ¿Trades abiertos tienen sentido?"""
    try:
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=5)
        cur = conn.cursor()
        cur.execute(
            "SELECT started_at FROM paper_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1"
        )
        active_session = cur.fetchone()
        session_start = active_session[0] if active_session else None
        cur.execute(
            "SELECT COUNT(*) FROM trades WHERE status='OPEN' AND (%s IS NULL OR timestamp_open >= %s)",
            (session_start, session_start),
        )
        n_open = cur.fetchone()[0]
        # Verificar que no hay trades OPEN sin SL
        cur.execute(
            "SELECT COUNT(*) FROM trades WHERE status='OPEN' AND stop_loss IS NULL "
            "AND (%s IS NULL OR timestamp_open >= %s)",
            (session_start, session_start),
        )
        n_no_sl = cur.fetchone()[0]
        conn.close()
        issues = []
        if n_no_sl > 0:
            issues.append(f'{n_no_sl} trades sin SL')
        if n_open > 8:
            issues.append(f'{n_open} trades abiertos (máx 8: 3 grid + 5 trend)')
        if issues:
            return False, f'Trades: {", ".join(issues)}'
        return True, f'{n_open} trades abiertos, todos con SL'
    except Exception as e:
        return False, f'Error verificando trades: {str(e)[:150]}'


def check_balance_stuck() -> tuple:
    """Check 9: ¿Balance lleva >24h sin cambiar? Indica bot paralizado por guard/halt."""
    try:
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=5)
        cur = conn.cursor()
        cur.execute(
            "SELECT started_at FROM paper_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1"
        )
        active_session = cur.fetchone()
        session_start = active_session[0] if active_session else None
        # Obtener balance más reciente y el de hace 24h
        cur.execute(
            'SELECT total_balance, timestamp FROM portfolio '
            'WHERE (%s IS NULL OR timestamp >= %s) ORDER BY timestamp DESC LIMIT 1',
            (session_start, session_start),
        )
        latest = cur.fetchone()
        if not latest:
            conn.close()
            return True, 'Sin datos de portfolio'
        cur.execute(
            "SELECT total_balance, timestamp FROM portfolio "
            "WHERE (%s IS NULL OR timestamp >= %s) AND timestamp <= NOW() - INTERVAL '24 hours' "
            "ORDER BY timestamp DESC LIMIT 1",
            (session_start, session_start),
        )
        old = cur.fetchone()
        # Contar trades cerrados en las últimas 24h
        cur.execute(
            "SELECT COUNT(*) FROM trades WHERE status='CLOSED' "
            "AND (%s IS NULL OR timestamp_open >= %s) "
            "AND timestamp_close >= NOW() - INTERVAL '24 hours'",
            (session_start, session_start),
        )
        recent_trades = cur.fetchone()[0]
        conn.close()

        if not old:
            return True, f'Sesión <24h activa, balance ${latest[0]:,.2f}'

        balance_diff = abs(float(latest[0]) - float(old[0]))
        if balance_diff < 0.01 and recent_trades == 0:
            return False, (
                f'⚠️ Balance ESTANCADO ${latest[0]:,.2f} por >24h sin trades. '
                f'Posible bloqueo por guard/halt.'
            )
        return True, f'Balance activo: ${latest[0]:,.2f} ({recent_trades} trades en 24h)'
    except Exception as e:
        return False, f'Error verificando balance: {str(e)[:150]}'


def check_grid_bot() -> tuple:
    """Check 10: Estado del Grid Bot — trades abiertos, PnL session y métricas clave."""
    try:
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=5)
        cur = conn.cursor()

        # Sesión activa
        cur.execute(
            "SELECT id, session_name, started_at, initial_balance "
            "FROM paper_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1"
        )
        active_session = cur.fetchone()
        if not active_session:
            conn.close()
            return True, '📊 Grid: sin sesión activa'

        session_id, session_name, started_at, initial_balance = active_session

        # Trades GRID_BOT abiertos ahora
        cur.execute(
            "SELECT asset, entry_price, stop_loss, take_profit "
            "FROM trades WHERE status='OPEN' AND strategy='GRID_BOT' "
            "AND timestamp_open >= %s",
            (started_at,),
        )
        open_trades = cur.fetchall()
        n_open = len(open_trades)
        open_assets = [r[0] for r in open_trades]

        # PnL acumulado GRID_BOT cerrados en la sesión
        cur.execute(
            "SELECT COUNT(*), "
            "COALESCE(SUM(pnl), 0) AS total_pnl, "
            "COALESCE(SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END), 0) AS wins "
            "FROM trades WHERE status='CLOSED' AND strategy='GRID_BOT' "
            "AND timestamp_open >= %s",
            (started_at,),
        )
        closed = cur.fetchone()
        conn.close()

        n_closed   = int(closed[0])
        total_pnl  = float(closed[1])
        n_wins     = int(closed[2])
        wr_pct     = (n_wins / n_closed * 100) if n_closed > 0 else 0.0

        assets_str = ','.join(sorted(set(open_assets))) if open_assets else 'ninguno'

        msg = (
            f'📊 Grid: {n_open}/3 abiertos [{assets_str}] | '
            f'{n_closed} cerrados WR={wr_pct:.0f}% PnL=${total_pnl:+.2f}'
        )
        # Alerta si se acerca al límite total sin trades
        if n_closed == 0 and n_open == 0:
            return True, f'📊 Grid: sin actividad aún en {session_name}'
        return True, msg
    except Exception as e:
        return False, f'📊 Grid error: {str(e)[:150]}'


def check_stocks() -> tuple:
    """Stocks agent cerrado (Jul 3, 2026). Backtest no mostro edge."""
    return True, '📈 Stocks CERRADO — sin edge en backtest (Capítulo cerrado)'


def check_options() -> tuple:
    """Check del options agent — DESACTIVADO por Council #9 (0-3-1)."""
    return True, '📣 Options DESACTIVADO — Council #9: -$613, DD 30.7%, BTC puts sin edge'


def check_pairs() -> tuple:
    """Check del Pairs Trading agent. Fase 4: detenido intencionalmente."""
    return True, '🔗 Pairs DETENIDO — no parte del test actual de cost model'


def check_snipe() -> tuple:
    """Check del PolyMarket SNIPE agent — DESACTIVADO por Council #7 (0-2-2)."""
    return True, '🎯 PolySnipe DESACTIVADO — Council #7: edge negativo (-$150 en 341 trades)'


def check_rsi_reversal() -> tuple:
    """Check del RSI Reversal — BUY oversold en TREND_UP (Council #12, 3-0-1)."""
    try:
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=5)
        row = _query_one(conn,
            "SELECT COUNT(*) FROM trades WHERE strategy='RSI_REVERSAL' AND timestamp_open > now() - interval '48 hours'")
        conn.close()
        count = int(row[0]) if row else 0
        if count == 0:
            return True, '🔄 RSI Reversal sin trades — esperando TREND_UP (régimen actual no permite BUY)'
        return True, f'🔄 RSI Reversal OK — {count} trades en 48h'
    except Exception as e:
        return False, f'🔄 RSI Reversal error: {str(e)[:80]}'


def _query_one(conn, sql: str, params=None):
    """Helper: ejecuta query y devuelve (None, ...) si falla."""
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        return cur.fetchone()
    except Exception:
        return None


def _pnl_and_wr(conn, table: str, where: str = '', pnl_col: str = 'pnl', params: tuple = ()):
    """Helper: retorna (trades, wins, pnl, wr_pct) para una estrategia."""
    base = f"FROM {table} WHERE status='CLOSED'"
    if where:
        base += f' AND {where}'
    row = _query_one(conn, f"SELECT COUNT(*) as t, SUM(CASE WHEN {pnl_col}>0 THEN 1 ELSE 0 END) as w, COALESCE(SUM({pnl_col}), 0) as pnl {base}", params)
    if not row:
        return 0, 0, 0.0, 0.0
    t, w, pnl = int(row[0] or 0), int(row[1] or 0), float(row[2] or 0)
    wr = (w / t * 100) if t > 0 else 0.0
    return t, w, pnl, wr


def _build_heartbeat(now: datetime) -> str:
    """Heartbeat multi-agente v2: 8 estrategias con balance real, PnL, WR, daily.

    Estructura:
      - Sección principal: tabla de 8 filas (estrategia | balance | trades | PnL | WR)
      - Sección extras: DD, daily PnL, parámetros activos
      - Footer: próximos heartbeats
    """
    lines = [f'💓 <b>ARTHAS TRADING — {now.strftime("%d %b %H:%M")} UTC</b>', '']

    try:
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=5)
    except Exception:
        return '\n'.join(lines + ['❌ DB inaccesible'])

    # ── 1. TrendMomentum (scope a sesión activa) ──
    tm_sess = _query_one(conn,
        "SELECT session_name, started_at FROM paper_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1")
    tm_open = 0; tm_pnl = 0.0; tm_wr = 0.0; tm_bal = 0.0; tm_dd = 0.0
    if tm_sess:
        tm_start = tm_sess[1]
        tm_open = int((_query_one(conn,
            "SELECT COUNT(*) FROM trades WHERE status='OPEN' AND strategy='TREND_MOMENTUM' AND timestamp_open >= %s", (tm_start,)) or [0])[0])
        _, _, tm_pnl, tm_wr = _pnl_and_wr(conn, 'trades',
            "strategy='TREND_MOMENTUM' AND close_reason != 'SESSION_CLOSE' AND timestamp_open >= %s", params=(tm_start,))
        pf_row = _query_one(conn, "SELECT total_balance, drawdown_pct FROM portfolio ORDER BY timestamp DESC LIMIT 1")
        tm_bal = float(pf_row[0]) if pf_row else 10000.0
        tm_dd = float(pf_row[1]) * 100 if pf_row and pf_row[1] else 0.0
    else:
        tm_sess = (None, None)

    # ── 2. Grid Bot ──
    gb_open_t = int((_query_one(conn,
        "SELECT COUNT(*) FROM trades WHERE status='OPEN' AND strategy='GRID_BOT'") or [0])[0])
    gb_t, gb_w, gb_pnl, gb_wr = _pnl_and_wr(conn, 'trades', "strategy='GRID_BOT'")

    # ── 3. Grid Stable ──
    gs_open = int((_query_one(conn,
        "SELECT COUNT(*) FROM trades WHERE status='OPEN' AND strategy='GRID_STABLE'") or [0])[0])
    gs_t, gs_w, gs_pnl, gs_wr = _pnl_and_wr(conn, 'trades', "strategy='GRID_STABLE'")
    gs_bal = round(500.0 + gs_pnl, 2)

    # ── 3b. RSI Reversal (Council #12, 3-0-1) ──
    rsi_t, rsi_w, rsi_pnl, rsi_wr = _pnl_and_wr(conn, 'trades', "strategy='RSI_REVERSAL'")
    rsi_open = int((_query_one(conn,
        "SELECT COUNT(*) FROM trades WHERE status='OPEN' AND strategy='RSI_REVERSAL'") or [0])[0])
    rsi_bal = round(500.0 + rsi_pnl, 2)

    # ── 4. Stocks ──
    stocks = _query_one(conn, "SELECT session_name, current_balance FROM stocks_sessions WHERE status='ACTIVE' LIMIT 1")
    st_open = 0; st_pnl = 0.0; st_wr = 0.0; st_bal = 220.0
    if stocks:
        st_bal = float(stocks[1]) if stocks[1] else 220.0
        st_open = int((_query_one(conn,
            "SELECT COUNT(*) FROM stocks_trades WHERE status='OPEN' AND session_id = (SELECT id FROM stocks_sessions WHERE status='ACTIVE' LIMIT 1)") or [0])[0])
        st_t, st_w, st_pnl, st_wr = _pnl_and_wr(conn, 'stocks_trades',
            "session_id = (SELECT id FROM stocks_sessions WHERE status='ACTIVE' LIMIT 1)")
    else:
        stocks = (None, None)

    # ── 5. Polymarket ──
    poly = _query_one(conn, "SELECT session_name, current_balance FROM poly_sessions WHERE status='ACTIVE' LIMIT 1")
    po_open = 0; po_pnl = 0.0; po_wr = 0.0; po_bal = 1000.0
    if poly:
        po_bal = float(poly[1]) if poly[1] else 1000.0
        po_open = int((_query_one(conn,
            "SELECT COUNT(*) FROM poly_positions WHERE status='OPEN' AND session_name = %s", (poly[0],)) or [0])[0])
        po_t, _, po_pnl, po_wr = _pnl_and_wr(conn, 'poly_positions',
            "close_reason!='SESSION_RESET' AND session_name = %s", params=(poly[0],))
    else:
        poly = (None, None)

    # ── 6. Options ──
    opt = _query_one(conn, "SELECT session_name, current_balance_usd FROM options_sessions WHERE status='ACTIVE' LIMIT 1")
    op_open = 0; op_pnl = 0.0; op_bal = 2000.0
    if opt:
        op_bal = float(opt[1]) if opt[1] else 2000.0
        op_open = int((_query_one(conn, "SELECT COUNT(*) FROM options_positions WHERE status='OPEN'") or [0])[0])
        op_row = _query_one(conn, "SELECT COALESCE(SUM(pnl_usd), 0) FROM options_positions WHERE status='CLOSED'")
        op_pnl = float(op_row[0]) if op_row else 0.0
    else:
        opt = (None, None)

    # ── 7. PolySnipe ──
    try:
        snipe_s = _query_one(conn, "SELECT session_name FROM snipe_sessions WHERE status='ACTIVE' LIMIT 1")
        sp_open = int((_query_one(conn, "SELECT COUNT(*) FROM snipe_trades WHERE status='OPEN'") or [0])[0])
        sp_t, sp_w, sp_pnl, sp_wr = _pnl_and_wr(conn, 'snipe_trades', pnl_col='pnl_usdc')
        sp_today = _query_one(conn,
            "SELECT COALESCE(SUM(pnl_usdc), 0) FROM snipe_trades WHERE status='CLOSED' AND timestamp_open::date = CURRENT_DATE")
        sp_daily = float(sp_today[0]) if sp_today else 0.0
        sp_bal = round(500.0 + sp_pnl, 2)
    except Exception:
        snipe_s = None; sp_open = 0; sp_pnl = 0.0; sp_wr = 0.0; sp_daily = 0.0; sp_bal = 500.0

    # ── 8. Daily PnL consolidado ──
    daily = _query_one(conn, """
        SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE status='CLOSED' AND timestamp_close >= CURRENT_DATE
    """)
    daily_pnl = float(daily[0]) if daily else 0.0

    conn.close()

    # ── Construir tabla ──
    def fmt_pnl(v):
        return f'${v:+,.0f}'
    def fmt_bal(v):
        return f'${v:,.0f}'

    header = f'{"Estrategia":<18s} {"Balance":>8s} {"Open":>4s} {"PnL":>9s} {"WR":>6s}'
    lines.append(f'<pre>{header}')

    rows_data = [
        ('💰 TrendMom', tm_bal, tm_open, tm_pnl, tm_wr),
        ('📊 GridBot ', tm_bal, gb_open_t, gb_pnl, gb_wr),
        ('📐 GridStab', gs_bal, gs_open, gs_pnl, gs_wr),
        ('🔄 RSI Rev ', rsi_bal, rsi_open, rsi_pnl, rsi_wr),
        ('📈 Stocks  ', st_bal, st_open, st_pnl, st_wr),
        ('🔮 Poly    ', po_bal, po_open, po_pnl, po_wr),
        ('📣 Options ', op_bal, op_open, op_pnl, 0.0),
        ('🎯 Snipe   ', sp_bal, sp_open, sp_pnl, sp_wr),
    ]

    for name, bal, opn, pnl, wr in rows_data:
        wr_str = f'{wr:.0f}%' if wr > 0 else '—'
        lines.append(f'{name} {fmt_bal(bal):>7s} {str(opn):>3s} {fmt_pnl(pnl):>8s} {wr_str:>5s}')
    lines.append('</pre>')

    # ── Extras ──
    lines.append('')
    extras = []

    # DD + daily
    dd_icon = '🟢' if tm_dd < 5 else ('🟡' if tm_dd < 8 else '🔴')
    extras.append(f'{dd_icon} DD: {tm_dd:.1f}%')
    extras.append(f'💵 Daily PnL: {fmt_pnl(daily_pnl)}')
    if sp_daily != 0:
        extras.append(f'🎯 Snipe today: {fmt_pnl(sp_daily)}')

    # Halt status
    import subprocess
    r = subprocess.run(['redis-cli', 'get', 'halt:trading'], capture_output=True, text=True, timeout=3)
    halt_val = r.stdout.strip() if r.returncode == 0 else ''
    if halt_val:
        extras.append(f'⚠️ HALT: {halt_val}')

    lines.append('  '.join(extras))
    lines.append(f'\n⏱️ Próximo heartbeat: ~{HEARTBEAT_HOURS}h | Alertas: cada 5min si hay fallos')

    # Proactive alerts (only in heartbeat, not every 5min check)
    alerts = _check_proactive_alerts(conn, now)
    if alerts:
        lines.append('\n⚠️ <b>Alertas:</b>')
        for a in alerts:
            lines.append(f'  • {a}')

    conn.close()
    return '\n'.join(lines)


def _is_nyse_open(now: datetime) -> bool:
    """NYSE opera L-V 14:30-21:00 UTC."""
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    hour = now.hour + now.minute / 60
    return 14.5 <= hour < 21.0


def _check_proactive_alerts(conn, now) -> list[str]:
    """Alertas proactivas: solo anomalías reales, no falsos positivos."""
    alerts = []
    try:
        # 1. Solo alertar agentes de alta frecuencia si no operan
        for name, tbl, ts_col in [
            ('TrendMomentum', 'trades', 'timestamp_close'),
            ('Grid Bot', 'trades', 'timestamp_close'),
        ]:
            cur = conn.cursor()
            cur.execute(f"SELECT COUNT(*) FROM {tbl} WHERE {ts_col} >= NOW() - INTERVAL '24 hours'")
            n = int((cur.fetchone() or [0])[0])
            if n == 0:
                alerts.append(f'⏸️ {name}: 0 trades en 24h (anómalo)')

        # 2. Stocks: solo alertar si NYSE está abierto
        if _is_nyse_open(now):
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM stocks_trades WHERE closed_at >= NOW() - INTERVAL '24 hours'")
            n = int((cur.fetchone() or [0])[0])
            if n == 0:
                alerts.append('⏸️ Stocks: 0 trades en 24h con NYSE abierto (anómalo)')

        # 3. DD diario > 3%
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE timestamp_close::date = CURRENT_DATE")
        daily = float((cur.fetchone() or [0])[0])
        cur.execute("SELECT total_balance FROM portfolio ORDER BY timestamp DESC LIMIT 1")
        bal = float((cur.fetchone() or [0])[0] or 10000)
        if daily < 0 and abs(daily) / bal > 0.03:
            alerts.append(f'📉 DD diario ${daily:+.0f} ({daily/bal*100:.1f}%) — supera 3%')

        # 4. Halt activo
        import subprocess
        r = subprocess.run(['redis-cli', 'get', 'halt:trading'], capture_output=True, text=True, timeout=3)
        halt_val = r.stdout.strip() if r.returncode == 0 else ''
        if halt_val and halt_val != '0':
            alerts.append(f'⚠️ HALT activo: {halt_val}')

    except Exception:
        pass
    return alerts
    return alerts


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--test-heartbeat', action='store_true',
                        help='Forzar envío inmediato de heartbeat a Telegram (ignora intervalo)')
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    state = load_state()

    checks = [
        ('🔧 Servicio', check_service_active),
        ('🔄 Ciclos', check_recent_cycles),
        ('📋 Logs', check_log_errors),
        ('🗄️ Base de datos', check_db_connection),
        ('📡 Datos mercado', check_market_data_fresh),
        ('📊 Dashboard', check_dashboard),
        ('📉 Drawdown', check_drawdown),
        ('💹 Trades', check_trades_coherent),
        ('🔒 Balance', check_balance_stuck),
        ('🤖 Grid Bot', check_grid_bot),
        ('🔄 RSI Reversal', check_rsi_reversal),
        ('🎯 PolySnipe', check_snipe),
        ('📈 Stocks', check_stocks),
        ('📣 Options', check_options),
        ('🔗 Pairs', check_pairs),
    ]

    results = []
    failures = []
    for name, check_fn in checks:
        try:
            ok, msg = check_fn()
        except Exception as e:
            ok, msg = False, f'Check crashed: {str(e)[:100]}'
        results.append((name, ok, msg))
        if not ok:
            failures.append((name, msg))

    all_ok = all(ok for _, ok, _ in results)

    # ── Alertas por fallos ──
    if failures:
        state['consecutive_failures'] = state.get('consecutive_failures', 0) + 1
        if should_send_failure_alert(state, failures, now):
            send_telegram(build_failure_alert(now, failures, state['consecutive_failures']))
            state['last_alert_sent_at'] = now.isoformat()
            state['last_alert_signature'] = build_failure_signature(failures)
        state['last_errors'] = [{'name': n, 'msg': m, 'ts': now.isoformat()} for n, m in failures]
    else:
        # Resetear contador si todo OK
        if state.get('consecutive_failures', 0) > 0:
            send_telegram(
                f'✅ <b>Sistema recuperado</b>\n'
                f'Todos los checks OK tras {state["consecutive_failures"]} fallos.\n'
                f'⏱️ {now.strftime("%Y-%m-%d %H:%M UTC")}'
            )
        state['consecutive_failures'] = 0
        state['last_alert_sent_at'] = ''
        state['last_alert_signature'] = ''

    # ── Heartbeat periódico ──
    last_hb = state.get('last_heartbeat', '')
    send_heartbeat = False
    if not last_hb:
        send_heartbeat = True
    else:
        try:
            last_hb_dt = datetime.fromisoformat(last_hb)
            if (now - last_hb_dt).total_seconds() >= HEARTBEAT_HOURS * 3600:
                send_heartbeat = True
        except (ValueError, TypeError):
            send_heartbeat = True

    if args.test_heartbeat:
        print('[HEARTBEAT] --test-heartbeat: forzando envío inmediato...')
        send_telegram(_build_heartbeat(now), silent=False)
        state['last_heartbeat'] = now.isoformat()
    elif send_heartbeat:
        print(f'[HEARTBEAT] Enviando heartbeat (silent={all_ok})...')
        send_telegram(_build_heartbeat(now), silent=all_ok)
        state['last_heartbeat'] = now.isoformat()
    else:
        next_hb = ''
        if last_hb:
            try:
                next_hb_dt = datetime.fromisoformat(last_hb) + timedelta(hours=HEARTBEAT_HOURS)
                next_hb = f' (próximo ~{next_hb_dt.strftime("%H:%M UTC")})'
            except (ValueError, TypeError):
                pass
        print(f'[HEARTBEAT] Suprimido — no han pasado {HEARTBEAT_HOURS}h{next_hb}')

    save_state(state)

    # ── Salida para logs ──
    status = 'OK' if all_ok else 'FAIL'
    print(f'[{now.strftime("%H:%M:%S")}] Health check: {status} ({len(results)-len(failures)}/{len(results)} passed)')
    for name, ok, msg in results:
        print(f'  {"✓" if ok else "✗"} {name}: {msg}')

    sys.exit(0 if all_ok else 1)


if __name__ == '__main__':
    main()
