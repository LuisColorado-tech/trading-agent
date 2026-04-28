"""
strategy_monitor.py — Monitor de rendimiento de estrategias (Trading + Polymarket).

Analiza en profundidad el estado actual de todas las estrategias, detecta
anomalías y genera un informe completo + alerta Telegram.

Estrategias monitoreadas:
  Trading Agent:   TREND_MOMENTUM, SMC_ORDER_BLOCKS, BTC_MICROSTRUCTURE, GRID_BOT
  Polymarket:      SIGNAL_BASED, TAIL_END, LATE_ENTRY, LEGGED_ARB, COMBINATORIAL_ARB
  BTC Direction:   BTC_DIRECTION (tabla btc_direction_trades)

Uso:
    venv/bin/python3 scripts/strategy_monitor.py              # completo + Telegram
    venv/bin/python3 scripts/strategy_monitor.py --quick      # solo consola
    venv/bin/python3 scripts/strategy_monitor.py --no-telegram # consola + reporte sin telegram
"""

import argparse
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, '/opt/trading')

from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

import redis as redis_lib
from sqlalchemy import create_engine, text

from api.db import q, q_one
from core.notifications import send_telegram

# ─────────────────────────────────────────────────────────────
# Constantes
# ─────────────────────────────────────────────────────────────
REPORTS_DIR = Path('/opt/trading/reports')
REPORTS_DIR.mkdir(exist_ok=True)

SEP  = '═' * 65
SEP2 = '─' * 65

# Umbrales de alerta
THRESH = {
    'wr_warn':           0.35,   # WR < 35% → amarillo
    'wr_crit':           0.30,   # WR < 30% → rojo
    'pf_warn':           1.00,   # PF < 1.0 → amarillo
    'pf_crit':           0.80,   # PF < 0.8 → rojo (destrucción)
    'consec_warn':       3,      # consecutive losses ≥ 3 → amarillo
    'consec_crit':       5,      # consecutive losses ≥ 5 → rojo
    'dd_warn':           0.05,   # drawdown ≥ 5% → amarillo
    'dd_crit':           0.08,   # drawdown ≥ 8% → rojo
    'min_trades_eval':   10,     # mínimo de trades para evaluar estrategia
    'edge_divergence':   0.10,   # si edge_real < edge_declarado - 10% → alerta
    'poly_wr_warn':      0.45,
    'poly_wr_crit':      0.35,
}

NOW = datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def redis_client():
    try:
        r = redis_lib.Redis(
            host=os.getenv('REDIS_HOST', 'localhost'),
            port=int(os.getenv('REDIS_PORT', 6379)),
            password=os.getenv('REDIS_PASSWORD') or None,
            decode_responses=True,
            socket_connect_timeout=3,
        )
        r.ping()
        return r
    except Exception:
        return None


def pct(n, d):
    """División segura para porcentaje. Castea Decimal a float."""
    n, d = float(n or 0), float(d or 0)
    return (n / d * 100) if d else 0.0


def pf_calc(gross_profit, gross_loss):
    """Profit Factor: gross_profit / abs(gross_loss). Castea Decimal a float."""
    gp, gl = float(gross_profit or 0), float(gross_loss or 0)
    if gl < 0:
        return round(gp / abs(gl), 3)
    if gl == 0:
        return float('inf') if gp > 0 else 0.0
    return round(gp / gl, 3)


def flag(value, warn_thresh, crit_thresh, higher_is_better=True):
    """Retorna 🔴/🟡/🟢 según umbrales."""
    if higher_is_better:
        if value < crit_thresh:  return '🔴'
        if value < warn_thresh:  return '🟡'
        return '🟢'
    else:
        if value > crit_thresh:  return '🔴'
        if value > warn_thresh:  return '🟡'
        return '🟢'


def sharpe(returns: list[float]) -> float:
    """Sharpe ratio simplificado (diario, risk-free=0)."""
    if len(returns) < 5:
        return 0.0
    import statistics
    mean = statistics.mean(returns)
    std  = statistics.stdev(returns)
    return round((mean / std) * (252 ** 0.5), 3) if std > 0 else 0.0


def expectancy(avg_win, avg_loss, wr):
    """Expectancy = (WR * avg_win) + ((1-WR) * avg_loss). Castea Decimal."""
    return round(float(wr) * float(avg_win or 0) + (1 - float(wr)) * float(avg_loss or 0), 4)


def consecutive_losses(trades: list[dict]) -> int:
    """Calcula racha de pérdidas consecutivas más reciente."""
    streak = 0
    for t in sorted(trades, key=lambda x: x.get('timestamp_close') or '', reverse=True):
        if (t.get('pnl') or 0) <= 0:
            streak += 1
        else:
            break
    return streak


# ─────────────────────────────────────────────────────────────
# 1. TRADING AGENT — SESSION ACTIVA
# ─────────────────────────────────────────────────────────────
def get_active_session() -> dict | None:
    return q_one(
        "SELECT * FROM paper_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1"
    )


def get_trading_global(session_start) -> dict:
    """Métricas globales de la sesión activa."""
    r = q_one("""
        SELECT
            COUNT(*)                                      AS total,
            SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)     AS wins,
            SUM(pnl)                                      AS total_pnl,
            AVG(CASE WHEN pnl > 0 THEN pnl ELSE NULL END) AS avg_win,
            AVG(CASE WHEN pnl <= 0 THEN pnl ELSE NULL END) AS avg_loss,
            SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END)   AS gross_profit,
            SUM(CASE WHEN pnl < 0 THEN pnl ELSE 0 END)   AS gross_loss,
            MAX(ABS(pnl))                                 AS max_single_loss
        FROM trades
        WHERE status = 'CLOSED'
          AND paper_trade = true
          AND timestamp_open >= :s
    """, {'s': session_start})
    return r or {}


def get_trading_by_strategy(session_start) -> list[dict]:
    return q("""
        SELECT
            strategy,
            COUNT(*)                                      AS total,
            SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)     AS wins,
            SUM(pnl)                                      AS total_pnl,
            AVG(CASE WHEN pnl > 0 THEN pnl ELSE NULL END) AS avg_win,
            AVG(CASE WHEN pnl <= 0 THEN pnl ELSE NULL END) AS avg_loss,
            SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END)   AS gross_profit,
            SUM(CASE WHEN pnl < 0 THEN pnl ELSE 0 END)   AS gross_loss,
            MIN(timestamp_close)                          AS first_trade,
            MAX(timestamp_close)                          AS last_trade
        FROM trades
        WHERE status = 'CLOSED'
          AND paper_trade = true
          AND timestamp_open >= :s
        GROUP BY strategy
        ORDER BY total_pnl DESC
    """, {'s': session_start})


def get_trading_by_asset(session_start) -> list[dict]:
    return q("""
        SELECT
            asset,
            COUNT(*)                                      AS total,
            SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)     AS wins,
            SUM(pnl)                                      AS total_pnl,
            SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END)   AS gross_profit,
            SUM(CASE WHEN pnl < 0 THEN pnl ELSE 0 END)   AS gross_loss
        FROM trades
        WHERE status = 'CLOSED'
          AND paper_trade = true
          AND timestamp_open >= :s
        GROUP BY asset
        ORDER BY total_pnl DESC
    """, {'s': session_start})


