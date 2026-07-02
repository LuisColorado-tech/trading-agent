"""
CostModel — Fees, spread y slippage reales por exchange/activo.

Punto único de verdad para "cuánto cuesta realmente entrar y salir de un trade".
Antes de este módulo, todo el stack (execution_agent, trade_monitor,
grid_stable_agent, risk_manager, backtests) asumía fill perfecto al precio
de la señal, sin comisión ni slippage. Eso sobreestimaba el PnL de toda
estrategia de alta frecuencia (grids) y subestimaba el edge mínimo necesario
para que un trade valga la pena.

⚠️ Las tasas de abajo son de referencia (conocimiento general de cada
exchange, no verificadas en vivo en esta sesión). ANTES de usar este modelo
para aprobar capital real, confirmar en la página de fees de cada exchange
con la cuenta y el volumen 30d reales:
  - Kraken:  https://www.kraken.com/features/fee-schedule
  - OKX:     https://www.okx.com/fees
  - Alpaca:  https://alpaca.markets/support/what-are-the-fees  (SEC/FINRA pass-through)
  - Deribit: https://www.deribit.com/pages/information/fees
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class FeeSchedule:
    maker_pct: float          # comisión maker, como fracción (0.0016 = 0.16%)
    taker_pct: float          # comisión taker, como fracción
    slippage_pct: float       # slippage esperado en market order, como fracción del notional
    withdraw_fixed_usd: float = 0.0  # costo fijo de retiro/red (no aplica por trade, informativo)


# ─── Fee schedules por exchange (ASUNCIÓN — verificar antes de operar real) ──
FEE_SCHEDULES: dict[str, FeeSchedule] = {
    # Kraken spot, tier base (<$50k vol 30d). Pares USDT.
    'kraken': FeeSchedule(maker_pct=0.0016, taker_pct=0.0026, slippage_pct=0.0008),
    # OKX spot, tier regular (no VIP). Peor liquidez en XAUT/XAG que Kraken en BTC/ETH.
    'okx': FeeSchedule(maker_pct=0.0008, taker_pct=0.0010, slippage_pct=0.0015),
    # Alpaca: $0 comisión nominal, pero SEC fee + FINRA TAF en ventas + spread bid/ask real.
    'alpaca': FeeSchedule(maker_pct=0.0000, taker_pct=0.0000, slippage_pct=0.0010),
    # Deribit options/futures: fee cobrado en BTC, aproximado aquí como % del notional.
    'deribit': FeeSchedule(maker_pct=0.0000, taker_pct=0.0004, slippage_pct=0.0020),
    # Polymarket: 0% fee de trading, pero libro delgado → slippage relevante.
    'polymarket': FeeSchedule(maker_pct=0.0000, taker_pct=0.0000, slippage_pct=0.0100),
}

# Estrategias que sólo colocan market orders (SL, breakout, la mayoría de entradas
# reactivas a señal) pagan taker en ambos lados. Grids con límite en el nivel
# pueden pagar maker en la entrada — ajustar por estrategia si se confirma el tipo
# de orden real usado en cada executor.
DEFAULT_ORDER_TYPE = 'taker'

# RR mínimo neto de costos para aprobar un trade. Compartido por RiskManager
# (crypto/stocks vía risk/risk_manager.py) y por estrategias con risk propio
# (GRID_STABLE vía strategies/grid_stable.py) — un solo umbral, no dos.
MIN_NET_RR_RATIO = 1.0


def get_fee_schedule(exchange: str) -> FeeSchedule:
    exchange = exchange.lower()
    if exchange not in FEE_SCHEDULES:
        raise KeyError(
            f"No hay fee schedule para '{exchange}'. "
            f"Definilo en core/cost_model.py antes de operar ese exchange."
        )
    return FEE_SCHEDULES[exchange]


def round_trip_cost_pct(exchange: str, entry_order_type: str = DEFAULT_ORDER_TYPE,
                         exit_order_type: str = DEFAULT_ORDER_TYPE) -> float:
    """% del notional que se pierde en fees + slippage entre abrir y cerrar un trade."""
    fs = get_fee_schedule(exchange)
    entry_fee = fs.maker_pct if entry_order_type == 'maker' else fs.taker_pct
    exit_fee = fs.maker_pct if exit_order_type == 'maker' else fs.taker_pct
    return entry_fee + exit_fee + (2 * fs.slippage_pct)


def trade_cost_usd(exchange: str, entry_notional: float, exit_notional: float,
                    entry_order_type: str = DEFAULT_ORDER_TYPE,
                    exit_order_type: str = DEFAULT_ORDER_TYPE) -> float:
    """Costo total en USD de un round-trip: fee+slippage de entrada + de salida."""
    fs = get_fee_schedule(exchange)
    entry_fee = fs.maker_pct if entry_order_type == 'maker' else fs.taker_pct
    exit_fee = fs.maker_pct if exit_order_type == 'maker' else fs.taker_pct
    entry_cost = entry_notional * (entry_fee + fs.slippage_pct)
    exit_cost = exit_notional * (exit_fee + fs.slippage_pct)
    return entry_cost + exit_cost


def net_pnl(gross_pnl: float, entry_price: float, exit_price: float, qty: float,
            exchange: str, entry_order_type: str = DEFAULT_ORDER_TYPE,
            exit_order_type: str = DEFAULT_ORDER_TYPE) -> tuple[float, float]:
    """
    Devuelve (pnl_neto, costo_total_usd) dado el pnl bruto ya calculado
    por trade_monitor/grid_stable_agent y los datos del fill.
    """
    entry_notional = entry_price * qty
    exit_notional = exit_price * qty
    cost = trade_cost_usd(exchange, entry_notional, exit_notional,
                           entry_order_type, exit_order_type)
    return gross_pnl - cost, cost


def min_rr_for_breakeven(exchange: str, entry_order_type: str = DEFAULT_ORDER_TYPE,
                          exit_order_type: str = DEFAULT_ORDER_TYPE) -> float:
    """
    RR ratio en TÉRMINOS DE PRECIO que hace falta para que, una vez restados
    fee+slippage, el trade gane al menos $0. Sirve como piso mínimo absoluto
    para MIN_RR_RATIO en risk_manager — cualquier estrategia con RR nominal
    por debajo de esto está, por diseño, perdiendo dinero neto.
    """
    return round_trip_cost_pct(exchange, entry_order_type, exit_order_type)
