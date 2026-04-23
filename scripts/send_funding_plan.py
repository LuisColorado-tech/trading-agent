"""
send_funding_plan.py - Genera PDF del Plan de Funding 2026-2027 y lo envia por Telegram.

Uso:
    python3 /opt/trading/scripts/send_funding_plan.py
"""
import io
import os
import sys
import requests
from datetime import datetime

sys.path.insert(0, '/opt/trading')
from fpdf import FPDF, XPos, YPos

TELEGRAM_TOKEN = '8179816401:AAHF3xprmPeauuOapGDD9idQrLsv8Dl2EYE'
TELEGRAM_CHAT  = '999936393'

# ?? Datos reales de la DB ????????????????????????????????????????????????????

SESSIONS = [
    ('SESSION_001', 'FAILED',    38,   7,  -7.66, 20.28, 0.49),
    ('SESSION_002', 'FAILED',     2,   1,  +0.67,  0.98, 1.67),
    ('SESSION_003', 'CLOSED',     0,   0,   0.00,  0.00, 0.00),
    ('SESSION_004', 'FAILED',    12,   4,  -1.06,  1.94, 0.56),
    ('SESSION_005', 'FAILED',     0,   0,  -0.30,  0.00, 0.00),
    ('SESSION_006', 'COMPLETED',  8,   2,  -0.30,  0.00, 0.00),
    ('SESSION_007', 'COMPLETED', 100, 42,  +0.92,  1.30, 1.08),
    ('SESSION_008', 'ACTIVE',    227,125, +12.34,   '?', 0.00),  # 10 dias activa
]

# SESSION_008 datos reales (desde trades directos, $10,092 -> ~$11,339)
S8 = {
    'inicio':   'Abr 12, 2026',
    'dias':     10,
    'balance_inicial': 10092.23,
    'balance_actual':  11338.78,
    'retorno':   12.34,  # %
    'trades':    227,
    'wins':      125,
    'wr':        55.1,   # %
    'pnl':       1246.55,
    'trend_pnl': 437.34,
    'grid_pnl':  809.21,
    'trend_wr':  54.9,
    'grid_wr':   55.1,
}

# Polymarket SIGNAL_BASED (ultimos datos)
POLY = {
    'trades':  38,
    'wr':      60.5,
    'pnl':     -70,  # aun negativo pero WR bueno
    'edge_min': 15,  # nuevo minimo tras ajuste
    'max_pos':   2.5,
}

# Options / Theta Farming
OPTIONS = {
    'posiciones': 2,
    'wins': 1,
    'pnl': 251.42,
    'balance_inicial': 2000,
    'balance_actual': 1461.97,   # con margen en uso
    'peak': 2251.42,
    'retorno_peak': 12.57,  # % desde inicio hasta peak
}

# BTC Direction
BTC_DIR = {
    'trades': 105,
    'wins': 29,
    'wr': 27.6,
    'pnl': -329,
    'status': 'Bajo vigilancia',
}

# ?? Plan de Funding ??????????????????????????????????????????????????????????

FUNDING_PLAN = [
    # (mes, ano, aporte, saldo_acum, retorno_est, nota)
    ('Jul', 2026,  300,  300,   6,   'Arranque minimo - solo Trading Agent'),
    ('Ago', 2026,  100,  406,   8,   ''),
    ('Sep', 2026,  100,  514,  10,   'Grid Bot cubre comisiones'),
    ('Oct', 2026,  100,  624,  12,   'Evaluar Polymarket SIGNAL (2 meses sin perdidas)'),
    ('Nov', 2026,  100,  736,  15,   ''),
    ('Dic', 2026,  100,  851,  17,   ''),
    ('Ene', 2027,  100,  968,  19,   ''),
    ('Feb', 2027,  100, 1087,  22,   'Bot cubre el VPS (~$20/mes)'),
    ('Mar', 2027,  100, 1209,  24,   'Evaluar Options Theta en live si paper >3 meses positivo'),
    ('Jun', 2027,    0, 1500,  30,   'Objetivo: $1,500 - capital autosostenible'),
]


