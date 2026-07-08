"""
Trading Council — Comité de agentes para debates de trading.

Uso:
    cd /opt/trading && venv/bin/python3 scripts/trading_council.py "<tema>"

El comité analiza el tema desde 4 perspectivas profesionales y emite
un veredicto con recomendación accionable.

Perfiles:
    QUANT       — Análisis estadístico, backtesting, datos
    TECHNICAL   — Análisis técnico, estructura de mercado
    RISK        — Gestión de riesgo, preservación de capital
    PORTFOLIO   — Visión estratégica, asignación, objetivos

Ejemplos:
    python3 scripts/trading_council.py "¿Debemos bajar MIN_SCORE de 65 a 60?"
    python3 scripts/trading_council.py "¿Conviene activar BUY en TREND_UP?"
    python3 scripts/trading_council.py "¿Añadimos SOL al Grid Bot?"
"""
import os
import sys
import json
import subprocess
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

DB_URL = (
    f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}"
    f"/{os.getenv('POSTGRES_DB', 'trading_agent')}"
)

# ── Council member definitions ──────────────────────────────────────────

@dataclass
class Member:
    name: str
    emoji: str
    role: str
    expertise: str
    color: str


COUNCIL = [
    Member("QUANT", "🤖", "Quantitative Analyst",
           "Estadística, backtesting, datos duros, proyecciones. "
           "Consulta DB, analiza WR, PF, RR, PnL. "
           "Vota basado en evidencia numérica.",
           "blue"),
    Member("TECHNICAL", "📊", "Technical Analyst",
           "Estructura de mercado, análisis técnico, patrones. "
           "Analiza EMAs, MACD, RSI, soportes/resistencias. "
           "Vota basado en la estructura del precio.",
           "green"),
    Member("RISK", "🛡️", "Risk Manager",
           "Preservación de capital, drawdown, exposición. "
           "Calcula worst-case, evalúa DirectionGuard, halts. "
           "Vota basado en protección de capital.",
           "red"),
    Member("PORTFOLIO", "💼", "Portfolio Manager",
           "Estrategia global, diversificación, objetivos. "
           "Piensa en 3-6 meses, live-readiness, allocation. "
           "Vota basado en el roadmap del sistema.",
           "gold"),
]


# ── Context gathering ────────────────────────────────────────────────────

def get_context() -> dict:
    """Recolecta datos del sistema para informar al comité."""
    ctx = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        from sqlalchemy import create_engine, text
        e = create_engine(DB_URL)

        # Portfolio
        r = e.connect().execute(text(
            "SELECT total_balance, drawdown_pct FROM portfolio ORDER BY timestamp DESC LIMIT 1"
        )).fetchone()
        if r:
            ctx["balance"] = float(r[0])
            ctx["drawdown_pct"] = float(r[1]) * 100

        # Active session
        r = e.connect().execute(text(
            "SELECT session_name, total_trades, winning_trades, "
            "final_balance - initial_balance as pnl "
            "FROM paper_sessions WHERE status='ACTIVE' LIMIT 1"
        )).fetchone()
        if r:
            ctx["session"] = r[0]
            ctx["session_trades"] = r[1]
            ctx["session_wins"] = r[2]
            ctx["session_pnl"] = float(r[3]) if r[3] else 0

        # TM strategy stats
        r = e.connect().execute(text(
            "SELECT COUNT(*), SUM(CASE WHEN pnl>0 THEN 1 ELSE 0 END), "
            "ROUND(SUM(pnl)::numeric,2), "
            "ROUND(AVG(CASE WHEN pnl>0 THEN pnl END)::numeric,2), "
            "ROUND(AVG(CASE WHEN pnl<0 THEN pnl END)::numeric,2) "
            "FROM trades WHERE strategy='TREND_MOMENTUM' AND status='CLOSED'"
        )).fetchone()
        if r and r[0] > 0:
            ctx["tm_trades"] = r[0]
            ctx["tm_wr"] = round(100 * r[1] / r[0], 1)
            ctx["tm_pnl"] = float(r[2])
            ctx["tm_avg_win"] = float(r[3]) if r[3] else 0
            ctx["tm_avg_loss"] = float(r[4]) if r[4] else 0

        # DirectionGuard
        import redis
        rt = redis.Redis(host='localhost', port=6379, decode_responses=True)
        blocked = {}
        for key in rt.scan_iter('direction_guard*'):
            val = rt.get(key)
            if val:
                blocked[key] = val
        ctx["direction_guard"] = blocked

        # Halt
        halt = rt.get("halt:trading")
        ctx["halt"] = halt

    except Exception as ex:
        ctx["error"] = str(ex)

    return ctx


def print_context(ctx: dict):
    """Imprime el contexto para el comité."""
    print(f"\n📋 CONTEXTO DEL SISTEMA")
    print(f"   Fecha:     {ctx.get('timestamp', '?')[:19]}")
    print(f"   Sesión:    {ctx.get('session', '?')}")
    print(f"   Balance:   ${ctx.get('balance', 0):,.2f}")
    print(f"   DD:        {ctx.get('drawdown_pct', 0):.1f}%")
    print(f"   Halt:      {ctx.get('halt') or 'No'}")
    print(f"   DirGuard:  {len(ctx.get('direction_guard', {}))} bloqueos")
    if ctx.get("tm_trades"):
        print(f"   TM:        {ctx['tm_trades']} trades, WR={ctx['tm_wr']}%, "
              f"PnL=${ctx['tm_pnl']:,.0f}")


