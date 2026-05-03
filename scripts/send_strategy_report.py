"""
send_strategy_report.py - Genera y envía por Telegram un PDF con todas las
estrategias del sistema Arthas Trading.

Uso:
    /opt/trading/venv/bin/python3 scripts/send_strategy_report.py
"""
import os
import sys
import tempfile
from datetime import datetime

sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv

load_dotenv('/opt/trading/config/.env')

import requests
from fpdf import FPDF

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN', '8179816401:AAHF3xprmPeauuOapGDD9idQrLsv8Dl2EYE')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '999936393')

# ── Datos de cada estrategia ──────────────────────────────────────────────────

STRATEGIES = [
    # ── TRADING AGENT ──────────────────────────────────────────────────────────
    {
        'agent': 'TRADING AGENT  (Crypto / Metales Spot)',
        'name': '1. TREND MOMENTUM  [OK]  ACTIVA',
        'tipo': 'Momentum Tendencial',
        'mercado': 'BTC, ETH, XAU, XAG (Kraken + OKX)',
        'logica': (
            'Detecta regímenes TREND_DOWN o BREAKOUT_DOWN usando EMA 20/50/200, '
            'RSI 14 y volumen relativo. Solo ejecuta SELL (short) - los BUY en '
            'TREND_UP fueron bloqueados tras backtest 2Y que mostró -$6,151.'
        ),
        'entrada': 'EMA 20 < EMA 50 < EMA 200  +  RSI < 50  +  vol_ratio >= 1.5',
        'salida': 'TP: 2×ATR  |  SL: 1×ATR  |  Trailing dinámico activado en 1R',
        'riesgo': '0.5% del balance por trade  |  Max 3 trades simultáneos',
        'resultado': 'SESSION_008: +$1,246 en 10 días  |  PF: 1.46  |  EV: $5.49/trade',
        'estado': 'ACTIVA - es el motor principal del sistema',
    },
    {
        'agent': 'TRADING AGENT  (Crypto / Metales Spot)',
        'name': '2. BREAKOUT  [OK]  ACTIVA',
        'tipo': 'Ruptura de rango',
        'mercado': 'BTC, ETH, XAU, XAG',
        'logica': (
            'Identifica compresión de precio (Bollinger Bands estrechas) seguida '
            'de ruptura con volumen anormalmente alto. Complementa a Trend Momentum '
            'en los primeros impulsos antes de que la tendencia sea confirmada.'
        ),
        'entrada': 'Precio rompe banda superior/inferior  +  vol_ratio >= 2.0',
        'salida': 'TP: 1.5×ATR  |  SL: 0.8×ATR',
        'riesgo': '0.5% del balance  |  Comparte cupo con Trend Momentum',
        'resultado': 'Activo - estadísticas incorporadas a SESSION_008',
        'estado': 'ACTIVA',
    },
    {
        'agent': 'TRADING AGENT  (Crypto / Metales Spot)',
        'name': '3. GRID BOT  [OK]  ACTIVA (condicional)',
        'tipo': 'Grid / Market Making',
        'mercado': 'BTC, ETH en rango lateral',
        'logica': (
            'Se activa solo en régimen RANGE o CHOPPY. Coloca una cuadrícula de '
            'órdenes compra/venta equiespaciadas. Captura oscilaciones sin necesitar '
            'dirección. Se desactiva automáticamente cuando el régimen cambia a TREND.'
        ),
        'entrada': 'Régimen RANGE/CHOPPY  +  ATR/precio < 1.5%',
        'salida': 'Cada par de órdenes se cierra en su nivel opuesto de la grilla',
        'riesgo': '5% del balance total dedicado a la grilla',
        'resultado': 'Condicional - no ha tenido sesiones largas de RANGE aún',
        'estado': 'ACTIVA - solo opera en mercados laterales',
    },
    {
        'agent': 'TRADING AGENT  (Crypto / Metales Spot)',
        'name': '4. MEAN REVERSION  [X]  DESACTIVADA',
        'tipo': 'Reversión a la media',
        'mercado': 'BTC, ETH',
        'logica': 'Compraba en oversold extremo (RSI < 20) esperando rebote.',
        'entrada': 'RSI < 20  +  precio < BB inferior  +  divergencia alcista',
        'salida': 'TP: BB media  |  SL: 2% bajo entrada',
        'riesgo': '-',
        'resultado': '8 trades  |  0 wins  |  PnL: -$569',
        'estado': 'DESACTIVADA - crypto en tendencias no revierte predeciblemente',
    },
    # ── OPTIONS AGENT ──────────────────────────────────────────────────────────
    {
        'agent': 'OPTIONS AGENT  (Deribit BTC)',
        'name': '5. THETA FARMING  [OK]  ACTIVA',
        'tipo': 'Venta de opciones / Theta decay',
        'mercado': 'BTC PUT OTM en Deribit',
        'logica': (
            'Vende PUTs BTC out-of-the-money cuando la volatilidad implícita (IV) '
            'está alta respecto a su historia (IV Rank 252d >= 30%). Cobra la prima '
            'y espera que el tiempo destruya el valor. La posición gana dinero '
            'todos los días que el precio no cae drásticamente.'
        ),
        'entrada': 'IV Rank 252d >= 30%  |  Strike: -15% del precio spot  |  Exp: 14-21 días',
        'salida': 'Cierre al 50% de la prima cobrada  |  SL si IV sube +30%',
        'riesgo': 'Max 3% del balance por PUT vendido  |  Delta neta < 0.20',
        'resultado': 'Paper mode - sin resultados aún (infraestructura validada)',
        'estado': 'ACTIVA en paper - pendiente validación antes de live',
    },
    # ── POLYMARKET AGENT ───────────────────────────────────────────────────────
    {
        'agent': 'POLYMARKET AGENT  (Mercados de Predicción)',
        'name': '6. SIGNAL BASED  [OK]  ACTIVA',
        'tipo': 'Señales técnicas aplicadas a predicciones',
        'mercado': 'Mercados Polymarket de BTC/ETH con vencimiento corto',
        'logica': (
            'Lee las señales técnicas 1H y 4H del Trading Agent (tabla signals en DB). '
            'Si BTC tiene 4+ señales SELL en los últimos 30 min -> compra NO en '
            '"Will BTC reach $X?". Si hay señales BUY -> compra YES. '
            'Edge mínimo requerido: 10%.'
        ),
        'entrada': '>=4 señales alineadas en 30 min  +  edge >= 10%  +  precio entrada <= 0.90',
        'salida': 'TP: precio >= 0.95  |  SL: precio <= 0.30  |  Resolución del mercado',
        'riesgo': '2.5% del balance poly por posición  |  Max 8 posiciones',
        'resultado': 'WR ~60%  |  PnL neto -$70 (PnL paper antes del hub)',
        'estado': 'ACTIVA - parte del hub multi-estrategia',
    },
    {
        'agent': 'POLYMARKET AGENT  (Mercados de Predicción)',
        'name': '7. TAIL END  [OK]  NUEVA',
        'tipo': 'Near-resolution yield farming',
        'mercado': 'Cualquier mercado Polymarket binario',
        'logica': (
            'Busca mercados donde un outcome ya está casi resuelto (precio >= 93%) '
            'pero aún faltan 1h-7 días para el vencimiento. Compra ese outcome '
            'para capturar el 2-7% restante con riesgo bajo. '
            'Similar a comprar un bono que vence pronto a descuento.'
        ),
        'entrada': 'price_yes >= 0.93  |  1h <= tiempo_restante <= 7 días  |  volumen >= $1,000',
        'salida': 'Resolución del mercado (cobra $1 por share)  |  SL si precio < 0.88',
        'riesgo': '2.5% balance  |  Retorno mínimo requerido: 2%',
        'resultado': 'NUEVA - sin historial (activada Abril 2026)',
        'estado': 'ACTIVA en hub',
    },
    {
        'agent': 'POLYMARKET AGENT  (Mercados de Predicción)',
        'name': '8. LATE ENTRY V3  [OK]  NUEVA',
        'tipo': 'Momentum de corto plazo / Last-minute consensus',
        'mercado': 'Mercados crypto Polymarket de 15 minutos',
        'logica': (
            'En los últimos 4 minutos antes de que cierre un mercado de 15 min, '
            'entra al lado favorito (el que cotiza más alto). El precio del mercado '
            'ya incorporó toda la información - se aprovecha la convergencia final '
            'hacia 1.0. Requiere diferencia YES/NO >= 30% para evitar mercados inciertos.'
        ),
        'entrada': 'Faltan <= 240s para el cierre  |  |YES - NO| >= 0.30  |  precio favorito <= 0.92',
        'salida': 'Resolución automática al cierre del mercado',
        'riesgo': '2.5% balance  |  SL si precio cae a 0.48',
        'resultado': 'NUEVA - sin historial (activada Abril 2026)',
        'estado': 'ACTIVA en hub',
    },
    {
        'agent': 'POLYMARKET AGENT  (Mercados de Predicción)',
        'name': '9. LEGGED ARB  [OK]  NUEVA',
        'tipo': 'Arbitraje en 2 fases',
        'mercado': 'Mercados Polymarket binarios con alta volatilidad',
        'logica': (
            'FASE 1: Compra YES cuando cotiza muy barato (<= 0.30) y NO cotiza >= 0.60. '
            'FASE 2: Espera a que el mercado oscile. Cuando YES+NO < 0.95, '
            'compra NO también. Al resolver, uno de los dos paga $1 -> '
            'profit garantizado de al menos 5%. Sin riesgo direccional.'
        ),
        'entrada': 'F1: price_yes <= 0.30  |  F2: yes_cost + no_precio < 0.95',
        'salida': 'Resolución del mercado (uno paga $1, el otro $0)',
        'riesgo': 'Max $30 total por par  |  Timeout: 14 días si F2 nunca llega',
        'resultado': 'NUEVA - 1er trade ejecutado (Pete Hegseth, edge 25.5%)',
        'estado': 'ACTIVA en hub',
    },
    {
        'agent': 'POLYMARKET AGENT  (Mercados de Predicción)',
        'name': '10. COMBINATORIAL ARB  [OK]  NUEVA',
        'tipo': 'Arbitraje lógico / Violaciones de monotonicidad',
        'mercado': 'Grupos de mercados relacionados en Polymarket',
        'logica': (
            'Detecta contradicciones matemáticas entre mercados relacionados. '
            'Ejemplo: si "BTC >= $77k" cotiza al 21% pero "BTC >= $78k" cotiza al 80%, '
            'es imposible - el precio más alto SIEMPRE debe tener probabilidad MENOR. '
            'Compra NO en el mercado "caro" que viola la lógica.'
        ),
        'entrada': 'P(threshold_alto) > P(threshold_bajo) + 5% en mismo activo/período',
        'salida': 'Resolución del mercado (la lógica eventualmente se cumple)',
        'riesgo': '2.5% balance  |  Edge mínimo: 5% de violación',
        'resultado': 'NUEVA - detectó 5 violaciones BTC en primer ciclo (Abril 2026)',
        'estado': 'ACTIVA en hub',
    },
    # ── STOCKS AGENT ───────────────────────────────────────────────────────────
    {
        'agent': 'STOCKS AGENT  (NYSE / NASDAQ)',
        'name': '11. STOCKS MOMENTUM  [...]  PAPER (pendiente Alpaca)',
        'tipo': 'Momentum acciones USA',
        'mercado': 'NVDA, TSLA, AAPL, META, AMZN, SPY, QQQ, GLD',
        'logica': (
            'Evalúa momentum en acciones USA usando OHLCV de Alpaca. '
            'SPY y QQQ actúan como filtro macro: si ambos están en bajada, '
            'bloquea todas las compras. Boost extra de +15 puntos si la señal '
            'está alineada con xsignals (@aguti00, WR validado 71.4% a 48h).'
        ),
        'entrada': 'Momentum score >= 60  +  macro bias BULL/NEUTRAL  +  xsignal alineada (opcional)',
        'salida': 'TP: +3%  |  SL: -1.5%  |  Trailing si profit > 2%',
        'riesgo': '1% balance por trade  |  Max 3 simultáneos  |  Max 8% exposición',
        'resultado': 'Sin trades aún - pendiente claves API Alpaca',
        'estado': 'PAPER MODE - activar con claves Alpaca en alpaca.markets',
    },
    # ── BTC DIRECTION ──────────────────────────────────────────────────────────
    {
        'agent': 'BTC DIRECTION  (Mercados 15-min Polymarket)',
        'name': '12. BTC DIRECTION MULTI-TF  [!]  VIGILANCIA',
        'tipo': 'Predicción direccional BTC corto plazo',
        'mercado': 'Mercados "BTC sube/baja en 15 min" en Polymarket',
        'logica': (
            'Analiza 5 timeframes (5m, 15m, 1H, 4H, Daily) para predecir si BTC '
            'sube o baja en los próximos 15 minutos. Cuando 4+ TF están alineados, '
            'entra al mercado de predicción correspondiente.'
        ),
        'entrada': '>=4 TF alineados  +  momentum score >= 70  +  no cooldown activo',
        'salida': 'Resolución automática del mercado 15-min',
        'riesgo': '1% balance por trade',
        'resultado': 'WR: 27.6%  |  105 trades  |  PnL: -$329  <- bajo vigilancia',
        'estado': 'VIGILANCIA - WR por debajo del mínimo (40%). Analizando causas.',
    },
]


