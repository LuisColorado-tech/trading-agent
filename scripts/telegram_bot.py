"""
telegram_bot.py — Bot de Telegram interactivo para Arthas Trading Agent.

Escucha comandos del usuario en Telegram y responde con datos en tiempo real
desde la base de datos o ejecutando comandos de arthas_trading.py.

Comandos disponibles: /status /all /crypto /stocks /poly /options /grid /btc
                      /trades /portfolio /signals /prices /scan /report
                      /commands /help /ayuda /comandos

Ejecutar: python3 scripts/telegram_bot.py (o como servicio systemd)
"""
import io
import os
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta

import psycopg2
import requests
from loguru import logger
from openai import OpenAI

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv

load_dotenv('/opt/trading/config/.env')

_deepseek_key = os.getenv('DEEPSEEK_API_KEY') or os.getenv('OPENAI_API_KEY')
_openai_client = OpenAI(
    api_key=_deepseek_key,
    base_url='https://api.deepseek.com',
)

DB_CONFIG = {
    'dbname': os.getenv('POSTGRES_DB', 'trading_agent'),
    'user': os.getenv('POSTGRES_USER', 'trading'),
    'password': os.getenv('POSTGRES_PASSWORD', 'Tr4d1ng_Ag3nt_2026!'),
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': os.getenv('POSTGRES_PORT', '5432'),
}

# Historial de conversación por chat_id (máx. 20 turnos en memoria)
_conversation_history: dict = {}
_MAX_HISTORY = 20

ARTHAS_SYSTEM_PROMPT = """Eres Arthas, el asistente de trading y finanzas personales de Lucho (Luis Colorado).

Tu personalidad:
- Directo y conciso. Sin rodeos.
- Paisa colombiano cultivado: mezclás el rigor técnico con expresiones naturales.
- Conocés en profundidad cripto, trading algorítmico, Polymarket y estrategias quant.
- Sos el co-piloto de Lucho en todas sus operaciones e ideas de negocio.
- Cuando no sabés algo, lo decís sin drama. Nunca inventás datos.
- Podés hablar de cualquier tema: finanzas, código, vida, ideas — sos su asistente integral.

Contexto del sistema:
- Estás corriendo en un servidor Linux con un trading agent en /opt/trading.
- Hay una paper session activa con $10,000 de capital.
- El sistema opera 7 agentes: Crypto, Stocks, Polymarket, PolySnipe, Options, Grid Bot y Grid Stable.
- Si Lucho pregunta por datos frescos, decile que use comandos:
  /status o /all → todos los agentes | /crypto | /stocks | /poly | /snipe | /options | /grid
  /trades /portfolio /signals /prices /scan /report
  /commands → lista completa de comandos

Respondé siempre en español (castellano colombiano natural, no exagerés el paisa)."""

logger.add(
    '/opt/trading/logs/telegram_bot_{time}.log',
    rotation='1 day',
    retention='14 days',
    level='INFO',
)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8179816401:AAHF3xprmPeauuOapGDD9idQrLsv8Dl2EYE')
TELEGRAM_CHAT_ID = int(os.getenv('TELEGRAM_CHAT_ID', '999936393'))
API = f'https://api.telegram.org/bot{TELEGRAM_TOKEN}'

# ── COMMAND MAP ────────────────────────────────────────────────────────────────
# Comandos con /  →  handler interno
COMMAND_MAP = {
    # Multi-agente (todos juntos)
    '/status': '__all_status__',
    '/all': '__all_status__',
    # Individuales por agente
    '/crypto': '__crypto_status__',
    '/stocks': '__stocks_detail__',
    '/stocks_status': '__stocks_detail__',
    '/poly': '__poly_detail__',
    '/poly_status': '__poly_detail__',
    '/polystatus': '__poly_detail__',
    '/polyreport': '__poly_detail__',
    '/options': '__options_detail__',
    '/opciones': '__options_detail__',
    '/grid': '__grid_detail__',
    '/btc': '__btc_detail__',
    '/btcdirection': '__btc_detail__',
    '/snipe': '__snipe_detail__',
    '/snipe_status': '__snipe_detail__',
    '/polysnipe': '__snipe_detail__',
    # Comandos originales de arthas_trading.py
    '/portfolio': 'portfolio',
    '/trades': 'trades',
    '/signals': 'signals',
    '/prices': 'prices',
    '/metrics': 'metrics',
    '/scan': 'scan',
    '/report': 'report',
    # Ayuda
    '/help': '__commands_help__',
    '/commands': '__commands_help__',
    '/comandos': '__commands_help__',
    '/ayuda': '__commands_help__',
    # Sin / también (mismos handlers)
    'status': '__all_status__',
    'all': '__all_status__',
    'crypto': '__crypto_status__',
    'stocks': '__stocks_detail__',
    'stocks_status': '__stocks_detail__',
    'poly': '__poly_detail__',
    'poly_status': '__poly_detail__',
    'polystatus': '__poly_detail__',
    'polyreport': '__poly_detail__',
    'options': '__options_detail__',
    'opciones': '__options_detail__',
    'grid': '__grid_detail__',
    'btc': '__btc_detail__',
    'btcdirection': '__btc_detail__',
    'portfolio': 'portfolio',
    'trades': 'trades',
    'signals': 'signals',
    'prices': 'prices',
    'metrics': 'metrics',
    'scan': 'scan',
    'report': 'report',
    'help': '__commands_help__',
    'commands': '__commands_help__',
    'comandos': '__commands_help__',
    'ayuda': '__commands_help__',
}


