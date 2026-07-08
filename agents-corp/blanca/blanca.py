"""
Blanca v2 — Presidential AI Assistant
- 2 daily briefings: 08:00 and 20:00 UTC
- Only escalates: services down >1h, customer complaints, critical errors
- CEOs report to Blanca, not to President
- Controls the Telegram chat
"""
import os, sys, json, time, socket, subprocess
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, '/opt/agents-corp')
sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')
import psycopg2
import urllib.request

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DS_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DB = {
    'host': os.getenv('POSTGRES_HOST'), 'port': int(os.getenv('POSTGRES_PORT', '5432')),
    'user': os.getenv('POSTGRES_USER'), 'password': os.getenv('POSTGRES_PASSWORD'),
    'dbname': os.getenv('POSTGRES_DB'), 'connect_timeout': 5,
}

def db(sql, params=None, fetch=False):
    conn = psycopg2.connect(**DB); cur = conn.cursor()
    cur.execute(sql, params)
    r = cur.fetchall() if fetch else None
    conn.commit(); cur.close(); conn.close()
    return r

def tg(text: str):
    if not TOKEN or not CHAT_ID: return
    payload = json.dumps({'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML'}).encode()
    urllib.request.urlopen(urllib.request.Request(
        f'https://api.telegram.org/bot{TOKEN}/sendMessage',
        data=payload, headers={'Content-Type': 'application/json'}), timeout=10)

def log(msg): print(f'{datetime.now(timezone.utc).strftime("%H:%M:%S")} | 🤍 Blanca | {msg}')

# ─── Service monitoring ────────────────────────────────────────────

SERVICES = {
    'deepapi':    {'port': 9001, 'service': 'operator-deepapi',    'ceo': '🤖 CEO DeepAPI'},
    'priceguard': {'port': 9002, 'service': 'operator-priceguard', 'ceo': '📊 CEO PriceGuard'},
    'viralbot':   {'port': None,  'service': 'operator-viralbot',   'ceo': '📱 CEO ViralBot'},
    'leadgen':    {'port': 9003, 'service': 'operator-leadgen',    'ceo': '🎯 CEO LeadGen'},
    'funding':    {'port': None,  'service': 'funding-agent',       'ceo': '💹 Funding Agent'},
}

def check_port(port):
    if not port: return True
    try:
        s = socket.socket(); s.settimeout(3)
        s.connect(('localhost', port)); s.close(); return True
    except: return False

def check_service(name):
    r = subprocess.run(['systemctl', 'is-active', name], capture_output=True, text=True)
    return r.stdout.strip() == 'active'

# ─── Blanca ────────────────────────────────────────────────────────