class ArthasPDF(FPDF):
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=15)

    def header(self):
        self.set_fill_color(15, 15, 30)
        self.rect(0, 0, 210, 18, 'F')
        self.set_font('Helvetica', 'B', 11)
        self.set_text_color(0, 200, 150)
        self.set_y(4)
        self.cell(0, 10, 'ARTHAS TRADING SYSTEM - Manual de Estrategias', align='C')
        self.set_text_color(0, 0, 0)
        self.ln(12)

    def footer(self):
        self.set_y(-13)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 10, f'Arthas Trading  |  Abril 2026  |  Pág. {self.page_no()}', align='C')
        self.set_text_color(0, 0, 0)

    def add_cover(self):
        self.add_page()
        # Fondo oscuro
        self.set_fill_color(15, 15, 30)
        self.rect(0, 0, 210, 297, 'F')

        self.ln(30)
        self.set_font('Helvetica', 'B', 28)
        self.set_text_color(0, 200, 150)
        self.cell(0, 14, 'ARTHAS', align='C')
        self.ln(10)
        self.set_font('Helvetica', 'B', 16)
        self.set_text_color(200, 200, 200)
        self.cell(0, 10, 'TRADING SYSTEM', align='C')
        self.ln(14)
        self.set_font('Helvetica', '', 13)
        self.set_text_color(150, 150, 150)
        self.cell(0, 8, 'Manual Completo de Estrategias', align='C')
        self.ln(6)
        self.cell(0, 8, '12 estrategias  |  4 agentes  |  Paper Trading', align='C')
        self.ln(40)

        # Separador
        self.set_draw_color(0, 200, 150)
        self.set_line_width(0.5)
        self.line(40, self.get_y(), 170, self.get_y())
        self.ln(12)

        self.set_font('Helvetica', '', 10)
        self.set_text_color(100, 180, 255)
        self.cell(0, 8, 'VPS: 187.77.5.109  |  Dashboard: :3000', align='C')
        self.ln(8)
        self.cell(0, 8, f'Generado: {datetime.now().strftime("%d/%m/%Y %H:%M")} UTC', align='C')
        self.ln(30)

        # Tabla resumen
        self.set_font('Helvetica', 'B', 11)
        self.set_text_color(0, 200, 150)
        self.cell(0, 8, 'RESUMEN DE AGENTES', align='C')
        self.ln(10)

        agents_summary = [
            ('Trading Agent', 'Crypto/Metales', '+$1,246 (SESSION_008)', '[OK] ACTIVO'),
            ('Options Agent', 'BTC PUT OTM Deribit', 'Paper, sin trades aun', '[OK] ACTIVO'),
            ('Polymarket Agent', 'Predicciones (5 estrats)', 'WR 60%, hub activo', '[OK] ACTIVO'),
            ('BTC Direction', 'BTC 15-min markets', 'WR 27.6% - VIGILANCIA', '[!]  VIGILAR'),
        ]

        col_w = [42, 44, 58, 36]
        headers = ['Agente', 'Mercado', 'Resultado', 'Estado']
        self.set_font('Helvetica', 'B', 9)
        self.set_fill_color(0, 120, 90)
        self.set_text_color(255, 255, 255)
        x_start = (210 - sum(col_w)) / 2
        self.set_x(x_start)
        for i, h in enumerate(headers):
            self.cell(col_w[i], 7, h, border=1, fill=True, align='C')
        self.ln()

        self.set_font('Helvetica', '', 9)
        for row in agents_summary:
            self.set_x(x_start)
            self.set_fill_color(30, 30, 50)
            self.set_text_color(200, 200, 200)
            for i, val in enumerate(row):
                self.cell(col_w[i], 6, val, border=1, fill=True, align='C')
            self.ln()

        self.set_text_color(0, 0, 0)

    def add_strategy(self, s: dict, is_first_in_agent: bool):
        self.add_page()

        # Banner del agente
        if is_first_in_agent:
            self.set_fill_color(20, 30, 55)
            self.rect(10, 18, 190, 10, 'F')
            self.set_font('Helvetica', 'B', 10)
            self.set_text_color(100, 180, 255)
            self.set_y(19)
            self.set_x(10)
            self.cell(190, 8, s['agent'], align='C')
            self.ln(14)
        else:
            self.set_y(20)

        # Nombre de la estrategia
        self.set_fill_color(0, 80, 60)
        self.set_font('Helvetica', 'B', 13)
        self.set_text_color(200, 255, 230)
        self.set_x(10)
        self.cell(190, 9, s['name'], fill=True, align='C')
        self.ln(12)

        # Tipo
        self.set_font('Helvetica', 'BI', 10)
        self.set_text_color(80, 140, 255)
        self.cell(0, 6, f"Tipo: {s['tipo']}   |   Mercado: {s['mercado']}")
        self.ln(10)

        def section(title, body):
            self.set_font('Helvetica', 'B', 9)
            self.set_fill_color(30, 45, 80)
            self.set_text_color(150, 200, 255)
            self.set_x(10)
            self.cell(190, 6, f'  {title}', fill=True)
            self.ln(7)
            self.set_font('Helvetica', '', 9)
            self.set_text_color(40, 40, 40)
            self.set_x(14)
            self.multi_cell(182, 5, body)
            self.ln(4)

        section('LOGICA DE LA ESTRATEGIA', s['logica'])
        section('CONDICIONES DE ENTRADA', s['entrada'])
        section('CONDICIONES DE SALIDA', s['salida'])
        section('GESTION DE RIESGO', s['riesgo'])
        section('RESULTADO EN PAPER', s['resultado'])

        # Estado badge
        self.ln(2)
        color = (0, 140, 80) if 'ACTIVA' in s['estado'] else (180, 80, 0) if 'VIGILANCIA' in s['estado'] else (100, 100, 100)
        self.set_fill_color(*color)
        self.set_font('Helvetica', 'B', 9)
        self.set_text_color(255, 255, 255)
        self.set_x(10)
        self.cell(190, 7, f"ESTADO:  {s['estado']}", fill=True, align='C')
        self.set_text_color(0, 0, 0)