# ?? PDF ??????????????????????????????????????????????????????????????????????

class PDF(FPDF):
    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=15)

    def header(self):
        self.set_fill_color(15, 15, 30)
        self.rect(0, 0, 210, 22, 'F')
        self.set_text_color(0, 212, 170)
        self.set_font('Helvetica', 'B', 13)
        self.set_y(6)
        self.cell(0, 10, 'ARTHAS TRADING SYSTEM  -  Plan de Funding 2026-2027', align='C')
        self.set_text_color(0, 0, 0)

    def footer(self):
        self.set_y(-12)
        self.set_font('Helvetica', '', 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, f'Generado {datetime.now().strftime("%d/%m/%Y %H:%M")} UTC  |  Paper trading - no garantiza resultados futuros', align='C')

    def section_title(self, title, r=15, g=15, b=30):
        self.ln(4)
        self.set_fill_color(r, g, b)
        self.set_text_color(255, 255, 255)
        self.set_font('Helvetica', 'B', 10)
        self.cell(0, 7, f'  {title}', new_x=XPos.LMARGIN, new_y=YPos.NEXT, fill=True)
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def kpi_row(self, items):
        """Fila de KPIs: lista de (label, valor, color_valor)"""
        col_w = (self.w - 20) / len(items)
        self.set_font('Helvetica', '', 8)
        for label, valor, color in items:
            x = self.get_x()
            y = self.get_y()
            self.set_fill_color(245, 247, 250)
            self.rect(x, y, col_w - 1, 14, 'F')
            self.set_font('Helvetica', '', 7)
            self.set_text_color(100, 100, 100)
            self.set_xy(x + 1, y + 1)
            self.cell(col_w - 2, 4, label)
            self.set_font('Helvetica', 'B', 9)
            self.set_text_color(*color)
            self.set_xy(x + 1, y + 6)
            self.cell(col_w - 2, 6, valor)
            self.set_xy(x + col_w, y)
        self.ln(15)
        self.set_text_color(0, 0, 0)

    def two_col_table(self, headers, rows, col_widths):
        self.set_font('Helvetica', 'B', 8)
        self.set_fill_color(30, 30, 50)
        self.set_text_color(255, 255, 255)
        for h, w in zip(headers, col_widths):
            self.cell(w, 6, h, fill=True, align='C')
        self.ln()
        self.set_font('Helvetica', '', 8)
        for i, row in enumerate(rows):
            self.set_fill_color(248, 249, 252) if i % 2 == 0 else self.set_fill_color(255, 255, 255)
            self.set_text_color(0, 0, 0)
            for val, w, align in zip(row[:-1], col_widths[:-1], ['L'] + ['C'] * (len(col_widths) - 2)):
                self.cell(w, 5.5, str(val), fill=True, align=align)
            # ultima columna puede ser nota en color
            color = row[-1][1] if isinstance(row[-1], tuple) else (0, 0, 0)
            text  = row[-1][0] if isinstance(row[-1], tuple) else str(row[-1])
            self.set_text_color(*color)
            self.cell(col_widths[-1], 5.5, text, fill=True, align='C')
            self.set_text_color(0, 0, 0)
            self.ln()
        self.ln(3)


