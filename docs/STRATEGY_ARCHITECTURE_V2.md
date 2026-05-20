# ARTHAS — Strategy Architecture v2

> **Plan de adopción de patrones arquitectónicos de Homerun para el sistema Arthas.**
> Basado en auditoría Mayo 2026. Inspirado en `braedonsaunders/homerun` (AGPL v3).
> Estado: **PLAN** — no implementado.

---

## 1. Motivación

El sistema actual tiene 6 estrategias crypto activas. Cada una está implementada de forma distinta:

| Estrategia | Parámetros en | Señal en | Ejecución en | Cierre en |
|---|---|---|---|---|
| TREND_MOMENTUM | YAML + asset_profiles.py | trend_momentum.py | strategy_engine.py | trade_monitor.py |
| GRID_BOT | YAML | grid_agent.py | grid_agent.py | grid_agent.py |
| GRID_STABLE | YAML | grid_stable_agent.py | grid_stable_agent.py | grid_stable_agent.py |
| BTC_MICROSTRUCTURE | Código | btc_microstructure.py | strategy_engine.py | trade_monitor.py |
| SMC_ORDER_BLOCKS | Código | smc_order_blocks.py | strategy_engine.py | trade_monitor.py |
| EMA_RIBBON | Código | ema_ribbon.py | strategy_engine.py | trade_monitor.py |

**Problemas:**
- Agregar una estrategia nueva requiere tocar 4-5 archivos
- `PAPER_TRADING=true/false` es global — no se puede probar una estrategia en paper mientras otras van en live
- Cambiar un parámetro requiere reiniciar el agente (180s warm-up)
- El backtest usa velas OHLCV sin modelar slippage ni liquidez
- No hay un contrato claro de qué métodos debe implementar una estrategia

Homerun resolvió todo esto con 4 patrones que podemos adoptar incrementalmente.

---

## 2. Visión Final

```
┌─────────────────────────────────────────────────────────┐
│                  STRATEGY ENGINE v2                      │
│                                                          │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐           │
│  │ DETECT   │───▶│ EVALUATE │───▶│ EXECUTE  │───▶ ORDER │
│  │ (señales)│    │ (gates)  │    │ (tamaño) │           │
│  └──────────┘    └──────────┘    └──────────┘           │
│       │                               │                  │
│       │    ┌──────────────┐           │                  │
│       └───▶│ SHOULD_EXIT  │◀──────────┘                  │
│            │ (monitoreo)  │                              │
│            └──────────────┘                              │
│                                                          │
│  Config por estrategia (Redis/DB, hot-reload)            │
│  Modo por estrategia (paper/live/shadow)                 │
│  Backtest con modelo de ejecución realista               │
└─────────────────────────────────────────────────────────┘
```

Cada estrategia es **1 archivo Python** con 3 métodos + 1 clase:

```python
class MiEstrategia(BaseStrategy):
    name = "mi_estrategia"
    config = {"min_score": 70, "sl_pct": 2.0}
    mode = "paper"  # paper | live | shadow
    
    def detect(self, data: OHLCV, regime: Regime) -> Signal | None: ...
    def evaluate(self, signal: Signal, portfolio: Portfolio) -> Decision: ...
    def should_exit(self, trade: Trade, price: float) -> ExitAction: ...
```

---

## 3. Plan de Implementación

### ETAPA 1 — Refactor BaseStrategy (semana 1)

**Objetivo**: Crear la clase base y migrar TREND_MOMENTUM sin cambiar su comportamiento. Probar que opera idéntico.

**Archivos nuevos**:
- `strategies/base.py` — clase `BaseStrategy` con contrato `detect() → evaluate() → should_exit()`
- `strategies/trend_momentum_v2.py` — `TrendMomentumStrategy(BaseStrategy)` con misma lógica

**Qué NO se toca**:
- `strategy_engine.py` (sigue funcionando con las estrategias viejas)
- `trade_monitor.py`
- `run_trading.py`
- `exchange_config.yaml`

**Validación**: Correr SESSION_011 con ambas versiones en paralelo (v1 y v2). Mismas señales, mismos trades, mismo PnL.

**Criterio de éxito**: TREND_MOMENTUM v2 genera las mismas señales que v1 durante 48h.

---

### ETAPA 2 — Migrar config a Redis (semana 2)

**Objetivo**: Los parámetros de estrategia se leen de Redis en cada ciclo. Editables sin reiniciar.