class Blanca:
    def __init__(self):
        self.cycles = 0
        self.last_briefing = None
        self.services_down_since = {}
        self.critical_events = []

    def run_cycle(self):
        self.cycles += 1

        # 1. Check all business services
        for bid, info in SERVICES.items():
            port_ok = check_port(info['port'])
            svc_ok = check_service(info['service'])

            if not svc_ok and not port_ok:
                now = datetime.now(timezone.utc)
                if bid not in self.services_down_since:
                    self.services_down_since[bid] = now
                downtime = (now - self.services_down_since[bid]).total_seconds()
                if downtime > 3600:  # >1 hour
                    self._alert_critical(bid, info, downtime)
            else:
                self.services_down_since.pop(bid, None)

        # 2. Check for unresolved work orders >6h
        stale = db("SELECT COUNT(*) FROM work_orders WHERE status='open' AND created_at < NOW() - INTERVAL '6 hours'", fetch=True)
        if stale and stale[0][0] > 3:
            self._alert_critical('dev', {'ceo': '🔧 Development'}, 21600)

        # 3. Briefings at 08:00 and 20:00 UTC
        now = datetime.now(timezone.utc)
        if now.hour in (8, 20) and now.minute < 5:
            today = now.date()
            if self.last_briefing != (today, now.hour):
                self._send_briefing(now.hour)
                self.last_briefing = (today, now.hour)

        # 4. Save state
        db("INSERT INTO blanca_memory (category, key, value, importance) VALUES ('state', 'runtime', %s, 'routine') ON CONFLICT (category, key) DO UPDATE SET value=%s, updated_at=NOW()",
           (json.dumps({'cycles': self.cycles, 'timestamp': now.isoformat()}),) * 2)

    def _alert_critical(self, bid, info, downtime):
        """Only send Telegram for CRITICAL issues."""
        hours = downtime / 3600
        msg = f'<b>🚨 CRÍTICO — {info["ceo"]}</b>\n'
        msg += f'Servicio <b>{info["service"]}</b> caído por <b>{hours:.1f}h</b>\n'
        msg += f'Puerto {info["port"]} no responde\n\n'
        msg += f'<i>— Blanca 🤍 | {datetime.now(timezone.utc).strftime("%H:%M UTC")}</i>'
        tg(msg)
        log(f'CRITICAL: {bid} down {hours:.1f}h')

    def _send_briefing(self, hour):
        """Daily briefing to President. Only important stuff."""
        period = 'AM' if hour == 8 else 'PM'

        # Gather info
        businesses_ok = 0; businesses_down = 0
        down_list = []
        for bid, info in SERVICES.items():
            if check_service(info['service']):
                businesses_ok += 1
            else:
                businesses_down += 1
                down_list.append(info['ceo'])

        # Work orders
        open_wo = db("SELECT COUNT(*) FROM work_orders WHERE status='open'", fetch=True)[0][0]
        resolved_24h = db("SELECT COUNT(*) FROM work_orders WHERE resolved_at > NOW() - INTERVAL '24 hours'", fetch=True)[0][0]

        # Recent CEO reports
        reports = db("SELECT business_id, summary, issues_found, issues_resolved FROM ceo_reports WHERE created_at > NOW() - INTERVAL '12 hours' ORDER BY created_at DESC LIMIT 5", fetch=True)

        # Customer complaints
        complaints = db("SELECT COUNT(*) FROM ceo_reports WHERE created_at > NOW() - INTERVAL '24 hours' AND issues_found > issues_resolved", fetch=True)[0][0]

        msg = f'<b>🤍 Blanca — Briefing {period} | {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}</b>\n\n'
        msg += f'<b>Servicios:</b> {businesses_ok}/{len(SERVICES)} operativos\n'
        if down_list:
            msg += f'<b>⚠️ Caídos:</b> {", ".join(down_list)}\n'
        msg += f'<b>Órdenes de trabajo:</b> {open_wo} abiertas | {resolved_24h} resueltas (24h)\n'
        msg += f'<b>Quejas clientes:</b> {complaints} pendientes\n\n'

        if reports:
            msg += '<b>Últimos reportes CEO:</b>\n'
            for r in reports:
                tag = '⚠️' if r[2] > r[3] else '✅'
                msg += f'{tag} <b>{r[0]}</b>: {r[1][:80]}\n'

        # Store briefing
        db("INSERT INTO blanca_briefings (briefing_type, summary, businesses_reported, services_down) VALUES (%s, %s, %s, %s)",
           (f'daily_{period.lower()}', msg[:500], businesses_ok, down_list))

        tg(msg)
        log(f'Briefing {period} sent: {businesses_ok}/{len(SERVICES)} up, {open_wo} open WOs')

    def main_loop(self):
        log('Blanca v2 online. 2 daily briefings. Critical-only escalation.')
        while True:
            try:
                self.run_cycle()
                time.sleep(60)
            except KeyboardInterrupt:
                log('Shutdown.')
                break
            except Exception as e:
                log(f'Error: {e}')
                time.sleep(60)


if __name__ == '__main__':
    Blanca().main_loop()