def build_pdf() -> bytes:
    pdf = PDF()
    pdf.add_page()
    pdf.set_left_margin(10)
    pdf.set_right_margin(10)

    # ?? RESUMEN EJECUTIVO ????????????????????????????????????????????????????
    pdf.section_title('RESUMEN EJECUTIVO - Estado actual (Abril 2026)')
    pdf.set_font('Helvetica', '', 8.5)
    pdf.set_text_color(40, 40, 40)
    pdf.multi_cell(0, 5,
        'Sistema de trading algoritmico en paper mode con 4 agentes activos. '
        'El Trading Agent (Trend Momentum + Grid Bot) es el motor principal, con resultados '
        'positivos y crecientes desde SESSION_007. SESSION_008 (activa, 10 dias) es la mejor '
        'del historial con +12.34% y 227 operaciones cerradas.',
        align='J')
    pdf.ln(3)

    # ?? TRADING AGENT - SESSION_008 ??????????????????????????????????????????
    pdf.section_title('AGENTE 1: Trading Agent - Trend Momentum + Grid Bot  [ESTRELLA]', 0, 100, 60)
    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_text_color(0, 130, 80)
    pdf.cell(0, 5, '  SESSION_008 (ACTIVA desde Abr 12) - Mejor sesion del historial', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    pdf.kpi_row([
        ('Balance inicial', f'${S8["balance_inicial"]:,.2f}', (80, 80, 80)),
        ('Balance actual',  f'${S8["balance_actual"]:,.2f}', (0, 140, 80)),
        ('Retorno (10 dias)', f'+{S8["retorno"]:.2f}%',     (0, 150, 60)),
        ('PnL neto',         f'+${S8["pnl"]:,.2f}',          (0, 140, 80)),
        ('Trades',           str(S8["trades"]),               (60, 60, 60)),
        ('Win Rate',         f'{S8["wr"]:.1f}%',              (0, 120, 200)),
    ])

    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(60, 60, 60)
    pdf.cell(0, 5, '  Desglose por estrategia en SESSION_008:', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    pdf.two_col_table(
        ['Estrategia', 'Trades', 'Win Rate', 'PnL', 'Avg Win', 'Avg Loss', 'Estado'],
        [
            ('TREND_MOMENTUM', 71,  f'{S8["trend_wr"]:.1f}%', f'+${S8["trend_pnl"]:,.2f}', '$26.54', '-$18.68', ('ACTIVA', (0,140,80))),
            ('GRID_BOT',       156, f'{S8["grid_wr"]:.1f}%',  f'+${S8["grid_pnl"]:,.2f}',  '$34.08', '-$30.31', ('ACTIVA', (0,140,80))),
        ],
        [35, 18, 22, 26, 22, 22, 25]
    )

    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_text_color(0, 80, 160)
    pdf.cell(0, 5, '  Historial de sesiones:', new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(1)
    pdf.set_font('Helvetica', '', 7.5)
    session_rows = []
    for name, status, trades, wins, ret, dd, pf in SESSIONS:
        wr = f'{wins/trades*100:.0f}%' if trades > 0 else '-'
        dd_str = f'{dd:.2f}%' if isinstance(dd, float) else str(dd)
        ret_str = f'{ret:+.2f}%' if isinstance(ret, float) else str(ret)
        if status == 'ACTIVE':
            s_color = (0, 140, 80)
        elif status in ('FAILED',):
            s_color = (180, 0, 0)
        else:
            s_color = (80, 80, 80)
        session_rows.append((name, trades, wr, ret_str, dd_str, f'{pf:.2f}', (status, s_color)))
    pdf.two_col_table(
        ['Sesion', 'Trades', 'WR', 'Retorno', 'Max DD', 'PF', 'Estado'],
        session_rows,
        [35, 16, 16, 22, 18, 16, 27]
    )

    # ?? OPTIONS ??????????????????????????????????????????????????????????????
    pdf.section_title('AGENTE 2: Options - Theta Farming (Deribit)  [PROMETEDOR]', 0, 60, 130)
    pdf.kpi_row([
        ('Sesion',         'OPTIONS_001',             (60, 60, 60)),
        ('Posiciones',     '2 (1 cerrada, 1 abierta)', (60, 60, 60)),
        ('PnL realizado',  f'+${OPTIONS["pnl"]:,.2f}', (0, 140, 80)),
        ('Peak balance',   f'${OPTIONS["peak"]:,.2f}', (0, 120, 200)),
        ('Ret. peak',      f'+{OPTIONS["retorno_peak"]:.1f}%', (0, 140, 80)),
        ('IV Rank filter', '? 20% (252d)',             (80, 80, 80)),
    ])
    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(60, 60, 60)
    pdf.multi_cell(0, 4.5,
        'Estrategia conservadora: venta de PUTs OTM semanales en BTC/USD. '
        'Solo opera con IV Rank alto (percentil anual). Stop 2x prima, profit lock 80%. '
        'Primera posicion (BTC-24APR26-66000-P) cerro capturando 97% de la prima cobrada. '
        'Mejoras recientes: IV Rank 252d (estandar anual), ordenar candidatos por prima/margen, '
        'mark price en paper mode.',
        align='J')
    pdf.ln(3)

    # ?? POLYMARKET ???????????????????????????????????????????????????????????
    pdf.section_title('AGENTE 3: Polymarket SIGNAL_BASED  [CON PRECAUCION - 2 meses de prueba]', 120, 80, 0)
    pdf.kpi_row([
        ('Trades',      str(POLY["trades"]),         (60, 60, 60)),
        ('Win Rate',    f'{POLY["wr"]:.1f}%',        (0, 120, 200)),
        ('PnL actual',  f'-${abs(POLY["pnl"])}',     (180, 0, 0)),
        ('Min edge',    f'{POLY["edge_min"]}%',       (60, 60, 60)),
        ('Max posicion', f'{POLY["max_pos"]}%',       (60, 60, 60)),
        ('PREDICTION_LLM', 'DESACTIVADO',             (150, 0, 0)),
    ])
    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(60, 60, 60)
    pdf.multi_cell(0, 4.5,
        'WR 60.5% es positivo, pero el PnL es -$70 porque las perdidas son mayores que los '
        'premios ganados (R:R desequilibrado). PREDICTION_LLM eliminado (43 trades, 0 wins, -$582). '
        'Ajustes recientes: edge minimo 15% (antes 10%), posicion maxima 2.5% (antes 4%). '
        'Recomendacion: incluir en live solo si completa 2 meses consecutivos sin drawdown neto.',
        align='J')
    pdf.ln(3)

    # ?? BTC DIRECTION ????????????????????????????????????????????????????????
    pdf.section_title('AGENTE 4: BTC Direction - Polymarket Fast Markets  [BAJO VIGILANCIA]', 100, 30, 30)
    pdf.kpi_row([
        ('Trades (reales)', str(BTC_DIR["trades"]),      (60, 60, 60)),
        ('Win Rate',        f'{BTC_DIR["wr"]:.1f}%',     (180, 80, 0)),
        ('PnL real',        f'-${abs(BTC_DIR["pnl"])}',  (180, 0, 0)),
        ('Fix aplicado',    'Settlement OK',              (0, 120, 80)),
        ('Timeframes',      '5m / 15m / 1h / 4h',        (60, 60, 60)),
        ('Estado',          'Vigilancia 2-3 semanas',     (150, 100, 0)),
    ])
    pdf.set_font('Helvetica', '', 8)
    pdf.set_text_color(60, 60, 60)
    pdf.multi_cell(0, 4.5,
        'Bug de settlement corregido (endpoint /events?slug= en lugar de /markets?conditionId=). '
        '105 trades backfilled con outcomes reales. WR 27.6% indica que las senales de momentum '
        'BTC en 5m/15m no tienen edge estadistico suficiente frente a los precios implicitos '
        'de Polymarket. Decision pendiente: si WR no supera 40% en 3 semanas, pausar el agente.',
        align='J')

    # ?? PLAN DE FUNDING ??????????????????????????????????????????????????????
    pdf.add_page()
    pdf.section_title('PLAN DE FUNDING - Jul 2026 -> Jun 2027', 10, 30, 80)

    pdf.set_font('Helvetica', '', 8.5)
    pdf.set_text_color(40, 40, 40)
    pdf.multi_cell(0, 5,
        'Capital minimo inicial: $300 USD. Aportaciones mensuales de $100 a partir de Jul 2026. '
        'Retorno mensual estimado conservador: 2% (basado en SESSION_008 real: +12.34% en 10 dias). '
        'Objetivo: $1,500 para mediados de 2027, punto en que el bot cubre sus propios costes operativos.',
        align='J')
    pdf.ln(3)

    # Tabla funding
    saldo = 0
    rows = []
    for mes, ano, aporte, saldo_acum, ret_est, nota in FUNDING_PLAN:
        saldo = saldo_acum
        ret_real = saldo * 0.02  # 2% mensual
        nota_color = (0, 100, 180) if nota else (120, 120, 120)
        rows.append((
            f'{mes} {ano}',
            f'+${aporte}',
            f'${saldo_acum}',
            f'~${ret_est}/mes',
            (nota if nota else '-', (nota_color))
        ))

    pdf.two_col_table(
        ['Mes', 'Aporte', 'Saldo acum.', 'Retorno est.', 'Hito / Nota'],
        rows,
        [22, 20, 26, 28, 94]
    )

    # Hitos clave
    pdf.section_title('HITOS CLAVE', 30, 30, 80)
    hitos = [
        ('$300 (Jul 2026)',  'Activar Trading Agent en LIVE - solo TREND_MOMENTUM + GRID_BOT'),
        ('$500 (Sep 2026)',  'Grid Bot comienza a cubrir comisiones por si solo'),
        ('$700 (Oct 2026)',  'Evaluar Polymarket SIGNAL_BASED si 2 meses seguidos positivos'),
        ('$1,000 (Feb 2027)','El bot cubre el costo del VPS (~$20/mes). Operacion autosostenible'),
        ('$1,200 (Mar 2027)','Evaluar Options Theta en live si >3 meses positivo en paper'),
        ('$1,500 (Jun 2027)','Capital objetivo - reinversion total, sin retiros hasta nueva etapa'),
    ]
    pdf.set_font('Helvetica', '', 8.5)
    pdf.set_text_color(40, 40, 40)
    for monto, desc in hitos:
        pdf.set_font('Helvetica', 'B', 8.5)
        pdf.set_text_color(0, 80, 180)
        pdf.cell(45, 6, f'  {monto}')
        pdf.set_font('Helvetica', '', 8.5)
        pdf.set_text_color(40, 40, 40)
        pdf.cell(0, 6, desc, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.ln(4)

    # Advertencia riesgo
    pdf.section_title('RIESGO OPERATIVO - VPS', 180, 30, 30)
    pdf.set_font('Helvetica', '', 8.5)
    pdf.set_text_color(40, 40, 40)
    pdf.multi_cell(0, 5,
        'El riesgo principal al pasar a LIVE no es el capital sino la disponibilidad del VPS. '
        'Si el servidor se cae con posiciones abiertas, el agente no puede ejecutar stop loss. '
        'Accion recomendada antes de ir a live: implementar watchdog externo que cierre posiciones '
        'automaticamente si el agente deja de publicar heartbeat por mas de 10 minutos. '
        'Esto es prioritario con cualquier monto que se deposite.',
        align='J')

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()


def send_pdf_telegram(pdf_bytes: bytes):
    """Envia el PDF como documento por Telegram."""
    filename = f'ArthasBot_FundingPlan_{datetime.now().strftime("%Y%m%d")}.pdf'
    caption = (
        '<b>? Plan de Funding - Arthas Trading System</b>\n\n'
        '<b>SESSION_008 (activa):</b> +12.34% en 10 dias | 227 trades | WR 55.1%\n'
        '<b>Capital minimo live:</b> $300 USD (Jul 2026)\n'
        '<b>Objetivo 2027:</b> $1,500 autosostenible\n\n'
        '4 agentes analizados: Trading ? | Options ? | Polymarket ?? | BTC Direction ?'
    )
    resp = requests.post(
        f'https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendDocument',
        data={'chat_id': TELEGRAM_CHAT, 'caption': caption, 'parse_mode': 'HTML'},
        files={'document': (filename, pdf_bytes, 'application/pdf')},
        timeout=30,
    )
    if resp.status_code == 200:
        print(f'PDF enviado: {filename}')
    else:
        print(f'Error Telegram: {resp.status_code} - {resp.text[:200]}')


if __name__ == '__main__':
    print('Generando PDF...')
    pdf_bytes = build_pdf()
    print(f'PDF generado: {len(pdf_bytes):,} bytes')
    print('Enviando por Telegram...')
    send_pdf_telegram(pdf_bytes)