def send_message(text: str, chat_id: int = TELEGRAM_CHAT_ID):
    """Envía mensaje por Telegram, dividiendo si es muy largo."""
    MAX_LEN = 4000
    chunks = []
    while len(text) > MAX_LEN:
        cut = text[:MAX_LEN].rfind('\n')
        if cut == -1:
            cut = MAX_LEN
        chunks.append(text[:cut])
        text = text[cut:].lstrip('\n')
    chunks.append(text)

    for chunk in chunks:
        if not chunk.strip():
            continue
        try:
            r = requests.post(
                f'{API}/sendMessage',
                json={'chat_id': chat_id, 'text': chunk},
                timeout=10,
            )
            if not r.json().get('ok'):
                logger.error(f'Telegram send failed: {r.json()}')
            else:
                logger.info(f'Mensaje enviado OK ({len(chunk)} chars)')
        except Exception as e:
            logger.error(f'Error enviando mensaje: {e}')


def run_arthas_command(command: str) -> str:
    """Ejecuta un comando de arthas_trading.py y devuelve la salida."""
    try:
        result = subprocess.run(
            ['/opt/trading/venv/bin/python3', '/opt/trading/scripts/arthas_trading.py', command],
            capture_output=True,
            text=True,
            timeout=60,
            cwd='/opt/trading',
        )
        output = result.stdout
        if result.stderr:
            output += f'\n⚠️ {result.stderr[-200:]}'
        return output.strip() if output.strip() else '(sin salida)'
    except subprocess.TimeoutExpired:
        return '⏰ Comando excedió el tiempo límite (60s)'
    except Exception as e:
        return f'❌ Error ejecutando comando: {e}'


# ── DB Helpers ─────────────────────────────────────────────────────────────────

def _query_one(conn, sql: str, params=None):
    """Helper: ejecuta query y devuelve fetchone o None si falla."""
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        return cur.fetchone()
    except Exception:
        return None


def _query_all(conn, sql: str, params=None):
    """Helper: ejecuta query y devuelve fetchall o [] si falla."""
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        return cur.fetchall()
    except Exception:
        return []


def _f(v, default='—'):
    """Formatea un valor: None/vacío → default."""
    if v is None or v == '':
        return default
    return v


# ── Status Builders ────────────────────────────────────────────────────────────

def build_commands_help() -> str:
    """Devuelve la tabla de comandos disponibles."""
    return '\n'.join([
        '⚔️ <b>ARTHAS — Comandos Disponibles</b>',
        '',
        '── <b>Multi-Agente</b> ──',
        '/status · /all          Estado de TODOS los agentes',
        '',
        '── <b>Por Agente</b> ──',
        '/crypto                 Crypto (BTC/ETH/SOL/XAU/XAG)',
        '/stocks                 Stocks (NYSE/NASDAQ vía Alpaca)',
        '/poly                   Polymarket (predicciones)',
        '/snipe                  PolySnipe — SNIPE+ARB Up/Down 15m',
        '/options                Options (Deribit theta farming)',
        '/grid                   Grid Bot (stable pairs)',
        '/btc                    BTC Direction (DEPRECATED)',
        '',
        '── <b>Detalle</b> ──',
        '/portfolio              Historial de snapshots del portfolio',
        '/trades                 Trades abiertos y últimos cerrados',
        '/signals                Últimas 15 señales del scanner',
        '/prices                 Precios actuales (BTC/ETH/SOL)',
        '/metrics                Métricas de paper trading',
        '/scan                   Forzar un escaneo de mercado ya',
        '/report                 Reporte completo (todo junto)',
        '',
        '── <b>Ayuda</b> ──',
        '/help · /commands       Esta tabla de comandos',
        '/ayuda · /comandos      Lo mismo en español',
        '',
        '💬 Si escribís cualquier otra cosa, Arthas (LLM) te responde.',
    ])