def get_close_reason_dist(session_start) -> list[dict]:
    return q("""
        SELECT close_reason, COUNT(*) AS cnt, SUM(pnl) AS pnl_sum
        FROM trades
        WHERE status = 'CLOSED'
          AND paper_trade = true
          AND timestamp_open >= :s
        GROUP BY close_reason
        ORDER BY cnt DESC
    """, {'s': session_start})


def get_recent_trades(session_start, limit=20) -> list[dict]:
    return q("""
        SELECT asset, side, strategy, pnl, close_reason, timestamp_close
        FROM trades
        WHERE status = 'CLOSED'
          AND paper_trade = true
          AND timestamp_open >= :s
        ORDER BY timestamp_close DESC LIMIT :lim
    """, {'s': session_start, 'lim': limit})


def get_portfolio_snapshot() -> dict | None:
    return q_one(
        "SELECT total_balance, available_cash, exposure_pct, drawdown_pct, pnl_total, peak_balance "
        "FROM portfolio ORDER BY timestamp DESC LIMIT 1"
    )


def get_open_trades() -> list[dict]:
    return q(
        "SELECT asset, strategy, side, entry_price, stop_loss, take_profit, position_size "
        "FROM trades WHERE status='OPEN' ORDER BY timestamp_open"
    )


def get_daily_pnl(session_start) -> list[dict]:
    """PnL diario para calcular Sharpe y equity curve."""
    return q("""
        SELECT
            DATE(timestamp_close AT TIME ZONE 'UTC') AS day,
            SUM(pnl) AS daily_pnl,
            COUNT(*) AS trades
        FROM trades
        WHERE status = 'CLOSED'
          AND paper_trade = true
          AND timestamp_open >= :s
        GROUP BY day
        ORDER BY day
    """, {'s': session_start})


def get_signals_by_strategy(session_start) -> list[dict]:
    """Cuenta señales por tipo/indicador (la tabla signals no tiene columna strategy)."""
    return q("""
        SELECT
            COALESCE(signal_type, 'unknown') AS strategy,
            COUNT(*) AS total_signals,
            AVG(strength) AS avg_score,
            COUNT(DISTINCT asset) AS avg_confluence
        FROM signals
        WHERE timestamp >= :s
        GROUP BY signal_type
        ORDER BY total_signals DESC
    """, {'s': session_start})


# ─────────────────────────────────────────────────────────────
# 2. POLYMARKET AGENT
# ─────────────────────────────────────────────────────────────
def get_poly_active_session() -> dict | None:
    return q_one(
        "SELECT * FROM poly_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1"
    )


def get_poly_by_strategy(poly_session_name) -> list[dict]:
    return q("""
        SELECT
            UPPER(strategy)                               AS strategy,
            COUNT(*)                                      AS total,
            SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)     AS wins,
            SUM(pnl)                                      AS total_pnl,
            AVG(CASE WHEN pnl > 0 THEN pnl ELSE NULL END) AS avg_win,
            AVG(CASE WHEN pnl <= 0 THEN pnl ELSE NULL END) AS avg_loss,
            SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END)   AS gross_profit,
            SUM(CASE WHEN pnl < 0 THEN pnl ELSE 0 END)   AS gross_loss,
            AVG((metadata->>'edge')::float)               AS avg_declared_edge,
            AVG((metadata->>'confidence')::float)         AS avg_confidence
        FROM poly_positions
        WHERE status = 'CLOSED'
          AND session_name = :sname
        GROUP BY UPPER(strategy)
        ORDER BY total_pnl DESC
    """, {'sname': poly_session_name})


def get_poly_global(poly_session_name) -> dict:
    r = q_one("""
        SELECT
            COUNT(*)                                      AS total,
            SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END)     AS wins,
            SUM(pnl)                                      AS total_pnl,
            AVG(CASE WHEN pnl > 0 THEN pnl ELSE NULL END) AS avg_win,
            AVG(CASE WHEN pnl <= 0 THEN pnl ELSE NULL END) AS avg_loss,
            SUM(CASE WHEN pnl > 0 THEN pnl ELSE 0 END)   AS gross_profit,
            SUM(CASE WHEN pnl < 0 THEN pnl ELSE 0 END)   AS gross_loss,
            AVG((metadata->>'edge')::float)               AS avg_declared_edge
        FROM poly_positions
        WHERE status = 'CLOSED'
          AND session_name = :sname
    """, {'sname': poly_session_name})
    return r or {}


def get_poly_open(poly_session_name) -> list[dict]:
    return q("""
        SELECT condition_id, UPPER(strategy) AS strategy, side, entry_price, shares, cost_basis,
               (metadata->>'edge')::float AS edge
        FROM poly_positions
        WHERE status = 'OPEN'
          AND session_name = :sname
        ORDER BY timestamp_open DESC
    """, {'sname': poly_session_name})


def get_poly_close_reasons(poly_session_name) -> list[dict]:
    return q("""
        SELECT close_reason, COUNT(*) AS cnt, SUM(pnl) AS pnl_sum
        FROM poly_positions
        WHERE status = 'CLOSED'
          AND session_name = :sname
        GROUP BY close_reason
        ORDER BY cnt DESC
    """, {'sname': poly_session_name})


def get_poly_recent(poly_session_name, limit=15) -> list[dict]:
    return q("""
        SELECT UPPER(strategy) AS strategy, side, entry_price, pnl, close_reason, timestamp_close,
               (metadata->>'edge')::float AS edge_declared
        FROM poly_positions
        WHERE status = 'CLOSED'
          AND session_name = :sname
        ORDER BY timestamp_close DESC LIMIT :lim
    """, {'sname': poly_session_name, 'lim': limit})


# ─────────────────────────────────────────────────────────────
# 3. BTC DIRECTION AGENT
# ─────────────────────────────────────────────────────────────
def get_btcd_global() -> dict:
    r = q_one("""
        SELECT
            COUNT(*)                                               AS total,
            SUM(CASE WHEN pnl_usdc > 0 THEN 1 ELSE 0 END)         AS wins,
            SUM(pnl_usdc)                                          AS total_pnl,
            AVG(CASE WHEN pnl_usdc > 0 THEN pnl_usdc ELSE NULL END) AS avg_win,
            AVG(CASE WHEN pnl_usdc <= 0 THEN pnl_usdc ELSE NULL END) AS avg_loss,
            SUM(CASE WHEN pnl_usdc > 0 THEN pnl_usdc ELSE 0 END)  AS gross_profit,
            SUM(CASE WHEN pnl_usdc < 0 THEN pnl_usdc ELSE 0 END)  AS gross_loss
        FROM btc_direction_trades
        WHERE status = 'CLOSED'
    """)
    return r or {}


