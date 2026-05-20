"""
BaseStrategy — Contrato para todas las estrategias del sistema.

Cada estrategia implementa:
    detect()    → Escanea datos y retorna Signal si hay entrada.
    evaluate()  → Gates pre-ejecución (risk, DirectionGuard, exposición).
    should_exit() → Monitoreo de trade abierto (SL, TP, trailing).

Etapa 1 (Mayo 2026): solo TREND_MOMENTUM migrado.
Etapas 2-4: hot-reload via Redis, mode por estrategia, backtest avanzado.
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List


class Mode(str, Enum):
    PAPER = "paper"
    LIVE = "live"
    SHADOW = "shadow"


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    NEUTRAL = "NEUTRAL"


@dataclass
class Signal:
    """Señal generada por detect(). Solo lectura — no modifica estado."""
    asset: str
    direction: Direction
    entry_price: float
    score: float
    stop_loss: float
    take_profit: float
    timeframe: str
    strategy: str
    reasons: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_legacy(cls, asset: str, timeframe: str, legacy: dict, strategy_name: str) -> "Signal":
        """Convierte dict legacy (v1) a Signal (v2)."""
        direction = Direction(legacy.get("direction", "NEUTRAL"))
        return cls(
            asset=asset,
            direction=direction,
            entry_price=0.0,  # se completa en el engine
            score=legacy.get("score", 0),
            stop_loss=legacy.get("stop_loss", 0.0),
            take_profit=legacy.get("take_profit", 0.0),
            timeframe=timeframe,
            strategy=strategy_name,
            reasons=legacy.get("reasons", []),
        )


@dataclass
class Decision:
    """Resultado de evaluate()."""
    action: str        # "execute" | "skip" | "blocked"
    reason: str
    size: float = 0.0


@dataclass
class ExitAction:
    """Resultado de should_exit()."""
    action: str        # "close" | "hold" | "update_sl"
    reason: str
    exit_price: float = 0.0
    pnl: float = 0.0
    new_sl: Optional[float] = None


class BaseStrategy:
    """Clase base para todas las estrategias de trading.

    Atributos de clase (definir en subclase):
        name: str               — slug único (ej: "trend_momentum")
        default_config: dict    — parámetros por defecto
        mode: Mode              — PAPER | LIVE | SHADOW

    Métodos a implementar:
        detect()     — evalúa OHLCV, retorna Signal o None
        evaluate()   — gates pre-ejecución, retorna Decision
        should_exit()— monitoreo de trade abierto, retorna ExitAction
    """

    name: str = "base"
    default_config: dict = {}
    mode: Mode = Mode.PAPER

    def __init__(self):
        self.config = dict(self.default_config)

    def detect(self, ind: "IndicatorSet", regime, macro_bias) -> Optional[Signal]:
        """Evalúa indicadores y régimen. Retorna Signal o None."""
        raise NotImplementedError

    def evaluate(self, signal: Signal, portfolio: dict, open_trades: list) -> Decision:
        """Gates pre-ejecución. Default: pasa todo (el engine ya filtra)."""
        return Decision(action="execute", reason="passthrough", size=0.0)

    def should_exit(self, trade: dict, current_price: float) -> ExitAction:
        """Monitorea trade abierto. Default: hold (el trade_monitor ya lo hace)."""
        return ExitAction(action="hold", reason="passthrough")
