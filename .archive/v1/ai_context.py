"""
ai_context.py — Briefing completo del sistema para GitHub Copilot / IA.

Ejecutar cuando se inicia una sesión de asistencia con IA:

    cd /opt/trading && venv/bin/python3 scripts/ai_context.py

Imprime TODO el contexto necesario para que la IA se ubique:
  - Arquitectura y archivos clave
  - Sesión paper activa (balance, trades, PnL, WR)
  - Trades abiertos
  - Últimos 10 trades cerrados
  - Perfiles de assets (AssetProfile)
  - Estado PerformanceGuard
  - Estado Redis (cooldowns, dedups)
  - Configuración de estrategias activas
  - Régimen de mercado actual
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, '/opt/trading')

from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

from sqlalchemy import create_engine, text
import redis as redis_lib

SEP = '─' * 60


def section(title: str):
    print(f'\n{SEP}')
    print(f'  {title}')
    print(SEP)


def db_engine():
    return create_engine(
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT','5432')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )


def redis_client():
    return redis_lib.Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        password=os.getenv('REDIS_PASSWORD') or None,
        decode_responses=True,
    )


# ══════════════════════════════════════════════════════════════
# 1. SISTEMA
# ══════════════════════════════════════════════════════════════
section('SISTEMA')
print(f'  Python:    {sys.version.split()[0]}')
print(f'  Venv:      /opt/trading/venv/')
print(f'  Timestamp: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M %Z")}')
print(f'  Paper:     {os.getenv("PAPER_TRADING", "true")}')
print()
print('  Archivos CLAVE:')
KEY_FILES = [
    ('StrategyEngine',    'agents/strategy_engine.py'),
    ('TradeMonitor',      'agents/trade_monitor.py'),
    ('ExecutionAgent',    'agents/execution_agent.py'),
    ('RiskManager',       'risk/risk_manager.py'),
    ('MarketRegime',      'core/market_regime.py'),
    ('AssetProfiles',     'core/asset_profiles.py'),
    ('PerformanceGuard',  'core/performance_guard.py'),
    ('TrendMomentum',     'strategies/trend_momentum.py'),
    ('Breakout',          'strategies/breakout.py'),
    ('MeanReversion',     'strategies/mean_reversion.py'),
    ('BtcDipBuyer',       'strategies/btc_dip_buyer.py'),
    ('MarketFeed',        'data/market_feed.py'),
    ('SessionManager',    'core/paper_session_manager.py'),
    ('SessionJournal',    'core/session_journal.py'),
    ('RunTrading',        'scripts/run_trading.py'),
]
for label, path in KEY_FILES:
    exists = '✓' if os.path.exists(f'/opt/trading/{path}') else '✗'
    print(f'    {exists} {label:<18} → {path}')

print()
print('  Comandos de ejecución:')
print('    Trading principal:  venv/bin/python3 scripts/run_trading.py')
print('    Backtest:           venv/bin/python3 scripts/backtest.py')
print('    Health check:       venv/bin/python3 scripts/health_check.py')
print('    Gestión sesión:     venv/bin/python3 scripts/manage_paper_session.py --help')


# ══════════════════════════════════════════════════════════════
# 2. SESIONES PAPER
# ══════════════════════════════════════════════════════════════
section('SESIONES PAPER (últimas 5)')
engine = db_engine()

try:
    with engine.connect() as conn:
        sessions = conn.execute(text("""
            SELECT session_name, status, initial_balance, final_balance,
                   total_trades, winning_trades, started_at, ended_at
            FROM paper_sessions
            ORDER BY started_at DESC LIMIT 5
        """)).fetchall()

    for s in sessions:
        active_marker = ' ← ACTIVA' if s.status == 'ACTIVE' else ''
        pnl = (s.final_balance - s.initial_balance) if s.final_balance else None
        wr = (s.winning_trades / s.total_trades * 100) if s.total_trades else 0
        pnl_str = f'PnL=${pnl:+.2f}' if pnl is not None else 'en curso'
        print(f'  {s.session_name}: {s.status}{active_marker}')
        print(f'    Inicio: {str(s.started_at)[:16]} UTC | Trades: {s.total_trades} | WR: {wr:.1f}% | {pnl_str}')
        print(f'    Balance: ${s.initial_balance:,.2f} → ${s.final_balance:,.2f}' if s.final_balance else f'    Balance inicial: ${s.initial_balance:,.2f}')
        print()
except Exception as e:
    print(f'  ERROR DB: {e}')


# ══════════════════════════════════════════════════════════════
# 3. ESTADO ACTUAL: PORTFOLIO + TRADES ABIERTOS
# ══════════════════════════════════════════════════════════════
section('PORTFOLIO ACTUAL + TRADES ABIERTOS')
try:
    with engine.connect() as conn:
        port = conn.execute(text("""
            SELECT total_balance, available_cash, exposure_pct, drawdown_pct, pnl_total, peak_balance
            FROM portfolio ORDER BY timestamp DESC LIMIT 1
        """)).fetchone()

        sess = conn.execute(text(
            "SELECT * FROM paper_sessions WHERE status='ACTIVE' ORDER BY started_at DESC LIMIT 1"
        )).fetchone()

        open_trades = conn.execute(text(
            "SELECT asset, side, entry_price, stop_loss, take_profit, position_size, strategy, timestamp_open "
            "FROM trades WHERE status='OPEN' ORDER BY timestamp_open"
        )).fetchall()

    if port:
        print(f'  Balance total:    ${port.total_balance:,.2f}')
        print(f'  Cash disponible:  ${port.available_cash:,.2f}')
        print(f'  Exposición:       {port.exposure_pct*100:.1f}%')
        print(f'  Drawdown actual:  {port.drawdown_pct*100:.2f}%')
        print(f'  PnL total:        ${port.pnl_total:+,.2f}')

    print(f'\n  Trades abiertos: {len(open_trades)}')
    if open_trades:
        for t in open_trades:
            risk = abs(t.entry_price - t.stop_loss)
            rr = abs(t.take_profit - t.entry_price) / risk if risk > 0 else 0
            print(f'    {t.asset} {t.side} | entry={t.entry_price:.4f} | SL={t.stop_loss:.4f} | '
                  f'TP={t.take_profit:.4f} | RR={rr:.2f} | strat={t.strategy}')
            print(f'      abierto: {str(t.timestamp_open)[:16]} UTC | size={t.position_size:.4f}')
    else:
        print('    (ninguno)')
except Exception as e:
    print(f'  ERROR DB: {e}')


# ══════════════════════════════════════════════════════════════
# 4. ÚLTIMOS 15 TRADES CERRADOS (sesión activa)
# ══════════════════════════════════════════════════════════════
section('ÚLTIMOS 15 TRADES CERRADOS (sesión activa)')
try:
    with engine.connect() as conn:
        if sess:
            recent = conn.execute(text("""
                SELECT asset, side, strategy, entry_price, exit_price, pnl, close_reason, timestamp_close
                FROM trades
                WHERE status='CLOSED' AND paper_trade=true AND timestamp_open >= :s
                ORDER BY timestamp_close DESC LIMIT 15
            """), {'s': sess.started_at}).fetchall()

            # Stats globales sesión activa
            stats = conn.execute(text("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) as wins,
                       SUM(pnl) as total_pnl,
                       AVG(CASE WHEN pnl>0 THEN pnl END) as avg_win,
                       AVG(CASE WHEN pnl<=0 THEN pnl END) as avg_loss
                FROM trades
                WHERE status='CLOSED' AND paper_trade=true AND timestamp_open >= :s
            """), {'s': sess.started_at}).fetchone()

            if stats.total:
                wr = stats.wins / stats.total * 100
                print(f'  Stats sesión activa: {stats.total} trades | WR={wr:.1f}% | '
                      f'PnL=${stats.total_pnl:+.2f} | '
                      f'avg_win=${stats.avg_win or 0:+.2f} | avg_loss=${stats.avg_loss or 0:+.2f}')
            print()

            for t in recent:
                icon = '✓' if t.pnl > 0 else '✗'
                print(f'  {icon} {t.asset:<5} {t.side:<4} | ${t.pnl:+7.2f} | {t.close_reason:<14} | '
                      f'{str(t.timestamp_close)[:16]} | {t.strategy}')
        else:
            print('  (no hay sesión activa)')