def get_btcd_rolling(n=50) -> dict:
    """WR y PnL en los últimos N trades."""
    r = q_one(f"""
        SELECT
            COUNT(*)                                       AS total,
            SUM(CASE WHEN pnl_usdc > 0 THEN 1 ELSE 0 END) AS wins,
            SUM(pnl_usdc)                                  AS total_pnl
        FROM (
            SELECT pnl_usdc FROM btc_direction_trades
            WHERE status = 'CLOSED'
            ORDER BY timestamp_close DESC LIMIT {n}
        ) sub
    """)
    return r or {}


def get_btcd_by_direction() -> list[dict]:
    return q("""
        SELECT
            direction,
            COUNT(*)                                       AS total,
            SUM(CASE WHEN pnl_usdc > 0 THEN 1 ELSE 0 END) AS wins,
            SUM(pnl_usdc)                                  AS pnl
        FROM btc_direction_trades
        WHERE status = 'CLOSED'
        GROUP BY direction
        ORDER BY total DESC
    """)


def get_btcd_recent(limit=10) -> list[dict]:
    return q("""
        SELECT direction, entry_price, pnl_usdc AS pnl, outcome AS close_reason, timestamp_close
        FROM btc_direction_trades
        WHERE status = 'CLOSED'
        ORDER BY timestamp_close DESC LIMIT :lim
    """, {'lim': limit})


# ─────────────────────────────────────────────────────────────
# 4. REDIS — Cooldowns y Halts
# ─────────────────────────────────────────────────────────────
def get_redis_state() -> dict:
    rc = redis_client()
    if not rc:
        return {'error': 'Redis no disponible'}
    try:
        cooldowns = rc.keys('cooldown:*')
        halts     = rc.keys('halt:*')
        dedups    = rc.keys('dedup:*')
        pg_blocks = rc.keys('pg:blocked:*')
        pg_prob   = rc.keys('pg:probation:*')
        return {
            'cooldowns': cooldowns,
            'halts':     halts,
            'dedups':    dedups,
            'pg_blocks': pg_blocks,
            'pg_prob':   pg_prob,
        }
    except Exception as e:
        return {'error': str(e)}


# ─────────────────────────────────────────────────────────────
# 5. ANOMALY DETECTION
# ─────────────────────────────────────────────────────────────
class Anomaly:
    def __init__(self, level, context, message):
        self.level   = level    # CRIT / WARN / INFO
        self.context = context
        self.message = message

    @property
    def icon(self):
        return {'CRIT': '🔴', 'WARN': '🟡', 'INFO': 'ℹ️'}.get(self.level, '⚪')

    def __str__(self):
        return f"{self.icon} [{self.level}] {self.context}: {self.message}"


def detect_anomalies(
    trading_by_strat, poly_by_strat, btcd_global, btcd_rolling,
    portfolio, redis_state, session, poly_session
) -> list[Anomaly]:
    anomalies = []

    # Trading strategies
    for s in trading_by_strat:
        name  = s.get('strategy') or 'UNKNOWN'
        total = s.get('total') or 0
        wins  = s.get('wins') or 0
        pnl   = s.get('total_pnl') or 0
        gp    = s.get('gross_profit') or 0
        gl    = s.get('gross_loss') or 0

        wr = pct(wins, total) / 100

        if total >= THRESH['min_trades_eval']:
            if wr < THRESH['wr_crit']:
                anomalies.append(Anomaly('CRIT', f'Trading/{name}',
                    f'WR {wr*100:.1f}% bajo mínimo crítico ({THRESH["wr_crit"]*100:.0f}%) en {total} trades'))
            elif wr < THRESH['wr_warn']:
                anomalies.append(Anomaly('WARN', f'Trading/{name}',
                    f'WR {wr*100:.1f}% bajo umbral de alerta en {total} trades'))

            pf = pf_calc(gp, gl)
            if pf < THRESH['pf_crit']:
                anomalies.append(Anomaly('CRIT', f'Trading/{name}',
                    f'Profit Factor {pf:.2f} — destrucción de capital activa'))
            elif pf < THRESH['pf_warn']:
                anomalies.append(Anomaly('WARN', f'Trading/{name}',
                    f'Profit Factor {pf:.2f} — sin edge confirmado'))

            if pnl < -100:
                anomalies.append(Anomaly('WARN', f'Trading/{name}',
                    f'PnL negativo de ${pnl:.2f} en sesión actual'))
        elif total > 0:
            anomalies.append(Anomaly('INFO', f'Trading/{name}',
                f'Solo {total} trades — datos insuficientes para evaluación ({THRESH["min_trades_eval"]} requeridos)'))
        else:
            anomalies.append(Anomaly('INFO', f'Trading/{name}',
                'Sin trades registrados — estrategia no ha generado señales ejecutadas'))

    # Estrategias nuevas sin datos
    known_strats = {s.get('strategy') for s in trading_by_strat}
    for new_strat in ['SMC_ORDER_BLOCKS', 'BTC_MICROSTRUCTURE']:
        if new_strat not in known_strats:
            anomalies.append(Anomaly('INFO', f'Trading/{new_strat}',
                'Estrategia nueva activada (Apr 25) — aún sin trades ejecutados. '
                'SMC_ORDER_BLOCKS requiere régimen TREND/BREAKOUT. '
                'BTC_MICROSTRUCTURE requiere TREND/BREAKOUT/DIP_BUY. '
                'Mercado en CHOPPY → bloqueadas por market_regime (correcto).'))

    # Portfolio drawdown
    if portfolio:
        dd = portfolio.get('drawdown_pct') or 0
        if dd >= THRESH['dd_crit']:
            anomalies.append(Anomaly('CRIT', 'Portfolio',
                f'Drawdown {dd*100:.2f}% ≥ {THRESH["dd_crit"]*100:.0f}% — cerca del halt automático (10%)'))
        elif dd >= THRESH['dd_warn']:
            anomalies.append(Anomaly('WARN', 'Portfolio',
                f'Drawdown {dd*100:.2f}% ≥ {THRESH["dd_warn"]*100:.0f}%'))

    # Redis: halts activos
    if redis_state and not redis_state.get('error'):
        if redis_state.get('halts'):
            anomalies.append(Anomaly('CRIT', 'Sistema',
                f'Trading HALT activo: {redis_state["halts"]}'))
        if redis_state.get('pg_blocks'):
            anomalies.append(Anomaly('WARN', 'PerformanceGuard',
                f'Estrategias bloqueadas por PG: {redis_state["pg_blocks"]}'))
        if redis_state.get('pg_prob'):
            anomalies.append(Anomaly('INFO', 'PerformanceGuard',
                f'Estrategias en probation (size reducido 50%): {redis_state["pg_prob"]}'))

    # Polymarket strategies
    for s in poly_by_strat:
        name  = s.get('strategy') or 'UNKNOWN'
        total = s.get('total') or 0
        wins  = s.get('wins') or 0
        pnl   = s.get('total_pnl') or 0
        gp    = s.get('gross_profit') or 0
        gl    = s.get('gross_loss') or 0
        avg_edge   = float(s.get('avg_declared_edge') or 0)
        avg_conf   = float(s.get('avg_confidence') or 0)

        wr = pct(wins, total) / 100

        if total >= 5:
            if wr < THRESH['poly_wr_crit']:
                anomalies.append(Anomaly('CRIT', f'Polymarket/{name}',
                    f'WR {wr*100:.1f}% — muy bajo para mercados de predicción'))
            elif wr < THRESH['poly_wr_warn']:
                anomalies.append(Anomaly('WARN', f'Polymarket/{name}',
                    f'WR {wr*100:.1f}% bajo objetivo ≥ 45%'))

            pf = pf_calc(gp, gl)
            if pf < THRESH['pf_crit']:
                anomalies.append(Anomaly('CRIT', f'Polymarket/{name}',
                    f'Profit Factor {pf:.2f} — edge destruido'))

            # Edge calibration check
            if avg_edge > 0 and total >= 5:
                # Edge realizado = gross_profit / total_cost_basis (proxy: pnl positivo vs total apostado)
                gp_f = float(gp)
                gl_f = float(gl)
                pnl_f = float(pnl)
                denom = abs(gl_f) + gp_f
                edge_real = pct(pnl_f, denom) / 100 if denom > 0 else 0.0
                drift = avg_edge - edge_real
                if drift > THRESH['edge_divergence']:
                    anomalies.append(Anomaly('WARN', f'Polymarket/{name}',
                        f'Edge calibration drift: declarado={avg_edge*100:.1f}% vs real={edge_real*100:.1f}% '
                        f'(gap={drift*100:.1f}pp)'))

    # BTC Direction
    btcd_total = btcd_global.get('total') or 0
    btcd_wins  = btcd_global.get('wins') or 0
    btcd_pnl   = btcd_global.get('total_pnl') or 0
    if btcd_total >= 10:
        btcd_wr = pct(btcd_wins, btcd_total) / 100
        if btcd_wr < 0.30:
            anomalies.append(Anomaly('CRIT', 'BTC Direction',
                f'WR histórico {btcd_wr*100:.1f}% — sin edge validado ({btcd_total} trades, PnL ${btcd_pnl:.2f})'))
        elif btcd_wr < 0.40:
            anomalies.append(Anomaly('WARN', 'BTC Direction',
                f'WR {btcd_wr*100:.1f}% — bajo objetivo mínimo del 40%'))

        r50 = btcd_rolling
        r50_total = r50.get('total') or 0
        r50_wins  = r50.get('wins') or 0
        if r50_total >= 20:
            r50_wr = pct(r50_wins, r50_total) / 100
            if r50_wr > btcd_wr + 0.08:
                anomalies.append(Anomaly('INFO', 'BTC Direction',
                    f'Señal de mejora: WR rolling-50 {r50_wr*100:.1f}% > WR total {btcd_wr*100:.1f}%'))

    return sorted(anomalies, key=lambda a: {'CRIT': 0, 'WARN': 1, 'INFO': 2}[a.level])