def build_all_agents_status() -> str:
    """Construye el status multi-agente consultando la DB directamente."""
    now = datetime.now(timezone.utc)
    lines = [f'⚔️ <b>ARTHAS — {now.strftime("%d %b %H:%M")} UTC</b>', '']

    try:
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=5)
    except Exception:
        return '\n'.join(lines + ['❌ Base de datos inaccesible'])

    # ── Crypto ──
    cs = _query_one(conn,
        "SELECT session_name, initial_balance, started_at "
        "FROM paper_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1")
    if cs:
        cs_name, cs_init, cs_start = cs
        cs_open = _query_one(conn,
            "SELECT COUNT(*) FROM trades WHERE status='OPEN' "
            "AND timestamp_open >= %s", (cs_start,))
        cs_pnl = _query_one(conn,
            "SELECT COALESCE(SUM(pnl), 0) FROM trades WHERE status='CLOSED' "
            "AND close_reason != 'SESSION_CLOSE' AND timestamp_open >= %s", (cs_start,))
        cs_dd = _query_one(conn,
            "SELECT drawdown_pct FROM portfolio WHERE timestamp >= %s "
            "ORDER BY timestamp DESC LIMIT 1", (cs_start,))
        cs_latest_bal = _query_one(conn,
            "SELECT total_balance FROM portfolio WHERE timestamp >= %s "
            "ORDER BY timestamp DESC LIMIT 1", (cs_start,))
    else:
        cs_name = cs_init = cs_start = None
        cs_open = cs_pnl = cs_dd = cs_latest_bal = None

    # ── Stocks ──
    stocks_sess = _query_one(conn,
        "SELECT session_name, current_balance, total_trades "
        "FROM stocks_sessions WHERE status='ACTIVE' LIMIT 1")
    if stocks_sess:
        stocks_open = _query_one(conn,
            "SELECT COUNT(*) FROM stocks_trades WHERE status='OPEN' "
            "AND session_id=(SELECT id FROM stocks_sessions WHERE status='ACTIVE' LIMIT 1)")
        stocks_pnl = _query_one(conn,
            "SELECT COALESCE(SUM(pnl), 0) FROM stocks_trades WHERE status='CLOSED' "
            "AND session_id=(SELECT id FROM stocks_sessions WHERE status='ACTIVE' LIMIT 1)")
    else:
        stocks_open = stocks_pnl = None

    # ── Polymarket ──
    poly_sess = _query_one(conn,
        "SELECT session_name, current_balance, total_trades "
        "FROM poly_sessions WHERE status='ACTIVE' LIMIT 1")
    if poly_sess:
        poly_name = poly_sess[0]
        poly_open = _query_one(conn,
            "SELECT COUNT(*) FROM poly_positions WHERE status='OPEN' "
            "AND session_name = %s", (poly_name,))
        poly_pnl = _query_one(conn,
            "SELECT COALESCE(SUM(pnl), 0) FROM poly_positions WHERE status='CLOSED' "
            "AND close_reason != 'SESSION_RESET' AND session_name = %s", (poly_name,))
        poly_wr = _query_one(conn,
            "SELECT COUNT(*), SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) "
            "FROM poly_positions WHERE status='CLOSED' "
            "AND close_reason != 'SESSION_RESET' AND session_name = %s", (poly_name,))
    else:
        poly_open = poly_pnl = poly_wr = poly_name = None

    # ── Options ──
    opt_sess = _query_one(conn,
        "SELECT session_name, current_balance, total_trades "
        "FROM options_sessions WHERE status='ACTIVE' LIMIT 1")
    if opt_sess:
        opt_open = _query_one(conn,
            "SELECT COUNT(*) FROM options_positions WHERE status='OPEN' "
            "AND session_name = %s", (opt_sess[0],))
        opt_pnl = _query_one(conn,
            "SELECT COALESCE(SUM(pnl_usd), 0) FROM options_positions "
            "WHERE status='CLOSED'")
    else:
        opt_open = opt_pnl = None

    # ── Grid Bot ──
    if cs_start:
        grid_trades = _query_all(conn,
            "SELECT COUNT(*), COALESCE(SUM(pnl), 0) FROM trades "
            "WHERE status='CLOSED' AND strategy='GRID_BOT' "
            "AND timestamp_open >= %s", (cs_start,))
        grid_open = _query_one(conn,
            "SELECT COUNT(*) FROM trades WHERE status='OPEN' "
            "AND strategy='GRID_BOT' AND timestamp_open >= %s", (cs_start,))
        grid_wins = _query_one(conn,
            "SELECT SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) FROM trades "
            "WHERE status='CLOSED' AND strategy='GRID_BOT' "
            "AND timestamp_open >= %s", (cs_start,))
    else:
        grid_trades = grid_open = grid_wins = None

    # ── PolyMarket SNIPE ──
    try:
        snipe_sess = _query_one(conn,
            "SELECT session_name, current_balance, total_trades "
            "FROM snipe_sessions WHERE status='ACTIVE' LIMIT 1")
        if snipe_sess:
            snipe_open = _query_one(conn,
                "SELECT COUNT(*) FROM snipe_trades WHERE status='OPEN'")
            snipe_pnl = _query_one(conn,
                "SELECT COALESCE(SUM(pnl_usdc), 0) FROM snipe_trades WHERE status='CLOSED'")
            snipe_wr_data = _query_one(conn,
                "SELECT COUNT(*), SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END) "
                "FROM snipe_trades WHERE status='CLOSED'")
        else:
            snipe_open = snipe_pnl = snipe_wr_data = None
    except Exception:
        snipe_sess = snipe_open = snipe_pnl = snipe_wr_data = None

    # ── BTC Direction (DEPRECATED) ──
    btcd_sess = _query_one(conn,
        "SELECT COUNT(*) FROM btc_direction_trades")
    btcd_wins = _query_one(conn,
        "SELECT SUM(CASE WHEN pnl_usdc>0 THEN 1 ELSE 0 END), "
        "COALESCE(SUM(pnl_usdc), 0) FROM btc_direction_trades "
        "WHERE status='CLOSED'")
    btcd_open = _query_one(conn,
        "SELECT COUNT(*) FROM btc_direction_trades WHERE status='OPEN'")

    conn.close()

    # ── Formatear tabla ──
    def row(emoji, name, session, balance, n_open, pnl, extra=''):
        sn = str(session)[:12] if session else '—'
        bl = f'${float(balance):,.0f}' if balance is not None else '—'
        op = str(int(n_open)) if n_open is not None else '—'
        pn_str = f'${float(pnl):+,.0f}' if pnl is not None else '—'
        ext_str = f'  {extra}' if extra else ''
        return f'{emoji} <b>{name}</b>  {sn:12s}  {bl:>8s}  {op:>2s} open  {pn_str:>8s}{ext_str}'

    # Crypto
    crypto_extra = ''
    if cs_dd:
        dd_pct = float(cs_dd[0]) * 100 if cs_dd[0] else 0
        icon = '🟢' if dd_pct < 5 else ('🟡' if dd_pct < 8 else '🔴')
        crypto_extra = f'{icon} DD {dd_pct:.1f}%'
    lines.append(row('💰', 'Crypto', _f(cs_name), cs_init,
                     cs_open[0] if cs_open else 0,
                     cs_pnl[0] if cs_pnl else 0,
                     crypto_extra))

    # Stocks
    lines.append(row('📈', 'Stocks', _f(stocks_sess[0] if stocks_sess else None),
                     stocks_sess[1] if stocks_sess else None,
                     stocks_open[0] if stocks_open else 0,
                     stocks_pnl[0] if stocks_pnl else 0))

    # Polymarket
    poly_extra = ''
    if poly_wr:
        pt, pw = int(poly_wr[0]), int(poly_wr[1])
        poly_extra = f'WR {pw/pt*100:.0f}%' if pt > 0 else ''
    lines.append(row('🔮', 'Poly', _f(poly_sess[0] if poly_sess else None),
                     poly_sess[1] if poly_sess else None,
                     poly_open[0] if poly_open else 0,
                     poly_pnl[0] if poly_pnl else 0,
                     poly_extra))

    # Options
    lines.append(row('📣', 'Options', _f(opt_sess[0] if opt_sess else None),
                     opt_sess[1] if opt_sess else None,
                     opt_open[0] if opt_open else 0,
                     opt_pnl[0] if opt_pnl else 0))

    # Grid Bot
    grid_extra = ''
    if grid_trades:
        gt = int(grid_trades[0][0])
        gw = int(grid_wins[0]) if grid_wins and grid_wins[0] else 0
        grid_extra = f'{gt}t WR {gw/gt*100:.0f}%' if gt > 0 else '—'
    lines.append(row('🤖', 'Grid Bot', '—', None,
                     grid_open[0] if grid_open else 0,
                     float(grid_trades[0][1]) if grid_trades else 0,
                     grid_extra))

    # PolyMarket SNIPE
    snipe_extra = ''
    if snipe_wr_data:
        st, sw = int(snipe_wr_data[0]), int(snipe_wr_data[1])
        snipe_extra = f'{st}t WR {sw/st*100:.0f}%' if st > 0 else '—'
    lines.append(row('🎯', 'SNIPE', _f(snipe_sess[0] if snipe_sess else None),
                     snipe_sess[1] if snipe_sess else None,
                     snipe_open[0] if snipe_open else 0,
                     snipe_pnl[0] if snipe_pnl else 0,
                     snipe_extra))

    # BTC Direction (DEPRECATED)
    btcd_extra = f'⚠️ REEMPLAZADO — usa /snipe'
    lines.append(row('₿', 'BTC Dir', '—', None,
                     btcd_open[0] if btcd_open else 0,
                     float(btcd_wins[1]) if btcd_wins and btcd_wins[1] else 0,
                     btcd_extra))

    # ── Pie ──
    lines.append('')
    total_dd = f' DD {float(cs_dd[0])*100:.1f}%' if cs_dd and cs_dd[0] else ''
    lines.append(f'⏱️ Próxima actualización: ~3h (heartbeat) | Servidor: {now.strftime("%H:%M UTC")}')
    lines.append('Usá /commands para ver todos los comandos.')

    return '\n'.join(lines)