**Qué cambia**:
- `BaseStrategy.config` se carga de `redis.get("strategy:trend_momentum:config")`
- Si la key no existe, usa `default_config` y la escribe a Redis
- Para cambiar un parámetro: `redis-cli set strategy:trend_momentum:config '{"min_score": 75}'`
- La estrategia lo lee en el próximo ciclo (60s)

**Archivos modificados**:
- `strategies/base.py` — agregar `_load_config()` / `_save_config()`
- Nuevo endpoint o script para editar config (`scripts/set_strategy_param.py`)

**Validación**: Cambiar `MIN_SCORE` de 65 a 70 sin reiniciar. Verificar en logs que la estrategia filtra más señales.

**Criterio de éxito**: Cambiar un parámetro y ver el efecto en ≤2 ciclos sin restart.

---

### ETAPA 3 — Modo por estrategia (semana 3)

**Objetivo**: `paper/live/shadow` por estrategia individual, no global.

**Qué cambia**:
- `BaseStrategy.mode` puede ser `"paper"`, `"live"`, o `"shadow"`
- `PAPER_TRADING` en `.env` se convierte en default global
- Cada estrategia puede sobrescribir su modo en config
- `execution_agent.py` consulta `strategy.mode` antes de ejecutar

**Archivos modificados**:
- `strategies/base.py` — campo `mode`
- `agents/execution_agent.py` — respetar `strategy.mode`
- `scripts/run_trading.py` — eliminar `PAPER_TRADING` global

**Validación**: GRID_BOT en live, TREND_MOMENTUM en paper, BTC_MICROSTRUCTURE en shadow. Verificar que solo GRID_BOT genera órdenes reales.

**Criterio de éxito**: 3 estrategias con modos diferentes, sin interferencia.

---

### ETAPA 4 — Backtest con modelo de ejecución (semana 4+)

**Objetivo**: Backtest que modela slippage, latencia, y usa datos reales de la DB.

**Qué cambia**:
- `scripts/backtest.py` lee `market_data` de PostgreSQL en vez de descargar de CCXT
- Agrega modelo de slippage: `fill_price = signal_price * (1 ± slippage_pct)`
- Agrega latencia simulada: `execution_time = signal_time + latency_ms`
- Walk-forward: optimiza en train, valida en test

**Archivos modificados**:
- `scripts/backtest.py` — reescritura parcial
- `strategies/base.py` — método `backtest(config, start, end)` opcional

---

## 4. Contrato BaseStrategy

```python
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

class Mode(str, Enum):
    PAPER = "paper"
    LIVE = "live"
    SHADOW = "shadow"

class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

@dataclass
class Signal:
    asset: str
    direction: Direction
    entry_price: float
    score: float
    stop_loss: float
    take_profit: float
    timeframe: str
    strategy: str
    metadata: dict = field(default_factory=dict)

@dataclass  
class Decision:
    action: str        # "execute" | "skip" | "blocked"
    reason: str
    size: float = 0.0  # position size in base currency

@dataclass
class ExitAction:
    action: str        # "close" | "hold" | "update_sl"
    reason: str
    exit_price: float = 0.0
    pnl: float = 0.0
    new_sl: Optional[float] = None

class BaseStrategy:
    name: str = "base"
    config: dict = {}
    mode: Mode = Mode.PAPER
    
    def __init__(self):
        self._load_config()
    
    def detect(self, ohlcv, regime, macro_bias) -> Optional[Signal]:
        """Evalúa datos OHLCV y retorna Signal si hay entrada. Solo lectura."""
        raise NotImplementedError
    
    def evaluate(self, signal: Signal, portfolio: dict, open_trades: list) -> Decision:
        """Gates pre-ejecución: risk manager, DirectionGuard, exposición."""
        raise NotImplementedError
    
    def should_exit(self, trade: dict, current_price: float) -> ExitAction:
        """Monitorea trade abierto: SL, TP, trailing stop, time stop."""
        raise NotImplementedError
    
    def _load_config(self):
        """Carga config desde Redis o usa default_config."""
        import redis, json
        r = redis.Redis(host='localhost', port=6379, decode_responses=True)
        stored = r.get(f"strategy:{self.name}:config")
        if stored:
            try:
                self.config = {**self.default_config, **json.loads(stored)}
                return
            except json.JSONDecodeError:
                pass
        self.config = dict(self.default_config)
        r.set(f"strategy:{self.name}:config", json.dumps(self.config))
    
    @property
    def default_config(self) -> dict:
        return {}
```

---

## 5. Migración de estrategias existentes

### TREND_MOMENTUM (primera en migrar)

