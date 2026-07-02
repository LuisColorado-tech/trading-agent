#!/usr/bin/env python3
"""
preflight_live.py — Verificación previa a operar con el cost model activo.

Corre en la VPS (venv/bin/python3 scripts/preflight_live.py) y valida que
el sistema esté listo para paper/live con costos reales:

  1. FEES REALES: compara FEE_SCHEDULES (core/cost_model.py) contra los fees
     que reporta cada exchange vía ccxt. Si difieren más del umbral, FALLA —
     el supuesto del modelo está desactualizado y el gate de RR neto miente.
  2. DB: columnas pnl_gross/fee_paid existen (migración 007 aplicada).
  3. ASSET_MAP: todo activo configurado resuelve a un exchange con fee schedule.
  4. GRIDS: viabilidad neta de cada perfil GRID_STABLE en los extremos de su
     rango (reporta qué pares van a operar y cuáles quedan silenciados).
  5. ENV: PAPER_TRADING y credenciales presentes.

Exit code 0 = listo. 1 = hay bloqueadores (no fondear/arrancar).
"""
import os
import sys

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

from core.cost_model import (
    FEE_SCHEDULES, MIN_NET_RR_RATIO, get_fee_schedule, round_trip_cost_pct,
)

# Tolerancia de drift entre el fee asumido y el real del exchange.
# 5 bps: un tier de volumen distinto ya lo dispara — eso es intencional,
# el gate de RR neto es tan bueno como el fee que asume.
FEE_DRIFT_TOLERANCE = 0.0005

_failures: list[str] = []
_warnings: list[str] = []


def _ok(msg): print(f'  ✅ {msg}')
def _warn(msg): print(f'  🟡 {msg}'); _warnings.append(msg)
def _fail(msg): print(f'  ❌ {msg}'); _failures.append(msg)


# ── 1. Fees reales vs FEE_SCHEDULES ────────────────────────────────

def check_live_fees():
    print('\n[1/5] Fees reales del exchange vs core/cost_model.py')
    import ccxt

    # Par representativo por exchange para leer maker/taker del mercado.
    probes = {
        'kraken': 'BTC/USDT',
        'okx': 'BTC/USDT',
    }
    for exc_name, symbol in probes.items():
        assumed = FEE_SCHEDULES[exc_name]
        try:
            exchange = getattr(ccxt, exc_name)({'enableRateLimit': True})
            markets = exchange.load_markets()
            market = markets.get(symbol)
            if not market:
                _warn(f'{exc_name}: {symbol} no listado, no se pudo verificar fee')
                continue
            live_maker = market.get('maker')
            live_taker = market.get('taker')
            if live_maker is None or live_taker is None:
                _warn(f'{exc_name}: ccxt no expone maker/taker para {symbol}')
                continue
            for kind, live, ours in (('maker', live_maker, assumed.maker_pct),
                                     ('taker', live_taker, assumed.taker_pct)):
                drift = abs(live - ours)
                if drift > FEE_DRIFT_TOLERANCE:
                    _fail(f'{exc_name} {kind}: real={live:.4%} asumido={ours:.4%} '
                          f'(drift {drift:.4%}) → actualizar FEE_SCHEDULES')
                else:
                    _ok(f'{exc_name} {kind}: real={live:.4%} ≈ asumido={ours:.4%}')
        except Exception as e:
            _warn(f'{exc_name}: no se pudo consultar fees en vivo ({e}). '
                  f'Verificar manualmente antes de fondear.')

    # Nota: los fees por API reflejan el tier PÚBLICO/base. Si la cuenta tiene
    # tier de volumen, verificar en la web del exchange con sesión iniciada.
    print('  ℹ️  ccxt reporta el tier base; con volumen 30d el fee real puede ser menor (nunca mayor).')


# ── 2. Columnas de DB ──────────────────────────────────────────────