def build_agent_detail(agent_type: str) -> str:
    """Detalle individual de un agente desde la DB."""
    try:
        conn = psycopg2.connect(**DB_CONFIG, connect_timeout=5)
    except Exception:
        return '❌ Base de datos inaccesible'

    if agent_type == 'stocks':
        return _build_stocks_detail(conn)
    elif agent_type == 'poly':
        return _build_poly_detail(conn)
    elif agent_type == 'options':
        return _build_options_detail(conn)
    elif agent_type == 'grid':
        return _build_grid_detail(conn)
    elif agent_type == 'btc':
        return _build_btc_detail(conn)
    elif agent_type == 'snipe':
        return _build_snipe_detail(conn)
    else:
        conn.close()
        return '❓ Agente desconocido'


def _build_stocks_detail(conn) -> str:
    sess = _query_one(conn,
        "SELECT session_name, started_at, initial_balance, current_balance, "
        "total_trades, status FROM stocks_sessions WHERE status='ACTIVE' LIMIT 1")
    if not sess:
        conn.close()
        return '📈 <b>Stocks Agent</b>\nSin sesión activa.'
    sn, started, init_bal, cur_bal, total_tr, status = sess
    open_tr = _query_one(conn,
        "SELECT COUNT(*) FROM stocks_trades WHERE status='OPEN'")
    closed_tr = _query_all(conn,
        "SELECT symbol, entry_price, pnl, closed_at FROM stocks_trades "
        "WHERE status='CLOSED' ORDER BY closed_at DESC LIMIT 5")
    open_list = _query_all(conn,
        "SELECT symbol, entry_price, stop_loss, take_profit, qty "
        "FROM stocks_trades WHERE status='OPEN'")
    conn.close()

    lines = ['📈 <b>Stocks Agent — Detalle</b>', '']
    lines.append(f'Sesión: {sn}')
    lines.append(f'Estado: {status}  |  Inicio: {str(started)[:19]}')
    lines.append(f'Balance inicial: ${float(init_bal):,.2f}  →  Actual: ${float(cur_bal):,.2f}')
    lines.append(f'Trades totales: {total_tr}  |  Abiertos: {open_tr[0] if open_tr else 0}')
    if open_list:
        lines.append('')
        lines.append('── <b>Posiciones abiertas</b> ──')
        for sym, entry, sl, tp, qty in open_list:
            sl_str = f' SL=${float(sl):.2f}' if sl else ''
            tp_str = f' TP=${float(tp):.2f}' if tp else ''
            lines.append(f'  {sym}  Entry ${float(entry):.2f}  Qty {int(qty)}{sl_str}{tp_str}')
    if closed_tr:
        lines.append('')
        lines.append('── <b>Últimos cerrados</b> ──')
        for sym, entry, pnl, closed in closed_tr:
            lines.append(f'  {sym}  PnL ${float(pnl):+.2f}  ({str(closed)[:19]})')
    return '\n'.join(lines)