except Exception as e:
    print(f'  ERROR DB: {e}')


# ══════════════════════════════════════════════════════════════
# 5. ASSET PROFILES
# ══════════════════════════════════════════════════════════════
section('ASSET PROFILES (core/asset_profiles.py)')
try:
    from core.asset_profiles import get_profile, hour_allowed, direction_allowed, ASSET_PROFILES
    hour_utc = datetime.now(timezone.utc).hour
    print(f'  Hora actual: {hour_utc}h UTC\n')
    print(f'  {"Asset":<5} {"SL×":<5} {"TP×":<5} {"Trail@":<8} {"Step":<6} {"Conf":<5} {"CanClose":<9} {"Estado":<10} Bloqueadas')
    for asset, profile in ASSET_PROFILES.items():
        h_ok = hour_allowed(asset, hour_utc)
        d_ok = direction_allowed(asset, 'SELL')
        estado = '✓ OK' if (h_ok and d_ok) else '⏸ HORA'
        blocked = sorted(profile.blocked_hours_utc) if profile.blocked_hours_utc else []
        print(f'  {asset:<5} {profile.sl_multiplier:<5} {profile.tp_multiplier:<5} '
              f'{profile.trailing_activation_r:<8} {profile.trailing_step_r:<6} '
              f'{profile.confluence_min:<5} {str(profile.require_candle_close):<9} '
              f'{estado:<10} {blocked}')
    print()
    print('  allowed_directions por asset (todos: SELL):')
    for asset, profile in ASSET_PROFILES.items():
        print(f'    {asset}: {sorted(profile.allowed_directions)}')
