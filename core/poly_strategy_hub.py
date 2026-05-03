"""
poly_strategy_hub.py — Orquestador multi-estrategia para Polymarket.

Centraliza el routing, deduplicación y performance tracking de todas las
estrategias Polymarket:
  1. SignalBasedPolyStrategy — Señales técnicas BTC/ETH 1h/4h (existente)
  2. TailEndPolyStrategy     — Near-resolution yield farming
  3. LateEntryPolyStrategy   — Late Entry V3 (últimos 4 min de mercados 15-min)
  4. LeggedArbPolyStrategy   — Legged Arbitrage 2-fase
   5. CombinatorialArbPolyStrategy — Violaciones lógicas entre mercados
   6. ValueZonePolyStrategy   — Compra YES en zona incertidumbre $0.42-$0.58

Orden de evaluación por prioridad (confidence):
  1. Combinatorial Arb (near risk-free cuando hay violación)
  2. Tail-End          (alta probabilidad near resolution)
  3. Late Entry        (consenso del mercado en ventana final)
  4. Legged Arb        (2 fases, requiere paciencia)
  5. Signal Based      (señales técnicas macro)
"""
import os
import sys
from datetime import datetime, timezone

import yaml
from loguru import logger
from sqlalchemy import create_engine, text

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv

load_dotenv('/opt/trading/config/.env')

with open('/opt/trading/config/exchange_config.yaml') as f:
    _POLY_CFG = yaml.safe_load(f).get('polymarket', {})

_STRATS_CFG = _POLY_CFG.get('strategies', {})


def _db_url() -> str:
    return (
        f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
        f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT', '5432')}"
        f"/{os.getenv('POSTGRES_DB')}"
    )