def _build_poly_detail(conn) -> str:
    sess = _query_one(conn,
        "SELECT session_name, started_at, initial_balance, current_balance, "
        "total_trades, status FROM poly_sessions WHERE status='ACTIVE' LIMIT 1")
    if not sess:
        conn.close()
        return '🔮 <b>Polymarket Agent</b>\nSin sesión activa.'
    sn, started, init_bal, cur_bal, total_tr, status = sess
    open_pos = _query_all(conn,
        "SELECT market, side, entry_price, contracts, current_price "
        "FROM poly_positions WHERE status='OPEN' AND session_name=%s", (sn,))
    closed_pos = _query_all(conn,
        "SELECT market, side, pnl, closed_at FROM poly_positions "
        "WHERE status='CLOSED' AND session_name=%s "
        "ORDER BY closed_at DESC LIMIT 5", (sn,))
    wr_data = _query_one(conn,
        "SELECT COUNT(*), SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) "
        "FROM poly_positions WHERE status='CLOSED' AND session_name=%s", (sn,))
    conn.close()

    lines = ['🔮 <b>Polymarket Agent — Detalle</b>', '']
    lines.append(f'Sesión: {sn}')
    lines.append(f'Estado: {status}  |  Inicio: {str(started)[:19]}')
    lines.append(f'Balance: ${float(init_bal):,.2f}  →  ${float(cur_bal):,.2f}')
    if wr_data:
        t, w = int(wr_data[0]), int(wr_data[1])
        wr = f'{w/t*100:.0f}%' if t > 0 else '—'
        lines.append(f'Trades: {total_tr}  |  WR: {wr} ({w}/{t})')
    if open_pos:
        lines.append('')
        lines.append('── <b>Posiciones abiertas</b> ──')
        for mkt, side, entry, contracts, cur_price in open_pos:
            cur_str = f' Px ${float(cur_price):.2f}' if cur_price else ''
            lines.append(f'  {mkt[:35]}  {side}  ${float(entry):.2f}  x{int(contracts)}{cur_str}')
    if closed_pos:
        lines.append('')
        lines.append('── <b>Últimos cerrados</b> ──')
        for mkt, side, pnl, closed in closed_pos:
            lines.append(f'  {mkt[:35]}  {side}  PnL ${float(pnl):+.2f}')
    return '\n'.join(lines)