def build_pdf(path: str):
    pdf = ArthasPDF()
    pdf.add_cover()

    prev_agent = None
    for s in STRATEGIES:
        is_first = s['agent'] != prev_agent
        pdf.add_strategy(s, is_first)
        prev_agent = s['agent']

    pdf.output(path)
    print(f'PDF generado: {path}')


def send_telegram(path: str):
    url = f'https://api.telegram.org/bot{TOKEN}/sendDocument'
    caption = (
        f'📊 *ARTHAS TRADING - Manual de Estrategias*\n'
        f'12 estrategias | 4 agentes | Paper Trading\n'
        f'Generado: {datetime.now().strftime("%d/%m/%Y %H:%M")} UTC'
    )
    with open(path, 'rb') as f:
        resp = requests.post(
            url,
            data={'chat_id': CHAT_ID, 'caption': caption, 'parse_mode': 'Markdown'},
            files={'document': ('Arthas_Estrategias.pdf', f, 'application/pdf')},
            timeout=30,
        )
    if resp.ok:
        print('PDF enviado por Telegram correctamente.')
    else:
        print(f'Error Telegram: {resp.status_code} {resp.text}')


if __name__ == '__main__':
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
        path = tmp.name
    build_pdf(path)
    send_telegram(path)
    os.unlink(path)
