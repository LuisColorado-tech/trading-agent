#!/usr/bin/env python3
"""
Health Check — Watchdog del Trading Agent.
Verifica que el sistema funciona correctamente y envía alertas por Telegram.

Se ejecuta vía systemd timer cada 5 minutos.
Si detecta problemas, envía alerta inmediata.
Cada 6 horas envía un resumen de estado (heartbeat).

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
TELEGRAM_TOKEN = '8179816401:AAHF3xprmPeauuOapGDD9idQrLsv8Dl2EYE'
TELEGRAM_CHAT = '999936393'
STATE_FILE = Path('/opt/trading/.health_state.json')
HEARTBEAT_HOURS = 3
MAX_CYCLE_AGE_MIN = 5
MAX_DATA_AGE_MIN = 15
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


def send_telegram(message: str, silent: bool = False):
    """Envía mensaje por Telegram."""
    try:
        requests.post(
            f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage',
            json={
                'chat_id': TELEGRAM_CHAT,
                'text': message,
                'parse_mode': 'HTML',
                'disable_notification': silent,
            },
            timeout=10,
        )
    except Exception as e:
        print(f'[ERROR] Telegram send failed: {e}')


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


def check_log_errors() -> tuple:
    """Check 3: ¿Hay errores en los logs recientes?"""
    since = get_recent_journal_since(5)
    code, out = run_cmd(
        f'journalctl -u trading-agent.service --since "{since}" '
        '--no-pager -o cat 2>/dev/null | grep -ciE "ERROR|SyntaxError|Exception|Traceback"'
    )
    n = int(out) if out.isdigit() else 0
    if n == 0:
        return True, 'Sin errores en logs'
    # Obtener el último error
    _, last_err = run_cmd(
        f'journalctl -u trading-agent.service --since "{since}" '
        '--no-pager -o cat 2>/dev/null | grep -iE "ERROR|SyntaxError|Exception" | tail -1'
    )
    return False, f'{n} errores en 5 min. Último: {last_err[:200]}'


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
        r = requests.get('http://localhost:8501', timeout=5)
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


def check_polymarket() -> tuple:
    """Check del servicio Polymarket."""
    try:
        import subprocess
        r = subprocess.run(['systemctl', 'is-active', 'polymarket-agent'], capture_output=True, text=True, timeout=5)
        svc_active = r.stdout.strip() == 'active'
        if not svc_active:
            return False, '🔮 Polymarket servicio INACTIVO'

        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("SELECT session_name, current_balance, total_trades FROM poly_sessions WHERE status='ACTIVE' LIMIT 1")
        row = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM poly_positions WHERE status='OPEN'")
        open_c = cur.fetchone()[0]
        conn.close()

        if not row:
            return True, '🔮 Poly: sin sesión activa'
        return True, f'🔮 Poly: {row[0]} ${float(row[1]):,.2f} | {open_c} pos | {row[2]} trades'
    except Exception as e:
        return False, f'🔮 Poly error: {str(e)[:100]}'


def check_stocks() -> tuple:
    """Check del stocks agent (Alpaca NYSE/NASDAQ)."""
    try:
        import subprocess
        r = subprocess.run(['systemctl', 'is-active', 'stocks-agent'], capture_output=True, text=True, timeout=5)
        svc_active = r.stdout.strip() == 'active'
        if not svc_active:
            return False, '📈 Stocks servicio INACTIVO'

        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("SELECT session_name, current_balance, total_trades FROM stocks_sessions WHERE status='ACTIVE' LIMIT 1")
        row = cur.fetchone()
        cur.execute("SELECT COUNT(*) FROM stocks_trades WHERE status='OPEN'")
        open_c = cur.fetchone()[0]
        conn.close()

        if not row:
            return True, '📈 Stocks: sin sesión activa'
        return True, f'📈 Stocks: {row[0]} ${float(row[1]):,.2f} | {open_c} open | {row[2]} trades'
    except Exception as e:
        return False, f'📈 Stocks error: {str(e)[:100]}'


def _query_one(conn, sql: str, params=None):
    """Helper: ejecuta query y devuelve (None, ...) si falla."""
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        return cur.fetchone()
    except Exception:
        return None


def _build_heartbeat(now: datetime) -> str:
    """Construye heartbeat multi-agente en formato tabla compacta.

    Cubre: Crypto, Stocks, Polymarket, Options, BTC Direction.
    Checks de sistema van en alertas, no en el heartbeat.
    """
    lines = [f'💓 <b>ARTHAS — {now.strftime("%d %b %H:%M")} UTC</b>', '']

    # ── Queries para cada agente ──
    try:
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=5)
    except Exception:
        return '\n'.join(lines + ['❌ DB inaccesible'])

    # Crypto — scope a sesión activa
    crypto_sess = _query_one(conn,
        "SELECT session_name, initial_balance, started_at FROM paper_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1")
    if crypto_sess:
        cs_name, cs_init, cs_start = crypto_sess
        crypto_open = _query_one(conn,
            "SELECT COUNT(*) FROM trades WHERE status='OPEN' AND timestamp_open >= %s", (cs_start,))
        crypto_pnl = _query_one(conn,
            "SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE status='CLOSED' AND close_reason != 'SESSION_CLOSE' AND timestamp_open >= %s", (cs_start,))
        crypto_dd = _query_one(conn,
            "SELECT drawdown_pct FROM portfolio WHERE timestamp >= %s ORDER BY timestamp DESC LIMIT 1", (cs_start,))
    else:
        cs_name, cs_init = None, None
        crypto_open = crypto_pnl = crypto_dd = None

    # Stocks
    stocks = _query_one(conn,
        "SELECT session_name, current_balance FROM stocks_sessions WHERE status='ACTIVE' LIMIT 1")
    if stocks:
        stocks_open = _query_one(conn,
            "SELECT COUNT(*) FROM stocks_trades WHERE status='OPEN' AND session_id = (SELECT id FROM stocks_sessions WHERE status='ACTIVE' LIMIT 1)")
        stocks_pnl = _query_one(conn,
            "SELECT COALESCE(SUM(pnl), 0) FROM stocks_trades WHERE status='CLOSED' AND session_id = (SELECT id FROM stocks_sessions WHERE status='ACTIVE' LIMIT 1)")
    else:
        stocks_open = stocks_pnl = None

    # Polymarket
    poly = _query_one(conn,
        "SELECT session_name, current_balance FROM poly_sessions WHERE status='ACTIVE' LIMIT 1")
    if poly:
        poly_name = poly[0]
        poly_open = _query_one(conn,
            "SELECT COUNT(*) FROM poly_positions WHERE status='OPEN' AND session_name = %s", (poly_name,))
        poly_pnl = _query_one(conn,
            "SELECT COALESCE(SUM(pnl), 0) FROM poly_positions WHERE status='CLOSED' AND close_reason!='SESSION_RESET' AND session_name = %s", (poly_name,))
        poly_wr = _query_one(conn,
            "SELECT COUNT(*), SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) FROM poly_positions WHERE status='CLOSED' AND close_reason!='SESSION_RESET' AND session_name = %s", (poly_name,))
    else:
        poly_open = poly_pnl = poly_wr = None

    # Options
    options = _query_one(conn,
        "SELECT session_name, current_balance FROM options_sessions WHERE status='ACTIVE' LIMIT 1")
    if options:
        options_open = _query_one(conn,
            "SELECT COUNT(*) FROM options_positions WHERE status='OPEN'")
        options_pnl = _query_one(conn,
            "SELECT COALESCE(SUM(pnl_usd), 0) FROM options_positions WHERE status='CLOSED'")
    else:
        options_open = options_pnl = None

    # BTC Direction
    btcd = _query_one(conn,
        "SELECT COUNT(*), SUM(CASE WHEN pnl_usdc>0 THEN 1 ELSE 0 END), COALESCE(SUM(pnl_usdc),0) FROM btc_direction_trades WHERE status='CLOSED'")
    btcd_open = _query_one(conn, "SELECT COUNT(*) FROM btc_direction_trades WHERE status='OPEN'")

    conn.close()

    # ── Construir tabla ──
    def fmt(v, default='—'):
        if v is None or v == '': return default
        return v

    def row(icon, name, session, balance, n_open, pnl, extra=''):
        sn = str(session)[:10] if session else '—'
        bl = f'${float(balance):,.0f}' if balance is not None else '—'
        op = str(int(n_open)) if n_open is not None else '—'
        pn = f'${float(pnl):+,.0f}' if pnl is not None else '—'
        ext = f' {extra}' if extra else ''
        return f'{icon} <b>{name}</b>  {sn:10s}  {bl:>7s}  {op:>2s} open  {pn:>8s}{ext}'

    lines.append(row('💰', 'Crypto ', 
        cs_name if cs_name else '—',
        cs_init if cs_init else None,
        crypto_open[0] if crypto_open else 0,
        crypto_pnl[0] if crypto_pnl else 0))

    lines.append(row('📈', 'Stocks ',
        stocks[0] if stocks else '—',
        stocks[1] if stocks else None,
        stocks_open[0] if stocks_open else 0,
        stocks_pnl[0] if stocks_pnl else 0))

    lines.append(row('🔮', 'Poly   ',
        poly[0] if poly else '—',
        poly[1] if poly else None,
        poly_open[0] if poly_open else 0,
        poly_pnl[0] if poly_pnl else 0))

    lines.append(row('📣', 'Options',
        options[0] if options else '—',
        options[1] if options else None,
        options_open[0] if options_open else 0,
        options_pnl[0] if options_pnl else 0))

    btcd_t = int(btcd[0]) if btcd else 0
    btcd_w = int(btcd[1]) if btcd else 0
    btcd_wr = f'{btcd_w/btcd_t*100:.0f}%' if btcd_t > 0 else '—'
    btcd_pnl = float(btcd[2]) if btcd else 0
    lines.append(row('₿ ', 'BTC Dir',
        f'WR {btcd_wr}', None,
        btcd_open[0] if btcd_open else 0,
        btcd_pnl, f'({btcd_t}t)'))

    # ── Info extra ──
    lines.append('')
    extras = []
    if crypto_dd:
        dd_val = float(crypto_dd[0]) * 100 if crypto_dd[0] else 0
        icon_dd = '🟢' if dd_val < 5 else ('🟡' if dd_val < 8 else '🔴')
        extras.append(f'{icon_dd} DD: {dd_val:.1f}%')
    if poly_wr:
        pw_t, pw_w = int(poly_wr[0]), int(poly_wr[1])
        extras.append(f'Poly WR: {pw_w/pw_t*100:.0f}%' if pw_t > 0 else 'Poly WR: —')
    extras.append('v3: MIN_SCORE=75 | MAX_CONC=2 | trailing 0.75R')
    extras.append('Stocks v3: trailing ON | xsignal fix | macro gradient')
    lines.append('  '.join(extras))

    lines.append(f'\n⏱️ Próximo heartbeat: ~{HEARTBEAT_HOURS}h | Alertas: cada 5min si hay fallos')
    return '\n'.join(lines)
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
        ('🔮 Polymarket', check_polymarket),
        ('📈 Stocks', check_stocks),
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

    if send_heartbeat:
        send_telegram(_build_heartbeat(now), silent=all_ok)
        state['last_heartbeat'] = now.isoformat()

    save_state(state)

    # ── Salida para logs ──
    all_ok = all(ok for _, ok, _ in results)
    status = 'OK' if all_ok else 'FAIL'
    print(f'[{now.strftime("%H:%M:%S")}] Health check: {status} ({len(results)-len(failures)}/{len(results)} passed)')
    for name, ok, msg in results:
        print(f'  {"✓" if ok else "✗"} {name}: {msg}')

    sys.exit(0 if all_ok else 1)


if __name__ == '__main__':
    main()