def _build_options_detail(conn) -> str:
    sess = _query_one(conn,
        "SELECT session_name, started_at, initial_balance, current_balance, "
        "total_trades, status FROM options_sessions WHERE status='ACTIVE' LIMIT 1")
    if not sess:
        conn.close()
        return '📣 <b>Options Agent</b>\nSin sesión activa.'
    sn, started, init_bal, cur_bal, total_tr, status = sess
    open_pos = _query_all(conn,
        "SELECT instrument_name, side, kind, entry_usd, contracts, "
        "mark_usd, pnl_usd FROM options_positions "
        "WHERE status='OPEN' AND session_name=%s", (sn,))
    closed_pos = _query_all(conn,
        "SELECT instrument_name, side, pnl_usd, closed_at "
        "FROM options_positions WHERE status='CLOSED' AND session_name=%s "
        "ORDER BY closed_at DESC LIMIT 5", (sn,))
    total_premium = _query_one(conn,
        "SELECT COALESCE(SUM(premium_usd), 0) FROM options_positions "
        "WHERE session_name=%s", (sn,))
    conn.close()

    lines = ['📣 <b>Options Agent — Detalle</b>', '']
    lines.append(f'Sesión: {sn}')
    lines.append(f'Estado: {status}  |  Inicio: {str(started)[:19]}')
    lines.append(f'Balance: ${float(init_bal):,.2f}  →  ${float(cur_bal):,.2f}')
    lines.append(f'Trades totales: {total_tr}')
    if total_premium:
        lines.append(f'Prima cobrada: ${float(total_premium[0]):+,.2f}')
    if open_pos:
        lines.append('')
        lines.append('── <b>Posiciones abiertas</b> ──')
        for inst, side, kind, entry, contracts, mark, pnl in open_pos:
            pnl_str = f' PnL ${float(pnl):+.2f}' if pnl else ''
            mark_str = f' Mark ${float(mark):.2f}' if mark else ''
            lines.append(f'  {inst[:30]}  {side} {kind}  Entry ${float(entry):.2f}  x{int(contracts)}{mark_str}{pnl_str}')
    if closed_pos:
        lines.append('')
        lines.append('── <b>Últimos cerrados</b> ──')
        for inst, side, pnl, closed in closed_pos:
            lines.append(f'  {inst[:30]}  {side}  PnL ${float(pnl):+,.2f}')
    return '\n'.join(lines)


def _build_grid_detail(conn) -> str:
    sess = _query_one(conn,
        "SELECT session_name, started_at FROM paper_sessions "
        "WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1")
    if not sess:
        conn.close()
        return '🤖 <b>Grid Bot</b>\nSin sesión activa.'
    sn, started = sess
    open_tr = _query_all(conn,
        "SELECT asset, entry_price, stop_loss, take_profit "
        "FROM trades WHERE status='OPEN' AND strategy='GRID_BOT' "
        "AND timestamp_open >= %s", (started,))
    closed_tr = _query_all(conn,
        "SELECT asset, pnl, closed_at FROM trades "
        "WHERE status='CLOSED' AND strategy='GRID_BOT' "
        "AND timestamp_open >= %s ORDER BY closed_at DESC LIMIT 10", (started,))
    stats = _query_one(conn,
        "SELECT COUNT(*), COALESCE(SUM(pnl), 0), "
        "SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) FROM trades "
        "WHERE status='CLOSED' AND strategy='GRID_BOT' "
        "AND timestamp_open >= %s", (started,))
    conn.close()

    t, sum_pnl, w = (int(stats[0]), float(stats[1]), int(stats[2])) if stats else (0, 0, 0)
    wr = f'{w/t*100:.0f}%' if t > 0 else '—'

    lines = ['🤖 <b>Grid Bot — Detalle</b>', '']
    lines.append(f'Dentro de sesión: {sn}')
    lines.append(f'Trades cerrados: {t}  |  WR: {wr}  |  PnL: ${sum_pnl:+,.2f}')
    if open_tr:
        lines.append('')
        lines.append(f'── <b>Posiciones abiertas ({len(open_tr)}/3)</b> ──')
        for asset, entry, sl, tp in open_tr:
            sl_str = f' SL=${float(sl):.2f}' if sl else ''
            tp_str = f' TP=${float(tp):.2f}' if tp else ''
            lines.append(f'  {asset}  Entry ${float(entry):.2f}{sl_str}{tp_str}')
    if closed_tr:
        lines.append('')
        lines.append('── <b>Últimos cerrados</b> ──')
        for asset, pnl, closed in closed_tr[:5]:
            lines.append(f'  {asset}  PnL ${float(pnl):+,.2f}')
    return '\n'.join(lines)