# ─────────────────────────────────────────────────────────────
# 6. CONSTRUIR EL INFORME
# ─────────────────────────────────────────────────────────────
def build_report(
    session, portfolio, open_trades, daily_pnl_rows,
    trading_global, trading_by_strat, trading_by_asset, close_reasons,
    signals_by_strat, recent_trades,
    poly_session, poly_global, poly_by_strat, poly_open, poly_close_reasons,
    btcd_global, btcd_rolling, btcd_by_dir,
    redis_state, anomalies
) -> str:

    ts  = NOW.strftime('%Y-%m-%d %H:%M UTC')
    lines = []
    L = lines.append

    # ── CABECERA ──────────────────────────────────────────────
    L(SEP)
    L(f'  INFORME DE MONITOREO DE ESTRATEGIAS — {ts}')
    L(SEP)
    L('')

    # ── 0. RESUMEN EJECUTIVO ──────────────────────────────────
    crit_count = sum(1 for a in anomalies if a.level == 'CRIT')
    warn_count = sum(1 for a in anomalies if a.level == 'WARN')
    info_count = sum(1 for a in anomalies if a.level == 'INFO')

    if crit_count > 0:
        global_status = '🔴 ALERTA CRÍTICA'
    elif warn_count > 0:
        global_status = '🟡 VIGILANCIA'
    else:
        global_status = '🟢 NORMAL'

    L(f'## 0. RESUMEN EJECUTIVO')
    L('')
    L(f'  Estado global:   {global_status}')
    L(f'  Anomalías:       🔴 {crit_count} críticas | 🟡 {warn_count} alertas | ℹ️  {info_count} info')
    L(f'  Timestamp:       {ts}')
    L('')

    # Portfolio snapshot
    if portfolio:
        bal = portfolio.get('total_balance') or 0
        dd  = (portfolio.get('drawdown_pct') or 0) * 100
        exp = (portfolio.get('exposure_pct') or 0) * 100
        pnl_total = portfolio.get('pnl_total') or 0
        dd_flag = flag(dd / 100, THRESH['dd_warn'], THRESH['dd_crit'], higher_is_better=False)
        L(f'  Portfolio:       Balance ${bal:,.2f} | PnL ${pnl_total:+,.2f} | '
          f'Drawdown {dd_flag} {dd:.2f}% | Exposición {exp:.1f}%')

    open_count = len(open_trades)
    L(f'  Trades abiertos: {open_count}')
    if open_trades:
        for t in open_trades:
            L(f'    • {t["asset"]} {t["side"]} | strat={t["strategy"]} | entry={t["entry_price"]:.4f}')

    L('')

    # Halts activos
    if redis_state and not redis_state.get('error'):
        if redis_state.get('halts'):
            L(f'  ⛔ HALT ACTIVO: {", ".join(redis_state["halts"])}')
        if redis_state.get('cooldowns'):
            L(f'  ⏸  Cooldowns activos: {len(redis_state["cooldowns"])} assets')
        if redis_state.get('pg_blocks'):
            L(f'  🚫 PG Bloqueadas: {", ".join(redis_state["pg_blocks"])}')

    L('')
    L(SEP2)

    # ── 1. TRADING AGENT ─────────────────────────────────────
    L('')
    L(f'## 1. TRADING AGENT')

    sess_name = session.get('session_name', 'N/A') if session else 'N/A'
    sess_start = str(session.get('started_at', ''))[:10] if session else 'N/A'
    sess_bal   = session.get('final_balance') or session.get('initial_balance') or 0 if session else 0
    L(f'   Sesión: {sess_name} | Inicio: {sess_start} | Balance: ${sess_bal:,.2f}')
    L('')

    # Métricas globales
    tg = trading_global
    total  = tg.get('total') or 0
    wins   = tg.get('wins') or 0
    t_pnl  = tg.get('total_pnl') or 0
    avg_w  = tg.get('avg_win') or 0
    avg_l  = tg.get('avg_loss') or 0
    gp     = tg.get('gross_profit') or 0
    gl     = tg.get('gross_loss') or 0

    if total > 0:
        wr_val = pct(wins, total)
        pf_val = pf_calc(gp, gl)
        exp_val = expectancy(avg_w, avg_l, wr_val / 100)
        wr_f = flag(wr_val / 100, THRESH['wr_warn'], THRESH['wr_crit'])
        pf_f = flag(pf_val, THRESH['pf_warn'], THRESH['pf_crit'])

        # Sharpe
        daily_returns = [float(r.get('daily_pnl') or 0) for r in daily_pnl_rows]
        sh = sharpe(daily_returns)

        L(f'   Métricas globales ({total} trades):')
        L(f'     WR:            {wr_f} {wr_val:.1f}%')
        L(f'     Profit Factor: {pf_f} {pf_val:.3f}')
        L(f'     Sharpe:        {"🟢" if sh > 0.8 else "🟡" if sh > 0 else "🔴"} {sh:.3f}')
        L(f'     PnL total:     {"🟢" if t_pnl > 0 else "🔴"} ${t_pnl:+,.2f}')
        L(f'     Avg win:       ${avg_w:+.2f} | Avg loss: ${avg_l:+.2f}')
        L(f'     Expectancy:    ${exp_val:+.4f}/trade')
    else:
        L('   Sin trades cerrados en sesión activa.')
    L('')

    # Por estrategia
    L(f'   --- Por Estrategia ---')
    L('')

    STRATEGY_LABEL = {
        'TREND_MOMENTUM':    'Trend Momentum    ',
        'SMC_ORDER_BLOCKS':  'SMC Order Blocks  ',
        'BTC_MICROSTRUCTURE':'BTC Microstructure',
        'GRID_BOT':          'Grid Bot          ',
        'MEAN_REVERSION':    'Mean Reversion    ',
    }

    known_strats_in_db = {s.get('strategy') for s in trading_by_strat}
    all_monitor_strats = list(STRATEGY_LABEL.keys())

    for strat in all_monitor_strats:
        row = next((s for s in trading_by_strat if s.get('strategy') == strat), None)
        label = STRATEGY_LABEL.get(strat, strat.ljust(20))

        if not row or (row.get('total') or 0) == 0:
            L(f'   {label} | Sin trades aún {"(nueva — activada Apr 25)" if strat in ["SMC_ORDER_BLOCKS","BTC_MICROSTRUCTURE"] else ""}')
            continue

        n  = row.get('total') or 0
        w  = row.get('wins') or 0
        p  = row.get('total_pnl') or 0
        aw = row.get('avg_win') or 0
        al = row.get('avg_loss') or 0
        gp_s = row.get('gross_profit') or 0
        gl_s = row.get('gross_loss') or 0
        wr_s = pct(w, n)
        pf_s = pf_calc(gp_s, gl_s)
        wr_f = flag(wr_s / 100, THRESH['wr_warn'], THRESH['wr_crit'])
        pf_f = flag(pf_s, THRESH['pf_warn'], THRESH['pf_crit'])

        last = str(row.get('last_trade') or '')[:10]

        L(f'   {label} | {n:>4} trades | WR {wr_f}{wr_s:5.1f}% | PF {pf_f}{pf_s:.2f} | '
          f'PnL ${p:+8.2f} | avg_win=${aw:+.2f} avg_loss=${al:+.2f} | último: {last}')

    # Señales generadas (incluyendo rechazadas por RM)
    if signals_by_strat:
        L('')
        L(f'   --- Señales generadas (incluyendo rechazadas por RiskManager) ---')
        for s in signals_by_strat:
            L(f'     {(s.get("strategy") or "?"):<22} | '
              f'{s.get("total_signals"):>5} señales | '
              f'score_avg={s.get("avg_score") or 0:.1f} | '
              f'confluence_avg={s.get("avg_confluence") or 0:.2f}')

    L('')

    # Por asset
    L(f'   --- Por Asset ---')
    L('')
    for a in trading_by_asset:
        asset  = a.get('asset') or '?'
        n      = a.get('total') or 0
        w      = a.get('wins') or 0
        p      = a.get('total_pnl') or 0
        gp_a   = a.get('gross_profit') or 0
        gl_a   = a.get('gross_loss') or 0
        wr_a   = pct(w, n)
        pf_a   = pf_calc(gp_a, gl_a)
        wr_f   = flag(wr_a / 100, THRESH['wr_warn'], THRESH['wr_crit'])
        pf_f   = flag(pf_a, THRESH['pf_warn'], THRESH['pf_crit'])
        L(f'     {asset:<5} | {n:>4} trades | WR {wr_f}{wr_a:5.1f}% | PF {pf_f}{pf_a:.2f} | PnL ${p:+8.2f}')

    L('')

    # Distribución de cierres
    L(f'   --- Razones de Cierre ---')
    total_closed = sum((r.get('cnt') or 0) for r in close_reasons)
    for cr in close_reasons:
        reason = cr.get('close_reason') or 'UNKNOWN'
        cnt    = cr.get('cnt') or 0
        p_cr   = cr.get('pnl_sum') or 0
        pct_cr = pct(cnt, total_closed)
        L(f'     {reason:<16} | {cnt:>4} ({pct_cr:5.1f}%) | PnL ${p_cr:+,.2f}')

    # Últimos trades
    if recent_trades:
        L('')
        L(f'   --- Últimos {len(recent_trades)} Trades ---')
        for t in recent_trades:
            icon = '✓' if (t.get('pnl') or 0) > 0 else '✗'
            L(f'     {icon} {t.get("asset","?"):<5} {t.get("side","?"):<4} | '
              f'${(t.get("pnl") or 0):+7.2f} | {(t.get("close_reason") or "?"):<14} | '
              f'{(t.get("strategy") or "?"):<22} | {str(t.get("timestamp_close") or "")[:16]}')

    L('')
    L(SEP2)

    # ── 2. POLYMARKET AGENT ──────────────────────────────────
    L('')
    L(f'## 2. POLYMARKET AGENT')

    if poly_session:
        ps_name  = poly_session.get('session_name', 'N/A')
        ps_start = str(poly_session.get('started_at', ''))[:10]
        ps_bal   = poly_session.get('current_balance') or poly_session.get('initial_balance') or 0
        L(f'   Sesión: {ps_name} | Inicio: {ps_start} | Balance: ${ps_bal:,.2f}')
        L('')

        pg = poly_global
        p_total = pg.get('total') or 0
        p_wins  = pg.get('wins') or 0
        p_pnl   = pg.get('total_pnl') or 0
        p_aw    = pg.get('avg_win') or 0
        p_al    = pg.get('avg_loss') or 0
        p_gp    = pg.get('gross_profit') or 0
        p_gl    = pg.get('gross_loss') or 0
        p_edge  = pg.get('avg_declared_edge') or 0

        if p_total > 0:
            p_wr   = pct(p_wins, p_total)
            p_pf   = pf_calc(p_gp, p_gl)
            p_wr_f = flag(p_wr / 100, THRESH['poly_wr_warn'], THRESH['poly_wr_crit'])
            p_pf_f = flag(p_pf, THRESH['pf_warn'], THRESH['pf_crit'])
            L(f'   Métricas globales ({p_total} trades):')
            L(f'     WR:              {p_wr_f} {p_wr:.1f}%')
            L(f'     Profit Factor:   {p_pf_f} {p_pf:.3f}')
            L(f'     PnL total:       {"🟢" if p_pnl > 0 else "🔴"} ${p_pnl:+,.2f}')
            L(f'     Avg win:         ${p_aw:+.2f} | Avg loss: ${p_al:+.2f}')
            L(f'     Edge declarado (avg): {p_edge*100:.1f}%')
        else:
            L('   Sin trades cerrados en sesión activa.')

        L('')
        L(f'   --- Por Estrategia Polymarket ---')
        L('')

        POLY_STRATEGY_LABEL = {
            'SIGNAL_BASED':      'Signal Based      ',
            'TAIL_END':          'Tail End          ',
            'LATE_ENTRY':        'Late Entry        ',
            'LEGGED_ARB':        'Legged Arb        ',
            'COMBINATORIAL_ARB': 'Combinatorial Arb ',
        }
        poly_known = {s.get('strategy') for s in poly_by_strat}

        for strat, label in POLY_STRATEGY_LABEL.items():
            row = next((s for s in poly_by_strat if s.get('strategy') == strat), None)
            if not row or (row.get('total') or 0) == 0:
                L(f'   {label} | Sin trades aún')
                continue

            n   = row.get('total') or 0
            w   = row.get('wins') or 0
            p   = row.get('total_pnl') or 0
            aw  = row.get('avg_win') or 0
            al  = row.get('avg_loss') or 0
            gp_ = row.get('gross_profit') or 0
            gl_ = row.get('gross_loss') or 0
            ed  = row.get('avg_declared_edge') or 0
            cf  = row.get('avg_confidence') or 0
            wr_ = pct(w, n)
            pf_ = pf_calc(gp_, gl_)
            wr_f = flag(wr_ / 100, THRESH['poly_wr_warn'], THRESH['poly_wr_crit'])
            pf_f = flag(pf_, THRESH['pf_warn'], THRESH['pf_crit'])

            # Edge realizado (proxy)
            total_invested = abs(gl_) + gp_
            edge_real = pct(p, total_invested) / 100 if total_invested > 0 else 0
            drift = ed - edge_real
            drift_flag = '🔴' if drift > 0.15 else '🟡' if drift > 0.08 else '🟢'

            L(f'   {label} | {n:>4} trades | WR {wr_f}{wr_:5.1f}% | PF {pf_f}{pf_:.2f} | '
              f'PnL ${p:+7.2f} | edge_dec={ed*100:.1f}% edge_real={drift_flag}{edge_real*100:.1f}%')

        # Posiciones abiertas
        if poly_open:
            L('')
            L(f'   --- Posiciones Abiertas ({len(poly_open)}) ---')
            for po in poly_open:
                L(f'     {po.get("strategy","?"):<20} | {po.get("side","?")} | '
                  f'entry={po.get("entry_price") or 0:.3f} | shares={po.get("shares") or 0:.1f} | '
                  f'cost=${po.get("cost_basis") or 0:.2f} | edge={po.get("edge") or 0:.1f}%')

        # Razones de cierre poly
        if poly_close_reasons:
            L('')
            L(f'   --- Razones de Cierre Polymarket ---')
            for cr in poly_close_reasons:
                reason = cr.get('close_reason') or 'UNKNOWN'
                cnt    = cr.get('cnt') or 0
                p_cr   = cr.get('pnl_sum') or 0
                L(f'     {reason:<20} | {cnt:>4} trades | PnL ${p_cr:+,.2f}')

    else:
        L('   Sin sesión Polymarket activa.')

    L('')
    L(SEP2)

    # ── 3. BTC DIRECTION AGENT ───────────────────────────────
    L('')
    L(f'## 3. BTC DIRECTION AGENT')
    L('')

    btcd_total = btcd_global.get('total') or 0
    btcd_wins  = btcd_global.get('wins') or 0
    btcd_pnl   = btcd_global.get('total_pnl') or 0
    btcd_gp    = btcd_global.get('gross_profit') or 0
    btcd_gl    = btcd_global.get('gross_loss') or 0

    if btcd_total > 0:
        btcd_wr  = pct(btcd_wins, btcd_total)
        btcd_pf  = pf_calc(btcd_gp, btcd_gl)
        wr_f = flag(btcd_wr / 100, 0.40, 0.30)
        pf_f = flag(btcd_pf, THRESH['pf_warn'], THRESH['pf_crit'])

        r50_total = btcd_rolling.get('total') or 0
        r50_wins  = btcd_rolling.get('wins') or 0
        r50_pnl   = btcd_rolling.get('total_pnl') or 0
        r50_wr    = pct(r50_wins, r50_total) if r50_total else 0

        L(f'   Histórico total ({btcd_total} trades):')
        L(f'     WR:            {wr_f} {btcd_wr:.1f}%')
        L(f'     Profit Factor: {pf_f} {btcd_pf:.3f}')
        L(f'     PnL total:     {"🟢" if btcd_pnl > 0 else "🔴"} ${btcd_pnl:+,.2f}')
        L('')
        L(f'   Rolling 50 trades ({r50_total} disponibles):')
        wr50_f = flag(r50_wr / 100, 0.40, 0.30)
        L(f'     WR rolling-50: {wr50_f} {r50_wr:.1f}% | PnL rolling: ${r50_pnl:+,.2f}')

        # Tendencia (mejorando / empeorando)
        if r50_total >= 20 and btcd_total >= 30:
            trend = 'mejorando ↑' if r50_wr > btcd_wr else 'empeorando ↓' if r50_wr < btcd_wr - 3 else 'estable →'
            L(f'     Tendencia:     {trend}')

        if btcd_by_dir:
            L('')
            L(f'   --- Por Dirección ---')
            for d in btcd_by_dir:
                dir_  = d.get('direction') or '?'
                n     = d.get('total') or 0
                w     = d.get('wins') or 0
                p     = d.get('pnl') or 0
                wr_d  = pct(w, n)
                L(f'     {dir_:<8} | {n:>4} trades | WR {wr_d:5.1f}% | PnL ${p:+,.2f}')
    else:
        L('   Sin trades registrados en btc_direction_trades.')

    L('')
    L(SEP2)

    # ── 4. REDIS / SISTEMA ──────────────────────────────────
    L('')
    L(f'## 4. ESTADO SISTEMA (Redis)')
    L('')
    if redis_state.get('error'):
        L(f'   ⚠️  Redis no disponible: {redis_state["error"]}')
    else:
        L(f'   Cooldowns activos:    {len(redis_state.get("cooldowns", []))}')
        L(f'   Halts activos:        {len(redis_state.get("halts", []))}')
        L(f'   Dedups activos:       {len(redis_state.get("dedups", []))}')
        L(f'   PG Bloqueadas:        {len(redis_state.get("pg_blocks", []))}')
        L(f'   PG Probation:         {len(redis_state.get("pg_prob", []))}')
        if redis_state.get('cooldowns'):
            L(f'   Cooldowns: {redis_state["cooldowns"]}')
        if redis_state.get('pg_blocks'):
            L(f'   PG Blocks: {redis_state["pg_blocks"]}')

    L('')
    L(SEP2)

    # ── 5. ANOMALÍAS DETECTADAS ──────────────────────────────
    L('')
    L(f'## 5. ANOMALÍAS Y ALERTAS DETECTADAS')
    L('')

    if not anomalies:
        L('   ✅ Sin anomalías detectadas — sistema operando dentro de parámetros.')
    else:
        for a in anomalies:
            L(f'   {a}')

    L('')
    L(SEP2)

    # ── 6. ANÁLISIS PROFUNDO — ESTRATEGIAS NUEVAS ────────────
    L('')
    L(f'## 6. ANÁLISIS ESTRATEGIAS NUEVAS (activadas Apr 25, 2026)')
    L('')

    for new_strat in ['SMC_ORDER_BLOCKS', 'BTC_MICROSTRUCTURE']:
        row = next((s for s in trading_by_strat if s.get('strategy') == new_strat), None)
        total_s = row.get('total') or 0 if row else 0
        sig_row = next((s for s in signals_by_strat if s.get('strategy') == new_strat), None)
        total_sig = sig_row.get('total_signals') or 0 if sig_row else 0
        label_s = STRATEGY_LABEL.get(new_strat, new_strat)

        L(f'   {label_s}:')
        L(f'     Estado:          {"EN RODAJE" if total_s < 10 else "EVALUABLE"}')
        L(f'     Señales generadas (tabla signals): {total_sig}')
        L(f'     Trades ejecutados: {total_s}')

        if total_s == 0 and total_sig == 0:
            L(f'     INFO: Sin actividad — régimen actual CHOPPY bloquea estas estrategias.')
            L(f'         SMC_ORDER_BLOCKS activa cuando: allow_trend=True OR allow_breakout=True')
            L(f'         BTC_MICROSTRUCTURE activa cuando: allow_trend=True OR allow_breakout=True OR allow_dip_buy=True')
            L(f'         Estado normal: esperando condición de mercado favorable')
        elif total_s == 0 and total_sig > 0:
            L(f'     ℹ️  Genera señales pero el RiskManager las rechaza — revisar parámetros')
        elif 0 < total_s < 10:
            row = row or {}
            wr_s_  = pct(row.get('wins') or 0, total_s)
            pnl_s_ = row.get('total_pnl') or 0
            L(f'     WR parcial:      {wr_s_:.1f}% | PnL parcial: ${pnl_s_:+.2f}')
            L(f'     Conclusión:      Insuficiente — necesita ≥10 trades para evaluar edge')
        else:
            # Comparar vs TrendMomentum (benchmark)
            bench = next((s for s in trading_by_strat if s.get('strategy') == 'TREND_MOMENTUM'), None)
            if bench:
                bench_wr = pct(bench.get('wins') or 0, bench.get('total') or 1)
                bench_pf = pf_calc(bench.get('gross_profit') or 0, bench.get('gross_loss') or 0)
                new_wr   = pct(row.get('wins') or 0, total_s)
                new_pf   = pf_calc(row.get('gross_profit') or 0, row.get('gross_loss') or 0)
                wr_delta = new_wr - bench_wr
                pf_delta = new_pf - bench_pf
                delta_wr_f = '↑' if wr_delta > 0 else '↓'
                delta_pf_f = '↑' if pf_delta > 0 else '↓'
                L(f'     vs TREND_MOMENTUM: WR {new_wr:.1f}% {delta_wr_f} ({wr_delta:+.1f}pp) | '
                  f'PF {new_pf:.2f} {delta_pf_f} ({pf_delta:+.2f})')
        L('')

    # Polymarket — SignalBased nueva
    poly_sig_row = next((s for s in poly_by_strat if s.get('strategy') == 'SIGNAL_BASED'), None)
    L(f'   Signal Based Poly (reemplaza arquitectura LLM):')
    if not poly_sig_row or (poly_sig_row.get('total') or 0) == 0:
        L(f'     Estado:    Sin trades aún')
        L(f'     Contexto:  Versión LLM generó -$581 en 43 trades. Esta versión usa')
        L(f'                señales BTC técnicas (BtcDirectionStrategy + MarketRegime)')
        L(f'                sin consultar LLM para decisiones de entrada.')
    else:
        n   = poly_sig_row.get('total') or 0
        w   = poly_sig_row.get('wins') or 0
        p   = poly_sig_row.get('total_pnl') or 0
        wr_ = pct(w, n)
        pf_ = pf_calc(poly_sig_row.get('gross_profit') or 0, poly_sig_row.get('gross_loss') or 0)
        L(f'     {n} trades | WR {wr_:.1f}% | PF {pf_:.2f} | PnL ${p:+.2f}')
        L(f'     Referencia pre-LLM: -$581 en 43 trades (WR ~16%). Delta vs nueva arch:')
        if p > -581 / 43 * n:
            L(f'     ✅ Mejora sobre versión LLM ({p:+.2f} vs ${-581/43*n:.2f} esperado con LLM)')
        else:
            L(f'     ⚠️  Rendimiento similar o peor que versión LLM — revisar filtros')
    L('')
    L(SEP2)

    # ── 7. EQUITY CURVE ─────────────────────────────────────
    L('')
    L(f'## 7. EQUITY CURVE — Trading Agent')
    L('')
    if daily_pnl_rows:
        cumulative = 0.0
        init_bal   = float(session.get('initial_balance') or 10000) if session else 10000.0
        balance    = init_bal
        max_abs    = max((abs(float(r.get('daily_pnl') or 0)) for r in daily_pnl_rows), default=1) or 1.0
        L(f'   {"Día":<12} | {"PnL día":>9} | {"Acumulado":>11} | {"Balance":>10} | Trades')
        L(f'   {"-"*12}-+-{"-"*9}-+-{"-"*11}-+-{"-"*10}-+-------')
        for row in daily_pnl_rows:
            day       = str(row.get('day', ''))[:10]
            daily     = float(row.get('daily_pnl') or 0)
            t_cnt     = row.get('trades') or 0
            cumulative += daily
            balance    += daily
            bar  = '█' * min(int(abs(daily) / max_abs * 10), 20)
            sign = '+' if daily >= 0 else ''
            L(f'   {day:<12} | {sign}{daily:>8.2f} | {cumulative:>+11.2f} | ${balance:>9,.2f} | {t_cnt:>3}')
    else:
        L('   Sin datos de equity curve disponibles.')

    L('')
    L(SEP)
    L(f'  Fin del informe — {ts}')
    L(SEP)

    return '\n'.join(lines)