class PolyStrategyHub:
    """
    Hub central que coordina todas las estrategias Polymarket.

    Responsibilities:
    - Inicializar todas las estrategias habilitadas
    - Evaluar todos los mercados contra todas las estrategias
    - Deduplicar por condition_id (no abrir dos posiciones en el mismo mercado)
    - Ordenar señales por confidence descendente
    - Registrar performance por estrategia en DB
    """

    def __init__(self):
        self.engine = create_engine(_db_url())
        self._strategies = {}
        self._init_strategies()

    def _init_strategies(self):
        """Inicializa las estrategias habilitadas según config."""
        # 1. Signal Based (siempre habilitada — es la estrategia base)
        try:
            from strategies.signal_based_poly import SignalBasedPolyStrategy
            self._strategies['signal_based'] = SignalBasedPolyStrategy()
            logger.info('POLY HUB: SignalBasedPolyStrategy loaded')
        except Exception as e:
            logger.error(f'POLY HUB: Failed to load SignalBasedPolyStrategy: {e}')

        # 2. Tail-End
        if _STRATS_CFG.get('tail_end', {}).get('enabled', True):
            try:
                from strategies.poly_tail_end import TailEndPolyStrategy
                self._strategies['tail_end'] = TailEndPolyStrategy()
                logger.info('POLY HUB: TailEndPolyStrategy loaded')
            except Exception as e:
                logger.error(f'POLY HUB: Failed to load TailEndPolyStrategy: {e}')

        # 3. Late Entry
        if _STRATS_CFG.get('late_entry', {}).get('enabled', True):
            try:
                from strategies.poly_late_entry import LateEntryPolyStrategy
                self._strategies['late_entry'] = LateEntryPolyStrategy()
                logger.info('POLY HUB: LateEntryPolyStrategy loaded')
            except Exception as e:
                logger.error(f'POLY HUB: Failed to load LateEntryPolyStrategy: {e}')

        # 4. Legged Arb
        if _STRATS_CFG.get('legged_arb', {}).get('enabled', True):
            try:
                from strategies.poly_legged_arb import LeggedArbPolyStrategy
                self._strategies['legged_arb'] = LeggedArbPolyStrategy()
                logger.info('POLY HUB: LeggedArbPolyStrategy loaded')
            except Exception as e:
                logger.error(f'POLY HUB: Failed to load LeggedArbPolyStrategy: {e}')

         # 5. Combinatorial Arb
        if _STRATS_CFG.get('combinatorial', {}).get('enabled', True):
            try:
                from strategies.poly_combinatorial import CombinatorialArbPolyStrategy
                self._strategies['combinatorial'] = CombinatorialArbPolyStrategy()
                logger.info('POLY HUB: CombinatorialArbPolyStrategy loaded')
            except Exception as e:
                logger.error(f'POLY HUB: Failed to load CombinatorialArbPolyStrategy: {e}')

        # 6. Value Zone
        if _STRATS_CFG.get('value_zone', {}).get('enabled', True):
            try:
                from strategies.poly_value_zone import ValueZonePolyStrategy
                self._strategies['value_zone'] = ValueZonePolyStrategy()
                logger.info('POLY HUB: ValueZonePolyStrategy loaded')
            except Exception as e:
                logger.error(f'POLY HUB: Failed to load ValueZonePolyStrategy: {e}')

        logger.info(f'POLY HUB: {len(self._strategies)} strategies active: {list(self._strategies.keys())}')

    def evaluate_all(
        self,
        markets: list[dict],
        market_regime: str = 'UNKNOWN',
        already_traded: set | None = None,
        tail_end_markets: list[dict] | None = None,
        late_entry_markets: list[dict] | None = None,
    ) -> list[dict]:
        """Evalúa todos los mercados contra todas las estrategias.

        Args:
            markets: mercados del scan principal (activos en DB)
            market_regime: régimen actual ('TREND_UP', 'TREND_DOWN', 'RANGE', 'UNKNOWN')
            already_traded: condition_ids ya operados (para deduplicar)
            tail_end_markets: mercados near-resolution escaneados
            late_entry_markets: mercados 15-min próximos a cerrar

        Returns:
            Lista de signals ordenados por confidence DESC, deduplicados.
        """
        already_traded = already_traded or set()
        all_signals = []
        seen_condition_ids: set[str] = set()

        # ── Combinatorial Arb (escanea grupos, no mercados individuales) ──
        if 'combinatorial' in self._strategies:
            all_markets_for_combo = markets + (tail_end_markets or [])
            try:
                combo_signals = self._strategies['combinatorial'].find_opportunities(
                    all_markets_for_combo
                )
                for sig in combo_signals:
                    cid = sig['market'].get('condition_id', '')
                    if cid and cid not in already_traded and cid not in seen_condition_ids:
                        seen_condition_ids.add(cid)
                        all_signals.append(sig)
            except Exception as e:
                logger.debug(f'POLY HUB: Combinatorial eval error: {e}')

        # ── Tail-End markets ──
        if 'tail_end' in self._strategies and tail_end_markets:
            for market in tail_end_markets:
                cid = market.get('condition_id', '')
                if not cid or cid in already_traded or cid in seen_condition_ids:
                    continue
                try:
                    sig = self._strategies['tail_end'].evaluate(market)
                    if sig.get('opportunity'):
                        seen_condition_ids.add(cid)
                        all_signals.append(sig)
                except Exception as e:
                    logger.debug(f'POLY HUB: TailEnd eval error: {e}')

        # ── Late Entry markets ──
        if 'late_entry' in self._strategies and late_entry_markets:
            for market in late_entry_markets:
                cid = market.get('condition_id', '')
                if not cid or cid in already_traded or cid in seen_condition_ids:
                    continue
                try:
                    sig = self._strategies['late_entry'].evaluate(market)
                    if sig.get('opportunity'):
                        seen_condition_ids.add(cid)
                        all_signals.append(sig)
                except Exception as e:
                    logger.debug(f'POLY HUB: LateEntry eval error: {e}')

        # ── Mercados principales (signal_based + legged_arb) ──
        for market in markets:
            cid = market.get('condition_id', '')
            if not cid or cid in already_traded or cid in seen_condition_ids:
                continue

            # Signal Based
            if 'signal_based' in self._strategies:
                try:
                    sig = self._strategies['signal_based'].evaluate(
                        market, market_regime=market_regime
                    )
                    if sig.get('opportunity'):
                        seen_condition_ids.add(cid)
                        all_signals.append(sig)
                        continue  # No evaluar más estrategias para este mercado
                except Exception as e:
                    logger.debug(f'POLY HUB: SignalBased eval error: {e}')

            # Legged Arb (si signal_based no lo tomó)
            if 'legged_arb' in self._strategies and cid not in seen_condition_ids:
                try:
                    sig = self._strategies['legged_arb'].evaluate(market)
                    if sig.get('opportunity'):
                        seen_condition_ids.add(cid)
                        all_signals.append(sig)
                except Exception as e:
                    logger.debug(f'POLY HUB: LeggedArb eval error: {e}')

            # Value Zone (si ninguna otra estrategia tomó este mercado)
            if 'value_zone' in self._strategies and cid not in seen_condition_ids:
                try:
                    sig = self._strategies['value_zone'].evaluate(market)
                    if sig.get('opportunity'):
                        seen_condition_ids.add(cid)
                        all_signals.append(sig)
                except Exception as e:
                    logger.debug(f'POLY HUB: ValueZone eval error: {e}')

        # Ordenar por confidence DESC
        all_signals.sort(key=lambda s: s.get('confidence', 0), reverse=True)

        if all_signals:
            strategy_counts = {}
            for s in all_signals:
                strat = s.get('strategy', 'unknown')
                strategy_counts[strat] = strategy_counts.get(strat, 0) + 1
            logger.info(
                f'POLY HUB: {len(all_signals)} signals found: '
                + ', '.join(f'{k}={v}' for k, v in strategy_counts.items())
            )

        return all_signals

    def record_execution(self, strategy_name: str, session_id: int,
                         pnl: float | None = None, won: bool | None = None):
        """Registra una ejecución en poly_strategy_stats (si la tabla existe).

        No falla si la tabla no existe aún.
        """
        try:
            with self.engine.connect() as conn:
                conn.execute(
                    text('''
                        INSERT INTO poly_strategy_stats (strategy_name, session_id, total_trades)
                        VALUES (:s, :sid, 1)
                        ON CONFLICT (strategy_name, session_id) DO UPDATE SET
                            total_trades = poly_strategy_stats.total_trades + 1,
                            wins = poly_strategy_stats.wins + CASE WHEN :won THEN 1 ELSE 0 END,
                            total_pnl = poly_strategy_stats.total_pnl + COALESCE(:pnl, 0),
                            updated_at = now()
                    '''),
                    {
                        's': strategy_name,
                        'sid': session_id,
                        'pnl': pnl or 0.0,
                        'won': bool(won) if won is not None else False,
                    },
                )
                conn.commit()
        except Exception:
            pass  # La tabla puede no existir aún

    def get_strategy(self, name: str):
        """Retorna una estrategia por nombre."""
        return self._strategies.get(name)