def _build_btc_detail(conn) -> str:
    open_tr = _query_all(conn,
        "SELECT direction, entry_usdc, stop_usdc, target_usdc "
        "FROM btc_direction_trades WHERE status='OPEN'")
    closed_tr = _query_all(conn,
        "SELECT direction, entry_usdc, pnl_usdc, closed_at "
        "FROM btc_direction_trades WHERE status='CLOSED' "
        "ORDER BY closed_at DESC LIMIT 10")
    stats = _query_one(conn,
        "SELECT COUNT(*), SUM(CASE WHEN pnl_usdc>0 THEN 1 ELSE 0 END), "
        "COALESCE(SUM(pnl_usdc), 0) FROM btc_direction_trades "
        "WHERE status='CLOSED'")
    conn.close()

    t, w, sum_pnl = (int(stats[0]), int(stats[1] or 0), float(stats[2] or 0)) if stats else (0, 0, 0)
    wr = f'{w/t*100:.0f}%' if t > 0 else '—'

    lines = ['₿ <b>BTC Direction Agent — Detalle</b>', '']
    lines.append(f'Trades cerrados: {t}  |  WR: {wr}  |  PnL: ${sum_pnl:+,.2f}')
    if open_tr:
        lines.append('')
        lines.append(f'── <b>Posiciones abiertas ({len(open_tr)})</b> ──')
        for direction, entry, stop, target in open_tr:
            sl_str = f' SL ${float(stop):,.2f}' if stop else ''
            tp_str = f' TP ${float(target):,.2f}' if target else ''
            lines.append(f'  {direction}  Entry ${float(entry):,.2f}{sl_str}{tp_str}')
    if closed_tr:
        lines.append('')
        lines.append('── <b>Últimos cerrados</b> ──')
        for direction, entry, pnl, closed in closed_tr[:5]:
            lines.append(f'  {direction}  Entry ${float(entry):,.2f}  PnL ${float(pnl):+,.2f}')
    return '\n'.join(lines)


def _build_snipe_detail(conn) -> str:
    """Detalle del PolyMarket SNIPE Agent."""
    try:
        stats = _query_one(conn,
            "SELECT COUNT(*), SUM(CASE WHEN outcome='WIN' THEN 1 ELSE 0 END), "
            "COALESCE(SUM(pnl_usdc), 0), "
            "SUM(CASE WHEN strategy='SNIPE' THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN strategy='ARB' THEN 1 ELSE 0 END) "
            "FROM snipe_trades WHERE status='CLOSED'")
    except Exception:
        stats = None
    open_tr = _query_all(conn,
        "SELECT strategy, asset, direction, entry_price, shares, cost_usdc, timestamp_open "
        "FROM snipe_trades WHERE status='OPEN' ORDER BY timestamp_open DESC LIMIT 10")
    conn.close()

    t, w, sum_pnl, snipe_cnt, arb_cnt = (int(stats[0]), int(stats[1] or 0), float(stats[2] or 0),
                                          int(stats[3] or 0), int(stats[4] or 0)) if stats else (0, 0, 0, 0, 0)
    wr = f'{w/t*100:.0f}%' if t > 0 else '—'

    lines = ['🎯 <b>PolyMarket SNIPE Agent — Detalle</b>', '']
    lines.append(f'Trades: {t}  |  WR: {wr}  |  PnL: ${sum_pnl:+,.2f}')
    lines.append(f'SNIPE: {snipe_cnt}  |  ARB: {arb_cnt}')

    if open_tr:
        lines.append('')
        lines.append(f'── <b>Posiciones abiertas ({len(open_tr)})</b> ──')
        for strat, asset, direction, entry, shares, cost_ts, _ in open_tr:
            lines.append(
                f'  [{strat}] {asset} {direction} '
                f'@ ${float(entry):.4f} x{int(shares)} = ${float(cost_ts):.2f}'
            )

    return '\n'.join(lines)


# ── Dispatcher ─────────────────────────────────────────────────────────────────

