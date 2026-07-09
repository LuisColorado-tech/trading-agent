#!/usr/bin/env python3
"""
repo_strategy_hunter.py
========================
Sistema de ingeniería inversa de estrategias de trading desde GitHub.

Fases:
  1. Discovery   → GitHub API → busca repos por keywords
  2. Analysis    → descarga README/código, extrae lógica de estrategia
  3. Save DB     → guarda en tabla repo_strategies
  4. Backtest    → adapta al framework existente y corre backtest
  5. Evaluate    → filtra por métricas (Sharpe, WinRate, DD)
  6. Deploy      → estrategias ganadoras → production strategies/

Uso:
  python repo_strategy_hunter.py --phase discover
  python repo_strategy_hunter.py --phase analyze
  python repo_strategy_hunter.py --phase backtest
  python repo_strategy_hunter.py --phase report
  python repo_strategy_hunter.py --phase all
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from typing import Any, Optional

import requests
from sqlalchemy import create_engine, text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("hunter")

DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://trading:Tr4d1ng_Ag3nt_2026!@localhost:5432/trading_agent",
)
GITHUB_API = "https://api.github.com"
GITHUB_RAW = "https://raw.githubusercontent.com"

# ──────────────────────────────────────────────────────────────────────────────
# QUERIES DE BÚSQUEDA EN GITHUB
# ──────────────────────────────────────────────────────────────────────────────
SEARCH_QUERIES = [
    # Polymarket específico
    {
        "q": "polymarket trading strategy python signal",
        "label": "polymarket_signal",
        "asset_class": "polymarket",
    },
    {
        "q": "polymarket btc prediction market bot python",
        "label": "polymarket_btc",
        "asset_class": "polymarket",
    },
    {
        "q": "polymarket arbitrage edge kelly criterion python",
        "label": "polymarket_arb",
        "asset_class": "polymarket",
    },
    # Crypto general - alta calidad
    {
        "q": "crypto trading strategy momentum rsi macd backtest python ccxt",
        "label": "crypto_momentum",
        "asset_class": "crypto",
    },
    {
        "q": "crypto mean reversion bollinger bands backtest python",
        "label": "crypto_mean_rev",
        "asset_class": "crypto",
    },
    {
        "q": "smart money concepts ICT order blocks FVG python trading",
        "label": "smc_ict",
        "asset_class": "crypto",
    },
    # Quant
    {
        "q": "quantitative trading strategy python sharpe ratio backtest",
        "label": "quant_general",
        "asset_class": "crypto",
    },
    {
        "q": "btc bitcoin trading bot momentum breakout python",
        "label": "btc_momentum",
        "asset_class": "crypto",
    },
]

# ──────────────────────────────────────────────────────────────────────────────
# CATÁLOGO MANUAL: repos ya identificados con alta prioridad
# ──────────────────────────────────────────────────────────────────────────────
MANUAL_REPOS = [
    {
        "repo": "aulekator/Polymarket-BTC-15-Minute-Trading-Bot",
        "stars": 196,
        "strategy_name": "BTC 15min Multi-Signal (7-Phase)",
        "strategy_type": "composite",
        "asset_class": "polymarket",
        "timeframe": "15m",
        "description": (
            "Bot 7 fases: Spike Detection, Sentiment Analysis, Price Divergence. "
            "Weighted voting fusion engine. Self-learning weight optimization. "
            "Stop loss 30%, take profit 20%, $1 max per trade."
        ),
        "entry_logic": (
            "Signal fusion de 3 detectores: (1) Spike Detection en precio BTC, "
            "(2) Análisis de sentimiento via Fear&Greed + social, "
            "(3) Divergencia de precio BTC vs Polymarket odds. "
            "Trade cuando composite score > threshold."
        ),
        "exit_logic": "Stop loss 30%, Take profit 20%, expiración del mercado 15min",
        "indicators_used": "fear_greed_index,price_spike,sentiment_score,price_divergence",
        "position_sizing": "fixed",
        "risk_params": {"stop_loss": 0.30, "take_profit": 0.20, "max_pos": 1.0},
        "source_files": "core/strategy_brain/signal_processors/, core/strategy_brain/fusion_engine/",
        "priority": 1,
    },
    {
        "repo": "suislanchez/polymarket-kalshi-weather-bot",
        "stars": 282,
        "strategy_name": "BTC Microstructure + Kelly Sizing",
        "strategy_type": "composite",
        "asset_class": "polymarket",
        "timeframe": "5m",
        "description": (
            "Estrategia BTC 5min: RSI(14), Momentum (1m/5m/15m), VWAP deviation, "
            "SMA crossover, Market skew. Convergence filter: 2+ indicadores deben coincidir. "
            "Edge > 2%. Position sizing via Kelly fraccional (15%)."
        ),
        "entry_logic": (
            "1. Fetch 60 velas 1min de Coinbase/Kraken/Binance. "
            "2. Calcular 5 indicadores: RSI(14), Momentum multiperiodo, VWAP dev, "
            "SMA crossover, Market skew. "
            "3. Convergence: ≥2 de 4 indicadores alineados. "
            "4. Weighted composite → probabilidad UP (rango 0.35-0.65). "
            "5. Comparar vs precio Polymarket → trade el lado con mayor edge."
        ),
        "exit_logic": "Expiración del mercado 5min, sin stop loss explícito",
        "indicators_used": "RSI_14,momentum_1m,momentum_5m,momentum_15m,VWAP_deviation,SMA_crossover,market_skew",
        "position_sizing": "kelly",
        "risk_params": {
            "min_edge": 0.02,
            "max_entry_price": 0.55,
            "max_trade_size": 75.0,
            "kelly_fraction": 0.15,
            "daily_loss_limit": 300.0,
        },
        "source_files": "backend/core/signals.py, backend/data/crypto.py",
        "priority": 1,
    },
    {
        "repo": "Polymarket/agents",
        "stars": 3363,
        "strategy_name": "Polymarket AI Agents (Oficial)",
        "strategy_type": "agent_based",
        "asset_class": "polymarket",
        "timeframe": "variable",
        "description": (
            "Framework OFICIAL de Polymarket para trading autónomo con AI Agents. "
            "Arquitectura Agent → Strategy → Market → Order. "
            "Soporta multi-market, risk management, backtesting integrado. "
            "760+ forks, MIT license. Comunidad activa."
        ),
        "entry_logic": (
            "1. Agent recibe señales del mercado (price, volume, order book). "
            "2. Strategy evalúa condiciones de entrada (RSI, momentum, etc.). "
            "3. Order se ejecuta via Polymarket CLOB o AMM. "
            "4. Risk manager aplica position sizing y stop loss."
        ),
        "exit_logic": "Expiración del mercado o TP/SL configurado por agente",
        "indicators_used": "RSI,momentum,orderbook_depth,market_sentiment",
        "position_sizing": "risk_pct",
        "risk_params": {"max_position_pct": 0.05, "daily_loss_limit": 200.0},
        "source_files": "src/agents/, src/strategies/, src/markets/",
        "priority": 1,
    },
    {
        "repo": "CarlosIbCu/polymarket-kalshi-btc-arbitrage-bot",
        "stars": 179,
        "strategy_name": "Cross-Platform Arbitrage (Polymarket ↔ Kalshi)",
        "strategy_type": "arb",
        "asset_class": "polymarket",
        "timeframe": "1h",
        "description": (
            "Arbitraje cross-platform en tiempo real entre Polymarket y Kalshi "
            "para mercados BTC 1-Hour Price. Detecta discrepancias de precio entre "
            "ambas plataformas y ejecuta arbitraje libre de riesgo. "
            "Tesis matemática documentada en thesis.md. MIT license."
        ),
        "entry_logic": (
            "1. Monitorear simultáneamente Polymarket CLOB y Kalshi API. "
            "2. Calcular precio combinado: si P_poly + P_kalshi < $1.00 → oportunidad. "
            "3. Comprar YES en la plataforma más barata, NO en la más cara. "
            "4. Profit = (1 - P_poly - P_kalshi) * size - fees."
        ),
        "exit_logic": "Expiración del mercado 1h, sin SL necesario (arbitraje puro)",
        "indicators_used": "polymarket_clob,kalshi_api,price_spread,order_book",
        "position_sizing": "fixed",
        "risk_params": {"min_spread": 0.01, "max_position": 100.0, "min_edge_pct": 0.01},
        "source_files": "bot.py, thesis.md, src/",
        "priority": 1,
    },
    {
        "repo": "joshyattridge/smart-money-concepts",
        "stars": 1615,
        "strategy_name": "Smart Money Concepts (ICT) - Order Blocks + FVG",
        "strategy_type": "breakout",
        "asset_class": "crypto",
        "timeframe": "15m",
        "description": (
            "Implementación completa de SMC/ICT: Order Blocks (OB), "
            "Fair Value Gaps (FVG), Liquidity sweeps, Break of Structure (BOS), "
            "Change of Character (CHoCH). "
            "Paquete pip publicado: smartmoneyconcepts."
        ),
        "entry_logic": (
            "1. Identificar Break of Structure (BOS) / Change of Character (CHoCH). "
            "2. Esperar retroceso a Order Block (zona de institución). "
            "3. Confirmar con Fair Value Gap (FVG) sin llenar. "
            "4. Entrar en la dirección del BOS con SL debajo/encima del OB."
        ),
        "exit_logic": "TP en siguiente nivel de liquidez, SL debajo del Order Block",
        "indicators_used": "order_blocks,FVG,BOS,CHoCH,liquidity_levels,inner_circle",
        "position_sizing": "risk_pct",
        "risk_params": {"risk_per_trade": 0.01, "min_rr": 2.0},
        "source_files": "smartmoneyconcepts/smc.py",
        "priority": 2,
    },
    {
        "repo": "ilahuerta-IA/backtrader-pullback-window-xauusd",
        "stars": 45,
        "strategy_name": "Pullback State Machine (4-Phase Entry)",
        "strategy_type": "momentum",
        "asset_class": "crypto",
        "timeframe": "15m",
        "description": (
            "Estrategia pullback con máquina de estados de 4 fases para Gold/XAU/USD. "
            "Resultados documentados: Sharpe 0.89, PF 1.64, WR 55.43%, DD 5.81%, "
            "+44.75% retorno en 5 años. Adaptable a BTC/crypto."
        ),
        "entry_logic": (
            "Máquina de estados 4 fases: "
            "1-SCAN: buscar tendencia con EMAs. "
            "2-WAIT: esperar retroceso a zona de soporte/resistencia. "
            "3-CONFIRM: confirmación con patrón de vela o momentum. "
            "4-ENTER: entrada con ventana de tiempo limitada."
        ),
        "exit_logic": "SL fijo debajo del swing low, TP en ratio R:R definido",
        "indicators_used": "EMA_fast,EMA_slow,ATR,swing_highs,swing_lows,volume",
        "position_sizing": "risk_pct",
        "risk_params": {
            "risk_per_trade": 0.01,
            "min_rr": 1.5,
            "reported_sharpe": 0.89,
            "reported_win_rate": 0.5543,
            "reported_max_dd": 0.0581,
        },
        "source_files": "strategy.py, indicators.py",
        "priority": 2,
    },
    {
        "repo": "0xrsydn/polymarket-crypto-toolkit",
        "stars": 57,
        "strategy_name": "Polymarket Plugin-Based Multi-Strategy",
        "strategy_type": "composite",
        "asset_class": "polymarket",
        "timeframe": "15m",
        "description": (
            "Toolkit modular para Polymarket crypto: plugin-based strategies, "
            "indicadores técnicos, backtesting integrado, feeds multi-fuente. "
            "Diseñado para composición de estrategias."
        ),
        "entry_logic": "Plugin-based: cada estrategia implementa evaluate(market) → Signal",
        "exit_logic": "Configurable por estrategia",
        "indicators_used": "RSI,MACD,BB,volume_profile",
        "position_sizing": "risk_pct",
        "risk_params": {"min_edge": 0.05},
        "source_files": "strategies/, indicators/, backtesting/",
        "priority": 3,
    },
    {
        "repo": "GiordanoSouza/polymarket-copy-trading-bot",
        "stars": 44,
        "strategy_name": "Copy-Trading de Wallets Rentables",
        "strategy_type": "signal_based",
        "asset_class": "polymarket",
        "timeframe": "event-based",
        "description": (
            "Bot de copy-trading: monitorea wallets exitosas en Polymarket, "
            "replica sus trades en tiempo real via Supabase. "
            "Estrategia: seguir a traders con historial probado."
        ),
        "entry_logic": (
            "1. Monitorear lista de wallets top traders. "
            "2. Cuando wallet objetivo abre posición → replica inmediatamente. "
            "3. Filtros: min_position_size, max_market_age, min_wallet_profit."
        ),
        "exit_logic": "Expiración del mercado o cuando wallet objetivo cierra",
        "indicators_used": "wallet_pnl,trade_history,win_rate_wallet",
        "position_sizing": "fixed",
        "risk_params": {"min_wallet_roi": 0.10, "max_copy_size": 50.0},
        "source_files": "bot.py, supabase_handler.py",
        "priority": 3,
    },
]


# ──────────────────────────────────────────────────────────────────────────────
# DB HELPERS
# ──────────────────────────────────────────────────────────────────────────────
def get_engine():
    return create_engine(DB_URL)


def upsert_strategy(engine, strategy: dict):
    """Inserta o actualiza una estrategia en repo_strategies."""
    sql = text(
        """
        INSERT INTO repo_strategies (
            repo_name, repo_url, stars, strategy_name, strategy_type,
            asset_class, timeframe, description, entry_logic, exit_logic,
            indicators_used, position_sizing, risk_params, source_files,
            implementation_status, priority, notes, updated_at
        ) VALUES (
            :repo_name, :repo_url, :stars, :strategy_name, :strategy_type,
            :asset_class, :timeframe, :description, :entry_logic, :exit_logic,
            :indicators_used, :position_sizing, CAST(:risk_params AS jsonb), :source_files,
            :implementation_status, :priority, :notes, NOW()
        )
        ON CONFLICT DO NOTHING
        RETURNING id
        """
    )
    with engine.connect() as conn:
        result = conn.execute(
            sql,
            {
                "repo_name": strategy.get("repo_name", ""),
                "repo_url": strategy.get("repo_url", ""),
                "stars": strategy.get("stars", 0),
                "strategy_name": strategy.get("strategy_name", ""),
                "strategy_type": strategy.get("strategy_type", ""),
                "asset_class": strategy.get("asset_class", ""),
                "timeframe": strategy.get("timeframe", ""),
                "description": strategy.get("description", ""),
                "entry_logic": strategy.get("entry_logic", ""),
                "exit_logic": strategy.get("exit_logic", ""),
                "indicators_used": strategy.get("indicators_used", ""),
                "position_sizing": strategy.get("position_sizing", ""),
                "risk_params": json.dumps(strategy.get("risk_params", {})),
                "source_files": strategy.get("source_files", ""),
                "implementation_status": strategy.get(
                    "implementation_status", "discovered"
                ),
                "priority": strategy.get("priority", 5),
                "notes": strategy.get("notes", ""),
            },
        )
        conn.commit()
        row = result.fetchone()
        return row[0] if row else None


# ──────────────────────────────────────────────────────────────────────────────
# FASE 1: DISCOVERY VIA GITHUB API
# ──────────────────────────────────────────────────────────────────────────────
def github_search(query: str, per_page: int = 8) -> list[dict]:
    """Busca repos en GitHub API sin autenticación."""
    url = f"{GITHUB_API}/search/repositories"
    params = {
        "q": query,
        "sort": "stars",
        "order": "desc",
        "per_page": per_page,
    }
    headers = {"Accept": "application/vnd.github.v3+json"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        data = r.json()
        return data.get("items", [])
    except Exception as e:
        log.warning(f"GitHub API error para '{query}': {e}")
        return []


def fetch_readme(repo_full_name: str) -> str:
    """Descarga README.md del repo."""
    for branch in ("main", "master"):
        url = f"{GITHUB_RAW}/{repo_full_name}/{branch}/README.md"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                return r.text[:8000]  # máx 8kb
        except Exception:
            pass
    return ""


def phase_discover(engine) -> int:
    """Fase 1: busca repos en GitHub y guarda en DB."""
    log.info("=== FASE 1: DISCOVERY ===")
    total_saved = 0

    for search_cfg in SEARCH_QUERIES:
        query = search_cfg["q"]
        asset_class = search_cfg.get("asset_class", "crypto")
        log.info(f"  Buscando: {query[:60]}...")

        repos = github_search(query, per_page=5)
        time.sleep(1)  # rate limit

        for repo in repos:
            full_name = repo["full_name"]
            stars = repo["stargazers_count"]
            description = repo.get("description", "") or ""

            # Descartar repos muy pequeños o irrelevantes
            if stars < 10:
                continue

            strategy = {
                "repo_name": full_name,
                "repo_url": repo["html_url"],
                "stars": stars,
                "strategy_name": f"Auto-discovered: {repo['name']}",
                "strategy_type": _infer_type(description),
                "asset_class": asset_class,
                "timeframe": _infer_timeframe(description),
                "description": description[:500],
                "entry_logic": "",
                "exit_logic": "",
                "indicators_used": _infer_indicators(description),
                "position_sizing": "",
                "risk_params": {},
                "source_files": "",
                "implementation_status": "discovered",
                "priority": _calc_priority(stars, description),
                "notes": f"Auto-discovered via search: {search_cfg['label']}",
            }

            sid = upsert_strategy(engine, strategy)
            if sid:
                log.info(f"    + Guardado: {full_name} ({stars}⭐) → id={sid}")
                total_saved += 1

    log.info(f"  Discovery completado: {total_saved} estrategias guardadas")
    return total_saved


def _infer_type(desc: str) -> str:
    desc_lower = desc.lower()
    if any(w in desc_lower for w in ["arbitrage", "arb", "latency"]):
        return "arb"
    if any(w in desc_lower for w in ["momentum", "trend", "breakout"]):
        return "momentum"
    if any(w in desc_lower for w in ["mean reversion", "mean-reversion", "bollinger"]):
        return "mean_reversion"
    if any(w in desc_lower for w in ["machine learning", "ml", "neural", "lstm"]):
        return "ml"
    if any(w in desc_lower for w in ["signal", "composite", "multi"]):
        return "composite"
    return "signal_based"


def _infer_timeframe(desc: str) -> str:
    for tf in ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]:
        if tf in desc.lower() or tf.replace("m", " minute") in desc.lower():
            return tf
    return "unknown"


def _infer_indicators(desc: str) -> str:
    indicators = []
    checks = {
        "RSI": ["rsi"],
        "MACD": ["macd"],
        "EMA": ["ema", "moving average"],
        "SMA": ["sma"],
        "VWAP": ["vwap"],
        "BB": ["bollinger"],
        "ATR": ["atr"],
        "momentum": ["momentum"],
        "volume": ["volume"],
        "sentiment": ["sentiment", "fear"],
    }
    desc_lower = desc.lower()
    for name, keywords in checks.items():
        if any(kw in desc_lower for kw in keywords):
            indicators.append(name)
    return ",".join(indicators) if indicators else ""


def _calc_priority(stars: int, desc: str) -> int:
    """Calcula prioridad 1-8 basado en estrellas y keywords relevantes."""
    score = 5
    if stars > 1000:
        score -= 2
    elif stars > 500:
        score -= 1
    elif stars > 100:
        score -= 0
    elif stars < 30:
        score += 2

    desc_lower = desc.lower()
    high_value = ["kelly", "sharpe", "edge", "profitable", "production", "backtest"]
    if any(kw in desc_lower for kw in high_value):
        score -= 1

    return max(1, min(8, score))


# ──────────────────────────────────────────────────────────────────────────────
# FASE 2: POBLAR CON REPOS MANUALES DE ALTA CALIDAD
# ──────────────────────────────────────────────────────────────────────────────
def phase_seed_manual(engine) -> int:
    """Puebla DB con repos manuales ya analizados."""
    log.info("=== POBLANDO REPOS MANUALES DE ALTA CALIDAD ===")
    saved = 0
    for r in MANUAL_REPOS:
        strategy = {
            "repo_name": r["repo"],
            "repo_url": f"https://github.com/{r['repo']}",
            "stars": r.get("stars", 0),
            "strategy_name": r["strategy_name"],
            "strategy_type": r.get("strategy_type", ""),
            "asset_class": r.get("asset_class", "crypto"),
            "timeframe": r.get("timeframe", ""),
            "description": r.get("description", ""),
            "entry_logic": r.get("entry_logic", ""),
            "exit_logic": r.get("exit_logic", ""),
            "indicators_used": r.get("indicators_used", ""),
            "position_sizing": r.get("position_sizing", ""),
            "risk_params": r.get("risk_params", {}),
            "source_files": r.get("source_files", ""),
            "implementation_status": "analyzed",
            "priority": r.get("priority", 5),
            "notes": "Manually analyzed",
        }
        sid = upsert_strategy(engine, strategy)
        if sid:
            log.info(f"  + {r['strategy_name']} ({r['repo']}) → id={sid}")
            saved += 1
        else:
            log.info(f"  ~ Ya existe: {r['strategy_name']}")
    return saved


# ──────────────────────────────────────────────────────────────────────────────
# FASE 3: ANÁLISIS DETALLADO (README scraping)
# ──────────────────────────────────────────────────────────────────────────────
def phase_analyze(engine):
    """Descarga READMEs de repos 'discovered' y actualiza descripción."""
    log.info("=== FASE 3: ANÁLISIS DE REPOS ===")

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, repo_name FROM repo_strategies "
                "WHERE implementation_status = 'discovered' "
                "AND entry_logic = '' "
                "ORDER BY priority ASC, stars DESC LIMIT 10"
            )
        ).fetchall()

    for row in rows:
        rid, repo_name = row
        log.info(f"  Analizando README: {repo_name}")
        readme = fetch_readme(repo_name)
        time.sleep(0.5)

        if readme:
            # Extraer sección de estrategia del README
            entry_logic = _extract_strategy_section(readme)
            with engine.connect() as conn:
                conn.execute(
                    text(
                        "UPDATE repo_strategies SET entry_logic=:el, "
                        "implementation_status='analyzed', updated_at=NOW() "
                        "WHERE id=:id"
                    ),
                    {"el": entry_logic[:1000], "id": rid},
                )
                conn.commit()
            log.info(f"    README extraído: {len(entry_logic)} chars")


def _extract_strategy_section(readme: str) -> str:
    """Extrae sección relevante de estrategia del README."""
    keywords = [
        "strategy", "how it works", "entry", "signal",
        "indicator", "algorithm", "approach",
    ]
    lines = readme.split("\n")
    result = []
    capture = False
    for line in lines:
        line_lower = line.lower()
        if any(kw in line_lower for kw in keywords) and line.startswith("#"):
            capture = True
        if capture:
            result.append(line)
        if capture and len(result) > 30:
            break
    return "\n".join(result) if result else readme[:500]


# ──────────────────────────────────────────────────────────────────────────────
# FASE 4: BACKTEST ADAPTER
# ──────────────────────────────────────────────────────────────────────────────
BACKTEST_ADAPTERS = {
    "BTC Microstructure + Kelly Sizing": {
        "script": "backtest.py",
        "strategy": "TrendMomentum",
        "args": "--assets BTC/USDT --tf 5m --months 12 --risk 0.01",
        "note": "Proxy: TrendMomentum es lo más cercano al RSI+Momentum multiperiodo",
    },
    "BTC 15min Multi-Signal (7-Phase)": {
        "script": "backtest.py",
        "strategy": "TrendMomentum",
        "args": "--assets BTC/USDT --tf 15m --months 24 --risk 0.01",
        "note": "Proxy: 7-phase signal fusion vs TrendMomentum en 15m",
    },
    "Pullback State Machine (4-Phase Entry)": {
        "script": "backtest.py",
        "strategy": "MeanReversion",
        "args": "--assets BTC/USDT ETH/USDT --tf 15m --months 18 --risk 0.01",
        "note": "Proxy: Pullback = MeanReversion con confirmación de tendencia",
    },
    "Smart Money Concepts (ICT) - Order Blocks + FVG": {
        "script": "backtest.py",
        "strategy": "Breakout",
        "args": "--assets BTC/USDT ETH/USDT --tf 15m --months 12 --risk 0.01",
        "note": "Proxy: Breakout captura BOS/CHoCH en SMC",
    },
}


def phase_backtest(engine):
    """Ejecuta backtests para estrategias analizadas usando el framework existente."""
    log.info("=== FASE 4: BACKTEST ===")

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id, strategy_name, asset_class FROM repo_strategies "
                "WHERE implementation_status IN ('analyzed', 'adapted') "
                "AND backtest_result IS NULL "
                "ORDER BY priority ASC LIMIT 5"
            )
        ).fetchall()

    for row in rows:
        rid, strategy_name, asset_class = row
        log.info(f"  Backtesting: {strategy_name}")

        if asset_class != "crypto":
            log.info(f"    Skipping {asset_class} (solo crypto en backtest)")
            continue

        adapter = BACKTEST_ADAPTERS.get(strategy_name)
        if not adapter:
            log.info(f"    Sin adapter definido para: {strategy_name}")
            # Usar defaults
            adapter = {
                "script": "backtest.py",
                "strategy": "TrendMomentum",
                "args": "--assets BTC/USDT --tf 15m --months 12 --risk 0.01",
            }

        csv_out = f"/opt/trading/reports/repo_bt_{rid}_{strategy_name[:20].replace(' ','_')}.csv"
        cmd = (
            f"cd /opt/trading && source venv/bin/activate && "
            f"python scripts/{adapter['script']} {adapter['args']} "
            f"--csv {csv_out} 2>&1"
        )

        log.info(f"    Corriendo: {adapter['script']} {adapter['args']}")
        try:
            result = subprocess.run(
                cmd, shell=True, capture_output=True, text=True, timeout=300
            )
            output = result.stdout + result.stderr

            # Parsear métricas del output
            metrics = _parse_backtest_output(output)
            metrics["adapter_note"] = adapter.get("note", "")
            metrics["ran_at"] = datetime.now().isoformat()

            with engine.connect() as conn:
                conn.execute(
                    text(
                        "UPDATE repo_strategies SET "
                        "backtest_result=CAST(:br AS jsonb), "
                        "implementation_status='backtested', "
                        "updated_at=NOW() WHERE id=:id"
                    ),
                    {"br": json.dumps(metrics), "id": rid},
                )
                conn.commit()

            log.info(f"    Resultado: {metrics}")

        except subprocess.TimeoutExpired:
            log.warning(f"    Timeout en backtest de {strategy_name}")
        except Exception as e:
            log.error(f"    Error en backtest: {e}")


def _parse_backtest_output(output: str) -> dict:
    """Parsea output del backtest para extraer métricas."""
    metrics = {}
    lines = output.split("\n")
    for line in lines:
        line_lower = line.lower()
        if "win rate" in line_lower or "win_rate" in line_lower:
            try:
                val = float("".join(c for c in line.split(":")[-1] if c.isdigit() or c == "."))
                metrics["win_rate"] = val / 100 if val > 1 else val
            except Exception:
                pass
        if "profit factor" in line_lower:
            try:
                metrics["profit_factor"] = float(line.split(":")[-1].strip().rstrip("%"))
            except Exception:
                pass
        if "max drawdown" in line_lower or "max_dd" in line_lower:
            try:
                val = float("".join(c for c in line.split(":")[-1] if c.isdigit() or c == "."))
                metrics["max_dd"] = val / 100 if val > 1 else val
            except Exception:
                pass
        if "sharpe" in line_lower:
            try:
                metrics["sharpe"] = float(line.split(":")[-1].strip())
            except Exception:
                pass
        if "total trades" in line_lower:
            try:
                metrics["total_trades"] = int("".join(c for c in line.split(":")[-1] if c.isdigit()))
            except Exception:
                pass
        if "return" in line_lower and "%" in line:
            try:
                val = float("".join(c for c in line.split(":")[-1] if c.isdigit() or c == "."))
                metrics["return_pct"] = val
            except Exception:
                pass
    return metrics


# ──────────────────────────────────────────────────────────────────────────────
# FASE 5: REPORTE
# ──────────────────────────────────────────────────────────────────────────────
def phase_report(engine):
    """Genera reporte de todas las estrategias encontradas y sus resultados."""
    log.info("=== REPORTE DE ESTRATEGIAS ===")

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    id, repo_name, stars, strategy_name, strategy_type,
                    asset_class, timeframe, implementation_status,
                    backtest_result, priority, description
                FROM repo_strategies
                ORDER BY priority ASC, stars DESC
                """
            )
        ).fetchall()

    print("\n" + "=" * 80)
    print("GITHUB STRATEGY HUNTER - REPORTE")
    print(f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 80)

    # Agrupar por status
    by_status: dict[str, list] = {}
    for row in rows:
        status = row[7]
        by_status.setdefault(status, []).append(row)

    for status, items in sorted(by_status.items()):
        print(f"\n[{status.upper()}] ({len(items)} estrategias)")
        print("-" * 60)
        for r in items:
            rid, repo, stars, name, stype, asset, tf, _, bt, prio, desc = r
            print(f"  P{prio} | {name}")
            print(f"       Repo: {repo} ({stars}⭐) | {stype} | {asset} | {tf}")
            if desc:
                print(f"       {desc[:100]}...")
            if bt:
                bt_data = bt if isinstance(bt, dict) else {}
                wr = bt_data.get("win_rate", "?")
                pf = bt_data.get("profit_factor", "?")
                dd = bt_data.get("max_dd", "?")
                sh = bt_data.get("sharpe", "?")
                print(f"       Backtest: WR={wr} | PF={pf} | DD={dd} | Sharpe={sh}")

    # Resumen
    print("\n" + "=" * 80)
    print(f"TOTAL: {len(rows)} estrategias en DB")
    print("Prioridad 1 (deploy candidates):")
    for r in rows:
        if r[9] == 1 and r[7] == "backtested":
            bt = r[8] or {}
            wr = bt.get("win_rate", 0) if isinstance(bt, dict) else 0
            pf = bt.get("profit_factor", 0) if isinstance(bt, dict) else 0
            if wr >= 0.45 and pf >= 1.2:
                print(f"  *** DEPLOY CANDIDATE: {r[3]} (WR={wr:.1%}, PF={pf:.2f})")
    print("=" * 80 + "\n")


# ──────────────────────────────────────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="GitHub Strategy Hunter")
    parser.add_argument(
        "--phase",
        choices=["discover", "seed", "analyze", "backtest", "report", "all"],
        default="all",
        help="Fase a ejecutar",
    )
    args = parser.parse_args()

    engine = get_engine()

    if args.phase in ("seed", "all"):
        n = phase_seed_manual(engine)
        log.info(f"Repos manuales sembrados: {n}")

    if args.phase in ("discover", "all"):
        n = phase_discover(engine)
        log.info(f"Repos descubiertos: {n}")

    if args.phase in ("analyze", "all"):
        phase_analyze(engine)

    if args.phase in ("backtest", "all"):
        phase_backtest(engine)

    if args.phase in ("report", "all"):
        phase_report(engine)


if __name__ == "__main__":
    main()