except Exception as e:
    print(f'  ERROR: {e}')


# ══════════════════════════════════════════════════════════════
# 6. PERFORMANCE GUARD
# ══════════════════════════════════════════════════════════════
section('PERFORMANCE GUARD')
try:
    from core.performance_guard import StrategyPerformanceGuard
    db_url = (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT','5432')}/{os.getenv('POSTGRES_DB')}"
    )
    guard = StrategyPerformanceGuard(db_url)

    blocked_any = False
    for strat in ['TREND_MOMENTUM', 'BREAKOUT', 'MEAN_REVERSION', 'BTC_DIP_BUYER']:
        probation = guard.is_on_probation(strat)
        reason = guard.assess_signal('BTC', strat)
        if reason or probation:
            blocked_any = True
            label = 'PROBATION' if probation else 'BLOQUEADO'
            print(f'  ⚠ {strat}: {label} → {reason or "riesgo reducido 50%"}')
    if not blocked_any:
        print('  ✓ Todas las estrategias desbloqueadas')
except Exception as e:
    print(f'  ERROR: {e}')


# ══════════════════════════════════════════════════════════════
# 7. REDIS — COOLDOWNS Y DEDUPS
# ══════════════════════════════════════════════════════════════
section('REDIS — COOLDOWNS & DEDUPS ACTIVOS')
try:
    r = redis_client()
    cooldowns = r.keys('cooldown:*')
    dedups = r.keys('dedup:*')
    halts = r.keys('halt:*')

    if cooldowns:
        print('  Cooldowns activos (asset bloqueado tras SL):')
        for k in sorted(cooldowns):
            ttl = r.ttl(k)
            print(f'    {k}: {ttl//60}min restantes')
    else:
        print('  Cooldowns: ninguno')

    if dedups:
        print('  Dedups activos (dirección bloqueada):')
        for k in sorted(dedups):
            ttl = r.ttl(k)
            print(f'    {k}: {ttl//3600:.1f}h restantes')
    else:
        print('  Dedups: ninguno')

    if halts:
        print('  ⚠ HALTS activos:')
        for k in sorted(halts):
            print(f'    {k}')
    else:
        print('  Halts: ninguno')
except Exception as e:
    print(f'  ERROR Redis: {e}')


# ══════════════════════════════════════════════════════════════
# 8. RÉGIMEN DE MERCADO ACTUAL (último dato 15m)
# ══════════════════════════════════════════════════════════════
section('RÉGIMEN DE MERCADO ACTUAL')
try:
    from data.market_feed import MarketFeed
    from agents.indicators import IndicatorEngine
    from core.market_regime import classify_market_regime

    feed = MarketFeed()
    print(f'  {"Asset":<5} {"Precio":>10} {"RSI":>6} {"ATR%":>6} {"Trend":>12} {"Régimen"}')
    for asset in ['BTC', 'ETH', 'SOL', 'AVAX', 'INJ', 'XAU', 'XAG']:
        try:
            df = feed.get_latest(asset, '15m', n=100)
            if df.empty:
                print(f'  {asset:<5}  sin datos')
                continue
            ind = IndicatorEngine.calculate(df, asset, '15m')
            if ind is None:
                print(f'  {asset:<5}  indicadores insuficientes')
                continue
            regime = classify_market_regime(ind)
            print(f'  {asset:<5} {ind.close:>10.4f} {ind.rsi:>6.1f} {ind.atr_pct*100:>5.2f}% '
                  f'{ind.trend_direction:>12} {regime.name}')
        except Exception as inner_e:
            print(f'  {asset:<5}  error: {inner_e}')