```python
class TrendMomentumStrategy(BaseStrategy):
    name = "trend_momentum"
    default_config = {
        "min_score": 65,
        "rsi_buy_zone": [50, 65],
        "rsi_sell_zone": [25, 50],
        "sl_multiplier": 1.5,
        "tp_multiplier": 2.5,
    }
    
    def detect(self, ohlcv, regime, macro_bias):
        if regime not in ("TREND_DOWN", "BREAKOUT_DOWN"):
            return None
        score = self._compute_score(ohlcv)
        if score < self.config["min_score"]:
            return None
        return Signal(
            asset=ohlcv.asset, direction=Direction.SELL,
            entry_price=ohlcv.close, score=score,
            stop_loss=ohlcv.close * (1 + ohlcv.atr * self.config["sl_multiplier"]),
            take_profit=ohlcv.close * (1 - ohlcv.atr * self.config["tp_multiplier"]),
            timeframe=ohlcv.timeframe, strategy=self.name,
        )
    
    def evaluate(self, signal, portfolio, open_trades):
        # DirectionGuard check
        if not crypto_is_allowed(signal.asset, signal.direction.value):
            return Decision("blocked", "direction_guard")
        # Risk manager
        if portfolio.get("drawdown_pct", 0) >= 0.10:
            return Decision("blocked", "drawdown")
        # Position size
        size = self._calculate_size(signal, portfolio)
        if size <= 0:
            return Decision("blocked", "size_zero")
        return Decision("execute", "ok", size=size)
    
    def should_exit(self, trade, current_price):
        entry = float(trade["entry_price"])
        sl = float(trade["stop_loss"])
        tp = float(trade["take_profit"])
        
        if trade["side"] == "SELL":
            if current_price >= sl:
                pnl = (entry - current_price) * float(trade["position_size"])
                return ExitAction("close", "stop_loss", current_price, pnl)
            if current_price <= tp:
                pnl = (entry - current_price) * float(trade["position_size"])
                return ExitAction("close", "take_profit", current_price, pnl)
        
        return ExitAction("hold", "")
```

### GRID_BOT y GRID_STABLE

Estas estrategias ya tienen su propio ciclo de vida independiente del `strategy_engine`. Se mantienen como están — no necesitan heredar de `BaseStrategy` porque no pasan por `detect() → evaluate() → should_exit()`. Se registran como `AutonomousStrategy`:

```python
class AutonomousStrategy(BaseStrategy):
    """Estrategias con ciclo de vida propio (grid, pairs, snipe)."""
    def run_cycle(self, portfolio, session) -> list[Trade]: ...
```

### EMA_RIBBON, BTC_MICROSTRUCTURE, SMC_ORDER_BLOCKS

Se migran después de TREND_MOMENTUM, usando el mismo patrón. Bajo volumen pero estructura simple.

---

## 6. Roadmap visual

```
Semana 1          Semana 2          Semana 3          Semana 4+
─────────         ─────────         ─────────         ─────────
BaseStrategy      Config en         Mode por          Backtest
+ TrendMom v2     Redis             estrategia        con slippage
                                    
[probando en      [hot-reload       [paper/live/      [walk-forward
 paralelo]         sin restart]      shadow]           + L2 model]
                                    
✅ mismo PnL      ✅ cambio en      ✅ GRID live      ✅ backtest
   48h validación    ≤2 ciclos        + TM paper        ≈ PnL real
```

---

## 7. Riesgos y mitigaciones

| Riesgo | Probabilidad | Mitigación |
|---|---|---|
| v2 genera señales distintas a v1 | Media | Correr en paralelo 48h, comparar logs |
| Hot-reload rompe ciclo activo | Baja | Validar config al cargar, fallback a default |
| Redis caído → config no disponible | Baja | `default_config` como fallback automático |
| Modo por estrategia interfiere entre sí | Baja | Cada estrategia instancia independiente |
| Backtest con slippage da resultados irreales | Media | Calibrar slippage con datos reales de trades |

---

## 8. Estado actual

| Etapa | Estado | Fecha |
|---|---|---|
| 1. Refactor BaseStrategy | ⏳ PLAN | — |
| 2. Config en Redis | ⏳ PLAN | — |
| 3. Modo por estrategia | ⏳ PLAN | — |
| 4. Backtest avanzado | ⏳ PLAN | — |

> **Última actualización**: Mayo 20, 2026 — documento creado.
> **Próximo paso**: Aprobación del plan → inicio Etapa 1.
