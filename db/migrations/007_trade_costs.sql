-- Costos reales por trade (fee + slippage) — ver core/cost_model.py y docs/FEASIBILITY_STUDY.md
--
-- Hasta esta migración, la columna `pnl` guardaba PnL BRUTO (precio de salida
-- menos precio de entrada, sin restar comisión ni slippage). Eso sobreestimaba
-- la ganancia real de toda estrategia, especialmente las de alta frecuencia
-- (grids), y fue la causa de que el capital bajara pese a "ganancias" en paper.
--
-- A partir de esta migración:
--   pnl        -> PnL NETO (lo que de verdad queda). Es lo que deben usar
--                 dashboards, métricas de graduación y cálculo de balance.
--   pnl_gross  -> PnL bruto (compatibilidad con reportes históricos/debug).
--   fee_paid   -> costo total estimado del round-trip (fee + slippage), en USD.

ALTER TABLE trades ADD COLUMN IF NOT EXISTS pnl_gross NUMERIC(14, 4);
ALTER TABLE trades ADD COLUMN IF NOT EXISTS fee_paid  NUMERIC(14, 4) DEFAULT 0;

COMMENT ON COLUMN trades.pnl IS 'PnL neto (después de fee + slippage estimado). Fuente de verdad para balance/métricas.';
COMMENT ON COLUMN trades.pnl_gross IS 'PnL bruto (precio de salida - precio de entrada, sin costos). Solo referencia.';
COMMENT ON COLUMN trades.fee_paid IS 'Fee + slippage estimado del round-trip, en USD. pnl = pnl_gross - fee_paid.';