except Exception as e:
    print(f'  ERROR: {e}')


# ══════════════════════════════════════════════════════════════
# 9. ESTRATEGIAS — CONFIGURACIÓN ACTIVA
# ══════════════════════════════════════════════════════════════
section('ESTRATEGIAS CONFIGURADAS')
print("""
  ACTIVAS:
    ✓ TREND_MOMENTUM — SELL | MIN_SCORE=65 | EMA_cross + RSI[25-45] + MACD + Vol
      SL/TP: por AssetProfile (ver sección 5)
      Blocking: BUY bloqueado por market_regime (TREND_UP → no BUY)

  INACTIVAS / BLOQUEADAS POR RÉGIMEN:
    ✗ MEAN_REVERSION — 0% WR paper, -$569 PnL histórico → comentada
    ✗ BTC_DIP_BUYER  — requiere BULL_DIP regime (29% WR en 15m) → inactiva por diseño
    ✗ BREAKOUT       — vol_ratio ≥ 2.0 muy estricto → casi nunca dispara

  MARKET REGIME (market_regime.py):
    TREND_DOWN  → permite TREND_MOMENTUM SELL (+ bonus +8 score)
    TREND_UP    → bloquea TREND_MOMENTUM BUY (pérdida -$6,151 en 2Y backtest)
    RANGE/CHOP  → CHOPPY → salida temprana sin evaluar estrategias

  RISK MANAGER (risk/risk_manager.py):
    MAX_RISK_PER_TRADE_PCT   = 0.5%  (del portafolio)
    MAX_CONCURRENT_TRADES    = 3
    MAX_PORTFOLIO_EXPOSURE   = 5%
    SL_COOLDOWN_MINUTES      = 60
    SIGNAL_DEDUP_HOURS       = 4
    MIN_RR_RATIO             = 1.5
""")


# ══════════════════════════════════════════════════════════════
# 10. PERFORMANCE POR ASSET (sesión activa)
# ══════════════════════════════════════════════════════════════
section('PERFORMANCE POR ASSET (sesión activa)')
try:
    with engine.connect() as conn:
        if sess:
            per_asset = conn.execute(text("""
                SELECT asset,
                       COUNT(*) as trades,
                       SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END) as wins,
                       SUM(pnl) as total_pnl,
                       AVG(pnl) as avg_pnl
                FROM trades
                WHERE status='CLOSED' AND paper_trade=true AND timestamp_open >= :s
                GROUP BY asset ORDER BY total_pnl DESC
            """), {'s': sess.started_at}).fetchall()

            print(f'  {"Asset":<6} {"Trades":>7} {"WR%":>6} {"PnL":>9} {"avg/trade":>10}')
            for r in per_asset:
                wr = r.wins / r.trades * 100 if r.trades else 0
                print(f'  {r.asset:<6} {r.trades:>7} {wr:>5.1f}% {r.total_pnl:>+9.2f} {r.avg_pnl:>+10.2f}')
        else:
            print('  (sesión activa sin trades aún)')
except Exception as e:
    print(f'  ERROR: {e}')


# ══════════════════════════════════════════════════════════════
print(f'\n{"═"*60}')
print('  BRIEFING COMPLETADO — Usa esta info para ubicarte')
print('  Backtest histórico: reports/backtest_15m_24m*.csv')
print()
print('  ── Documentación IA (leer en este orden) ──────────────')
AI_DOCS = [
    ('AI_MASTER.md',               'Entry point: VPS, stack, 4 agentes, servicios, comandos'),
    ('AI_TRADING_AGENT.md',        'Trading Agent: risk rules, regímenes, asset profiles, SESSION_008'),
    ('AI_OPTIONS_AGENT.md',        'Options Theta Farming: filtros, ciclo de vida, margen Deribit'),
    ('AI_POLYMARKET_AGENT.md',     'Polymarket SIGNAL_BASED: edge, sizing, PREDICTION_LLM desactivado'),
    ('AI_BTC_DIRECTION_AGENT.md',  'BTC Direction: multi-TF, bug history, WR 27.6%, backfill'),
]
for fname, desc in AI_DOCS:
    fpath = f'/opt/trading/docs/{fname}'
    exists = '✓' if os.path.exists(fpath) else '✗'
    print(f'  {exists} docs/{fname}')
    print(f'      {desc}')
print()
print('  Docs legacy: docs/ARCHITECTURE.md | docs/AUDIT_PIPELINE.md')
print(f'{"═"*60}\n')