def check_db_columns():
    print('\n[2/5] Columnas pnl_gross/fee_paid en tabla trades (migración 007)')
    try:
        from sqlalchemy import create_engine, text
        db_url = os.environ.get('DB_URL')
        if not db_url:
            user = os.getenv('POSTGRES_USER'); pw = os.getenv('POSTGRES_PASSWORD')
            host = os.getenv('POSTGRES_HOST', 'localhost'); db = os.getenv('POSTGRES_DB')
            if not all([user, pw, db]):
                _fail('Sin DB_URL ni POSTGRES_* en config/.env')
                return
            db_url = f'postgresql://{user}:{pw}@{host}/{db}'
        engine = create_engine(db_url)
        with engine.connect() as conn:
            rows = conn.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = 'trades'
                  AND column_name IN ('pnl_gross', 'fee_paid')
            """)).fetchall()
        found = {r[0] for r in rows}
        for col in ('pnl_gross', 'fee_paid'):
            if col in found:
                _ok(f'trades.{col} existe')
            else:
                _fail(f'trades.{col} NO existe → correr db/migrations/007_trade_costs.sql')
    except Exception as e:
        _fail(f'No se pudo consultar la DB: {e}')


# ── 3. ASSET_MAP → fee schedule ────────────────────────────────────

def check_asset_map_coverage():
    print('\n[3/5] Todo activo configurado tiene fee schedule')
    from data.market_feed import ASSET_MAP
    for asset, info in sorted(ASSET_MAP.items()):
        exc = info.get('exchange')
        try:
            get_fee_schedule(exc)
            _ok(f'{asset} → {exc} (round-trip {round_trip_cost_pct(exc):.2%})')
        except KeyError:
            _fail(f'{asset} → {exc}: SIN fee schedule en core/cost_model.py')


# ── 4. Viabilidad de grids ─────────────────────────────────────────

def check_grid_viability():
    print('\n[4/5] Viabilidad neta de perfiles GRID_STABLE')
    from core.grid_stable_profiles import GRID_STABLE_PROFILES
    for name, p in GRID_STABLE_PROFILES.items():
        cost = round_trip_cost_pct(p.exchange)
        results = []
        for range_pct in (p.min_range_pct, p.max_range_pct):
            spacing = range_pct / (p.grid_levels + 1)
            net_rr = (spacing * p.tp_ratio - cost) / (spacing * p.sl_ratio)
            results.append(net_rr)
        lo, hi = results
        if lo >= MIN_NET_RR_RATIO:
            _ok(f'{name}: net RR {lo:.2f}–{hi:.2f} en todo el rango → OPERABLE')
        elif hi >= MIN_NET_RR_RATIO:
            _warn(f'{name}: net RR {lo:.2f}–{hi:.2f} → viable solo en parte del rango, '
                  f'esperar pocas señales')
        else:
            _warn(f'{name}: net RR {lo:.2f}–{hi:.2f} → NO viable, el gate silenciará '
                  f'este par (protegido, no productivo)')


# ── 5. Entorno ─────────────────────────────────────────────────────

def check_env():
    print('\n[5/5] Entorno')
    paper = os.getenv('PAPER_TRADING', 'true').lower()
    if paper == 'true':
        _ok('PAPER_TRADING=true (modo seguro)')
    else:
        _warn('PAPER_TRADING != true — MODO LIVE. Confirmar que es intencional '
              'y que el checklist de docs/FEASIBILITY_STUDY.md §5 está completo.')
    for var in ('POSTGRES_DB', 'REDIS_HOST'):
        if os.getenv(var):
            _ok(f'{var} configurado')
        else:
            _warn(f'{var} no configurado')


def main():
    print('═' * 60)
    print(' PREFLIGHT LIVE — cost model + gates de RR neto')
    print('═' * 60)

    check_live_fees()
    check_db_columns()
    check_asset_map_coverage()
    check_grid_viability()
    check_env()

    print('\n' + '═' * 60)
    if _failures:
        print(f' ❌ {len(_failures)} BLOQUEADOR(ES) — NO arrancar/fondear:')
        for f in _failures:
            print(f'   - {f}')
        sys.exit(1)
    if _warnings:
        print(f' 🟡 Listo con {len(_warnings)} advertencia(s) — revisar arriba.')
    else:
        print(' ✅ Todo verificado — listo para operar.')
    sys.exit(0)


if __name__ == '__main__':
    main()
