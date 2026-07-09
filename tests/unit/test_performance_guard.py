"""
Tests unitarios del circuit breaker por estrategia.
"""
import sys

sys.path.insert(0, '/opt/trading')

from core.performance_guard import (
    PerformanceSnapshot,
    should_block_asset_strategy,
    should_block_strategy,
    summarize_closed_trades,
)


class TestSummarizeClosedTrades:
    def test_snapshot_computes_profit_factor_and_streak(self):
        rows = [
            {'pnl': -100},
            {'pnl': -90},
            {'pnl': -80},
            {'pnl': 150},
        ]
        snapshot = summarize_closed_trades(rows)

        assert snapshot.total == 4
        assert snapshot.wins == 1
        assert snapshot.losses == 3
        assert snapshot.consecutive_losses == 3
        assert snapshot.pnl == -120
        assert round(snapshot.profit_factor, 3) == round(150 / 270, 3)


class TestAssetStrategyBlocker:
    def test_blocks_negative_asset_strategy(self):
        snapshot = PerformanceSnapshot(
            total=4,
            wins=1,
            losses=3,
            flats=0,
            pnl=-140.0,
            gross_profit=160.0,
            gross_loss=300.0,
            win_rate=0.25,
            profit_factor=0.53,
            consecutive_losses=3,
        )
        reason = should_block_asset_strategy(snapshot)
        assert reason is not None
        assert 'ASSET_STRATEGY' in reason

    def test_does_not_block_positive_asset_strategy(self):
        snapshot = PerformanceSnapshot(
            total=6,
            wins=3,
            losses=2,
            flats=1,
            pnl=120.0,
            gross_profit=300.0,
            gross_loss=180.0,
            win_rate=0.60,
            profit_factor=1.67,
            consecutive_losses=0,
        )
        assert should_block_asset_strategy(snapshot) is None


class TestStrategyBlocker:
    def test_blocks_strategy_without_wins(self):
        snapshot = PerformanceSnapshot(
            total=5,
            wins=0,
            losses=5,
            flats=0,
            pnl=-500.0,
            gross_profit=0.0,
            gross_loss=500.0,
            win_rate=0.0,
            profit_factor=0.0,
            consecutive_losses=5,
        )
        reason = should_block_strategy(snapshot)
        assert reason == 'STRATEGY_NO_EDGE:5_losses'

    def test_keeps_strategy_if_sample_is_small(self):
        snapshot = PerformanceSnapshot(
            total=3,
            wins=0,
            losses=3,
            flats=0,
            pnl=-300.0,
            gross_profit=0.0,
            gross_loss=300.0,
            win_rate=0.0,
            profit_factor=0.0,
            consecutive_losses=3,
        )
        assert should_block_strategy(snapshot) is None