def process_message(message: dict):
    """Procesa un mensaje entrante de Telegram."""
    chat_id = message.get('chat', {}).get('id')
    text = (message.get('text') or '').strip()

    if chat_id != TELEGRAM_CHAT_ID:
        logger.warning(f'Mensaje de chat no autorizado: {chat_id}')
        return

    if not text:
        return

    cmd_raw = text.split()[0].lower()
    handler = COMMAND_MAP.get(cmd_raw)

    if handler is not None:
        logger.info(f'Comando: {cmd_raw} → {handler}')
        output = _dispatch(handler)
        send_message(output, chat_id)
    else:
        logger.info(f'Conversación libre: {text[:80]}')
        reply = chat_with_arthas(chat_id, text)
        send_message(reply, chat_id)


def _dispatch(handler: str) -> str:
    """Ejecuta el handler correspondiente y devuelve la salida."""
    try:
        if handler == '__all_status__':
            return build_all_agents_status()
        elif handler == '__commands_help__':
            return build_commands_help()
        elif handler == '__crypto_status__':
            return run_arthas_command('status')
        elif handler in ('__stocks_detail__', '__poly_detail__',
                         '__options_detail__', '__grid_detail__',
                         '__btc_detail__', '__snipe_detail__'):
            agent_map = {
                '__stocks_detail__': 'stocks',
                '__poly_detail__': 'poly',
                '__options_detail__': 'options',
                '__grid_detail__': 'grid',
                '__btc_detail__': 'btc',
                '__snipe_detail__': 'snipe',
            }
            return build_agent_detail(agent_map[handler])
        else:
            return run_arthas_command(handler)
    except Exception as e:
        logger.error(f'Error en dispatch ({handler}): {e}', exc_info=True)
        return f'❌ Error interno: {e}'


def chat_with_arthas(chat_id: int, user_text: str) -> str:
    """Envía el mensaje al LLM con historial conversacional."""
    history = _conversation_history.setdefault(chat_id, [])

    history.append({'role': 'user', 'content': user_text})

    if len(history) > _MAX_HISTORY:
        history[:] = history[-_MAX_HISTORY:]

    try:
        response = _openai_client.chat.completions.create(
            model='deepseek-chat',
            messages=[{'role': 'system', 'content': ARTHAS_SYSTEM_PROMPT}] + history,
            max_tokens=800,
            temperature=0.7,
        )
        reply = response.choices[0].message.content.strip()
        history.append({'role': 'assistant', 'content': reply})
        return reply
    except Exception as e:
        logger.error(f'Error en chat_with_arthas: {e}')
        return f'⚠️ No pude procesar eso ahora: {e}'


# ── Polling Loop ───────────────────────────────────────────────────────────────

def polling_loop():
    """Long-polling loop para recibir mensajes."""
    logger.info('Telegram bot started — listening for commands...')

    offset = None
    try:
        r = requests.get(f'{API}/getUpdates', params={'timeout': 0, 'limit': 1}, timeout=5)
        d = r.json()
        if d.get('ok') and d.get('result'):
            logger.info(f'{len(d["result"])} mensajes pendientes al arrancar')
        time.sleep(1)
    except Exception:
        pass

    while True:
        try:
            params = {'timeout': 30, 'allowed_updates': ['message']}
            if offset is not None:
                params['offset'] = offset

            resp = requests.get(f'{API}/getUpdates', params=params, timeout=35)
            data = resp.json()

            if not data.get('ok'):
                err_code = data.get('error_code', 0)
                if err_code == 409:
                    logger.error('Conflict 409 — hay otra instancia activa. Cerrando este proceso.')
                    sys.exit(1)
                logger.error(f'Telegram API error: {data}')
                time.sleep(5)
                continue

            for update in data.get('result', []):
                offset = update['update_id'] + 1
                msg = update.get('message')
                if msg:
                    process_message(msg)

        except requests.exceptions.Timeout:
            continue
        except KeyboardInterrupt:
            logger.info('Telegram bot stopped by user')
            break
        except Exception as e:
            logger.error(f'Polling error: {e}', exc_info=True)
            time.sleep(5)


# ── PID Lock ───────────────────────────────────────────────────────────────────

_PID_FILE = '/tmp/arthas_telegram_bot.pid'


def _acquire_lock():
    """Evita múltiples instancias usando PID file."""
    if os.path.exists(_PID_FILE):
        try:
            old_pid = int(open(_PID_FILE).read().strip())
            os.kill(old_pid, 0)
            logger.error(f'Bot ya está corriendo (PID {old_pid}). Saliendo.')
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            logger.info('PID file huérfano encontrado, continuando...')

    with open(_PID_FILE, 'w') as f:
        f.write(str(os.getpid()))

    import atexit
    atexit.register(lambda: os.path.exists(_PID_FILE) and os.remove(_PID_FILE))


if __name__ == '__main__':
    _acquire_lock()
    polling_loop()