# ─────────────────────────────────────────────────────────────
# 7. TELEGRAM SUMMARY (versión comprimida)
# ─────────────────────────────────────────────────────────────
def build_telegram_summary(
    session, portfolio,
    trading_global, trading_by_strat,
    poly_session, poly_global, poly_by_strat,
    btcd_global, btcd_rolling, anomalies
) -> str:
    ts = NOW.strftime('%Y-%m-%d %H:%M')
    crit = sum(1 for a in anomalies if a.level == 'CRIT')
    warn = sum(1 for a in anomalies if a.level == 'WARN')
    global_st = '🔴 ALERTA' if crit > 0 else '🟡 VIGILANCIA' if warn > 0 else '🟢 NORMAL'

    lines = [
        f'<b>📊 MONITOR DE ESTRATEGIAS — {ts}</b>',
        f'Estado: {global_st} | 🔴{crit} 🟡{warn}',
        '',
    ]

    # Portfolio
    if portfolio:
        bal = portfolio.get('total_balance') or 0
        dd  = (portfolio.get('drawdown_pct') or 0) * 100
        pnl = portfolio.get('pnl_total') or 0
        lines.append(f'💼 <b>Portfolio:</b> ${bal:,.2f} | PnL ${pnl:+,.2f} | DD {dd:.2f}%')

    # Trading sesión
    if session and trading_global.get('total'):
        total = trading_global.get('total') or 0
        wins  = trading_global.get('wins') or 0
        pnl   = trading_global.get('total_pnl') or 0
        wr    = pct(wins, total)
        pf    = pf_calc(trading_global.get('gross_profit') or 0, trading_global.get('gross_loss') or 0)
        lines.append(f'🤖 <b>Trading {session.get("session_name","?")}:</b> '
                     f'{total} trades | WR {wr:.1f}% | PF {pf:.2f} | PnL ${pnl:+,.2f}')

    # Top/Bottom estrategias trading
    sorted_strats = sorted(trading_by_strat, key=lambda s: s.get('total_pnl') or 0, reverse=True)
    if sorted_strats:
        best = sorted_strats[0]
        worst = sorted_strats[-1]
        lines.append(f'  ↑ Mejor: {best.get("strategy","?")} ${(best.get("total_pnl") or 0):+.2f}')
        if len(sorted_strats) > 1:
            lines.append(f'  ↓ Peor:  {worst.get("strategy","?")} ${(worst.get("total_pnl") or 0):+.2f}')

    lines.append('')

    # Polymarket
    if poly_session and poly_global.get('total'):
        p_total = poly_global.get('total') or 0
        p_wins  = poly_global.get('wins') or 0
        p_pnl   = poly_global.get('total_pnl') or 0
        p_wr    = pct(p_wins, p_total)
        p_pf    = pf_calc(poly_global.get('gross_profit') or 0, poly_global.get('gross_loss') or 0)
        lines.append(f'🎯 <b>Polymarket {poly_session.get("session_name","?")}:</b> '
                     f'{p_total} trades | WR {p_wr:.1f}% | PF {p_pf:.2f} | PnL ${p_pnl:+,.2f}')

    # BTC Direction
    btcd_total = btcd_global.get('total') or 0
    if btcd_total > 0:
        btcd_wr  = pct(btcd_global.get('wins') or 0, btcd_total)
        btcd_pnl = btcd_global.get('total_pnl') or 0
        r50_wr   = pct(btcd_rolling.get('wins') or 0, btcd_rolling.get('total') or 1)
        lines.append(f'📈 <b>BTC Direction:</b> {btcd_total} trades | WR {btcd_wr:.1f}% '
                     f'(rolling-50: {r50_wr:.1f}%) | PnL ${btcd_pnl:+,.2f}')

    lines.append('')

    # Anomalías críticas/warn
    if anomalies:
        lines.append('<b>⚠️ Alertas:</b>')
        for a in anomalies[:6]:  # máx 6 en telegram
            lines.append(f'  {a}')
        if len(anomalies) > 6:
            lines.append(f'  ... y {len(anomalies)-6} más (ver reporte completo)')

    lines.append('')
    lines.append(f'<i>Reporte completo: /opt/trading/reports/</i>')

    return '\n'.join(lines)


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='Monitor de estrategias de trading')
    parser.add_argument('--quick',      action='store_true', help='Solo consola, sin guardar reporte ni Telegram')
    parser.add_argument('--no-telegram', action='store_true', help='Genera reporte pero sin enviar a Telegram')
    args = parser.parse_args()

    print(f'\nRecopilando datos del sistema... ({NOW.strftime("%H:%M:%S UTC")})')

    # ── Cargar datos ──
    session         = get_active_session()
    session_start   = session.get('started_at') if session else (NOW - timedelta(days=90))
    portfolio       = get_portfolio_snapshot()
    open_trades     = get_open_trades()
    daily_pnl_rows  = get_daily_pnl(session_start)

    trading_global     = get_trading_global(session_start)
    trading_by_strat   = get_trading_by_strategy(session_start)
    trading_by_asset   = get_trading_by_asset(session_start)
    close_reasons      = get_close_reason_dist(session_start)
    signals_by_strat   = get_signals_by_strategy(session_start)
    recent_trades      = get_recent_trades(session_start)

    poly_session        = get_poly_active_session()
    poly_session_name   = poly_session.get('session_name') if poly_session else None
    poly_global         = get_poly_global(poly_session_name) if poly_session_name else {}
    poly_by_strat       = get_poly_by_strategy(poly_session_name) if poly_session_name else []
    poly_open           = get_poly_open(poly_session_name) if poly_session_name else []
    poly_close_reasons  = get_poly_close_reasons(poly_session_name) if poly_session_name else []

    btcd_global    = get_btcd_global()
    btcd_rolling   = get_btcd_rolling(50)
    btcd_by_dir    = get_btcd_by_direction()

    redis_state    = get_redis_state()

    # ── Detección de anomalías ──
    anomalies = detect_anomalies(
        trading_by_strat, poly_by_strat, btcd_global, btcd_rolling,
        portfolio, redis_state, session, poly_session
    )

    # ── Construir informe completo ──
    report = build_report(
        session, portfolio, open_trades, daily_pnl_rows,
        trading_global, trading_by_strat, trading_by_asset, close_reasons,
        signals_by_strat, recent_trades,
        poly_session, poly_global, poly_by_strat, poly_open, poly_close_reasons,
        btcd_global, btcd_rolling, btcd_by_dir,
        redis_state, anomalies
    )

    print(report)

    if not args.quick:
        # Guardar reporte
        ts_file = NOW.strftime('%Y%m%d_%H%M')
        report_path = REPORTS_DIR / f'strategy_monitor_{ts_file}.txt'
        report_path.write_text(report, encoding='utf-8')
        print(f'\n✓ Reporte guardado: {report_path}')

        # Telegram
        if not args.no_telegram:
            summary = build_telegram_summary(
                session, portfolio,
                trading_global, trading_by_strat,
                poly_session, poly_global, poly_by_strat,
                btcd_global, btcd_rolling, anomalies
            )
            send_telegram(summary)
            print('✓ Resumen enviado a Telegram.')


if __name__ == '__main__':
    main()