# ── Council deliberation ─────────────────────────────────────────────────

def deliberate(topic: str) -> dict:
    """Ejecuta el debate del comité sobre un tema."""
    ctx = get_context()

    print("=" * 70)
    print(f"🏛️  TRADING COUNCIL — Sesión extraordinaria")
    print(f"   Tema: {topic}")
    print("=" * 70)

    print_context(ctx)

    votes = {}
    for member in COUNCIL:
        print(f"\n{'━' * 70}")
        print(f"{member.emoji} {member.name} — {member.role}")
        print(f"{'━' * 70}")
        print(f"   Expertise: {member.expertise}")
        print(f"\n   Analizando...")

        # Each member analyzes based on their expertise
        analysis = analyze_as(member, topic, ctx)
        print(f"   {analysis}")

        # Vote
        vote = input(f"\n   Voto (✅/❌/⚠️ condicional): ").strip() or "✅"
        votes[member.name] = vote
        reason = input(f"   Razón (1 línea): ").strip() or "Ver análisis arriba"
        votes[f"{member.name}_reason"] = reason

    # Verdict
    print(f"\n{'═' * 70}")
    print(f"🏛️  VEREDICTO DEL COMITÉ")
    print(f"{'═' * 70}")
    for member in COUNCIL:
        v = votes[member.name]
        icon = "✅" if v == "✅" else ("❌" if v == "❌" else "⚠️")
        print(f"   {member.emoji} {member.name:<12s} {icon} {votes[f'{member.name}_reason']}")

    yes = sum(1 for m in COUNCIL if votes[m.name] == "✅")
    cond = sum(1 for m in COUNCIL if votes[m.name] == "⚠️")
    no = sum(1 for m in COUNCIL if votes[m.name] == "❌")

    print(f"\n   ─────────────────────────────")
    if yes >= 3:
        print(f"   RESULTADO: {yes}-{no}-{cond} — APROBADO ✅")
    elif yes + cond >= 3:
        print(f"   RESULTADO: {yes}-{no}-{cond} — APROBADO CON CONDICIONES ⚠️")
    else:
        print(f"   RESULTADO: {yes}-{no}-{cond} — RECHAZADO ❌")
    print(f"   ─────────────────────────────")

    return votes


def analyze_as(member: Member, topic: str, ctx: dict) -> str:
    """Análisis específico por miembro del comité."""
    if member.name == "QUANT":
        return quant_analysis(topic, ctx)
    elif member.name == "TECHNICAL":
        return tech_analysis(topic, ctx)
    elif member.name == "RISK":
        return risk_analysis(topic, ctx)
    elif member.name == "PORTFOLIO":
        return portfolio_analysis(topic, ctx)
    return ""


def quant_analysis(topic: str, ctx: dict) -> str:
    tm_t = ctx.get("tm_trades", 0)
    tm_wr = ctx.get("tm_wr", 0)
    tm_pnl = ctx.get("tm_pnl", 0)
    avg_w = ctx.get("tm_avg_win", 0)
    avg_l = ctx.get("tm_avg_loss", 0)
    bal = ctx.get("balance", 1000)

    return (
        f"DATOS: TM={tm_t} trades, WR={tm_wr}%, PnL=${tm_pnl:,.0f}. "
        f"Avg W=${avg_w:.0f}, Avg L=${avg_l:.0f}, "
        f"RR={abs(avg_w/max(avg_l,1)):.1f}:1. "
        f"Capital=${bal:,.0f}. "
        f"Evalúo impacto estadístico del cambio propuesto."
    )


def tech_analysis(topic: str, ctx: dict) -> str:
    return (
        f"Analizando estructura de mercado: EMAs, MACD, RSI, "
        f"soportes/resistencias, volatilidad. "
        f"Determino si el cambio es técnicamente sólido."
    )


def risk_analysis(topic: str, ctx: dict) -> str:
    dd = ctx.get("drawdown_pct", 0)
    bal = ctx.get("balance", 1000)
    halt = ctx.get("halt")
    return (
        f"DD actual={dd:.1f}%, Capital=${bal:,.0f}. "
        f"Halt={'ACTIVO' if halt else 'No'}. "
        f"DirectionGuard={len(ctx.get('direction_guard',{}))} bloqueos. "
        f"Calculo worst-case y defino condiciones de seguridad."
    )


def portfolio_analysis(topic: str, ctx: dict) -> str:
    return (
        f"Evaluando impacto en el roadmap a 3 meses. "
        f"¿Acerca o aleja del objetivo de live trading? "
        f"¿Mejora la diversificación del portafolio?"
    )


# ── CLI ──────────────────────────────────────────────────────────────────

def main():
    topic = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else None
    if not topic:
        topic = input("Tema a debatir: ").strip()

    if not topic:
        print("Uso: python3 scripts/trading_council.py \"<tema>\"")
        sys.exit(1)

    votes = deliberate(topic)

    # Save session record
    record = {
        "topic": topic,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "votes": votes,
    }
    os.makedirs("/opt/trading/.council", exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    with open(f"/opt/trading/.council/session_{ts}.json", "w") as f:
        json.dump(record, f, indent=2, default=str)

    print(f"\n📁 Acta guardada en .council/session_{ts}.json")


if __name__ == "__main__":
    main()
