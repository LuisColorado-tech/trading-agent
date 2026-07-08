"""
Blanca v3 — Presidential AI Assistant with Telegram chat control.
- Responds to President's messages in real-time
- 2 daily briefings at 08:00 and 20:00 UTC
- Only escalates critical issues (services down >1h)
- CEOs report to Blanca, not to President
"""
import os, sys, json, time, socket, subprocess
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/opt/trading/agents-corp')
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

def send_msg(text: str, chat: str = None, reply_to: int = None):
    if not TOKEN: return
    target = chat or CHAT_ID
    payload = {'chat_id': target, 'text': text, 'parse_mode': 'HTML'}
    if reply_to:
        payload['reply_parameters'] = json.dumps({'message_id': reply_to})
    try:
        urllib.request.urlopen(urllib.request.Request(
            f'https://api.telegram.org/bot{TOKEN}/sendMessage',
            data=json.dumps(payload).encode(),
            headers={'Content-Type': 'application/json'}), timeout=10)
    except Exception as e:
        print(f'Telegram error: {e}')

def poll_updates(offset: int = 0):
    try:
        r = urllib.request.urlopen(
            f'https://api.telegram.org/bot{TOKEN}/getUpdates?offset={offset}&timeout=10', timeout=15)
        return json.loads(r.read())
    except: return None

def log(msg): print(f'{datetime.now(timezone.utc).strftime("%H:%M:%S")} | 🤍 | {msg}')

def check_port(port):
    if not port: return True
    try: s=socket.socket(); s.settimeout(3); s.connect(('localhost',port)); s.close(); return True
    except: return False

def check_service(name):
    r = subprocess.run(['systemctl','is-active',name], capture_output=True, text=True)
    return r.stdout.strip() == 'active'

SERVICES = {
    'deepapi':    {'port':9001, 'svc':'ceo-deepapi',    'name':'🤖 DeepAPI'},
    'priceguard': {'port':9002, 'svc':'ceo-priceguard', 'name':'📊 PriceGuard'},
    'viralbot':   {'port':None, 'svc':'ceo-viralbot',   'name':'📱 ViralBot'},
    'leadgen':    {'port':9003, 'svc':'ceo-leadgen',    'name':'🎯 LeadGen'},
    'funding':    {'port':None, 'svc':'funding-agent',   'name':'💹 Funding'},
}

class Blanca:
    def __init__(self):
        self.cycles = 0
        self.last_briefing = None
        self.down_since = {}
        self.offset = 0
        r = db("SELECT value FROM blanca_memory WHERE category='state' AND key='tg_offset'", fetch=True)
        if r:
            try:
                val = r[0][0]
                if isinstance(val, dict): val = json.dumps(val)
                if isinstance(val, str): self.offset = int(json.loads(val).get('o', 0))
            except: pass

    def run_cycle(self):
        self.cycles += 1
        self._poll_telegram()
        self._monitor_services()
        self._check_briefing_time()
        self._save_state()

    def _poll_telegram(self):
        updates = poll_updates(self.offset + 1)
        if not updates or not updates.get('ok'): return
        for u in updates.get('result', []):
            self.offset = max(self.offset, u['update_id'])
            msg = u.get('message', {}); text = msg.get('text', '').strip()
            chat_id = str(msg.get('chat', {}).get('id', ''))
            msg_id = msg.get('message_id')
            if not text: continue
            log(f'MSG [{chat_id}]: {text[:80]}')
            self._respond(text, chat_id, msg_id)

        # Save offset
        db("INSERT INTO blanca_memory (category,key,value,importance) VALUES ('state','tg_offset',%s,'routine') ON CONFLICT (category,key) DO UPDATE SET value=%s,updated_at=NOW()",
           (json.dumps({'o': self.offset}),)*2)

    def _respond(self, text, chat_id, msg_id):
        t = text.lower()

        # ── Quick commands ──
        if any(w in t for w in ['hola','hello','buenas']):
            send_msg('🤍 Buenos días, Presidente. 5 servicios monitoreados. Escriba <i>ayuda</i> para ver comandos.', chat_id, msg_id)
            return

        if 'status' in t or 'estado' in t or 'cómo va' in t:
            ok = sum(1 for b in SERVICES.values() if check_service(b['svc']))
            wo = db("SELECT COUNT(*) FROM work_orders WHERE status='open'", fetch=True)[0][0]
            m = f'<b>🤍 Status</b>\n▸ Servicios: {ok}/5 operativos\n▸ Work orders abiertas: {wo}\n'
            for bid, info in SERVICES.items():
                svc = check_service(info['svc'])
                m += f'{"🟢" if svc else "🔴"} {info["name"]}\n'
            send_msg(m, chat_id, msg_id)
            return

        if 'ceo' in t:
            reps = db("SELECT business_id, summary, issues_found, issues_resolved, created_at FROM ceo_reports ORDER BY created_at DESC LIMIT 5", fetch=True)
            if reps:
                m = '<b>📋 Últimos reportes CEO</b>\n'
                for r in reps:
                    status = '⚠️' if r[2] > r[3] else '✅'
                    m += f'{status} <b>{r[0]}</b>: {r[1][:90]}\n'
                send_msg(m, chat_id, msg_id)
            else:
                send_msg('🤍 Sin reportes recientes de CEOs. Todo tranquilo.', chat_id, msg_id)
            return

        if 'work order' in t or 'orden' in t or 'wo' in t:
            wo = db("SELECT id, business_id, priority, title, created_at FROM work_orders WHERE status='open' ORDER BY CASE priority WHEN 'critical' THEN 1 WHEN 'high' THEN 2 ELSE 3 END, created_at LIMIT 8", fetch=True)
            if wo:
                m = '<b>🔧 Work Orders pendientes</b>\n'
                for w in wo:
                    em = {'critical':'🚨','high':'⚠️'}.get(w[2],'📋')
                    ago = datetime.now(timezone.utc) - w[4]
                    hrs = ago.total_seconds() / 3600
                    m += f'{em} #{w[0]} [{w[1]}] {w[3][:65]} — <i>{hrs:.1f}h</i>\n'
                send_msg(m, chat_id, msg_id)
            else:
                send_msg('🤍 Sin work orders. Los CEOs tienen todo bajo control.', chat_id, msg_id)
            return

        if 'funding' in t or 'crypto' in t:
            earned = db("SELECT COALESCE(SUM(funding_earned_usd),0) FROM funding_events WHERE timestamp > NOW() - INTERVAL '24 hours'", fetch=True)[0][0]
            bal = db("SELECT total_balance, available_cash FROM portfolio_v2 ORDER BY timestamp DESC LIMIT 1", fetch=True)
            m = f'<b>💹 Funding Report</b>\n▸ 24h ganado: ${float(earned):.4f}\n'
            if bal:
                m += f'▸ Balance: ${float(bal[0][0]):,.2f}\n▸ Disponible: ${float(bal[0][1]):,.2f}'
            send_msg(m, chat_id, msg_id)
            return

        if 'ayuda' in t or 'help' in t or 'comando' in t:
            send_msg('<b>🤍 Comandos disponibles:</b>\n• <i>status</i> — estado de todos los servicios\n• <i>ceos</i> — últimos reportes de CEOs\n• <i>work orders</i> — tareas pendientes\n• <i>funding</i> — estado del crypto\n• <i>briefing</i> — briefing completo ahora\n• <i>di [mensaje] para [CEO]</i> — enviar instrucción a un CEO', chat_id, msg_id)
            return

        if 'briefing' in t:
            self._send_briefing('ondemand')
            send_msg('🤍 Briefing enviado al chat principal.', chat_id, msg_id)
            return

        # ── Forward to CEO ──
        ceo_map = {'deepapi':'deepapi','priceguard':'priceguard','viralbot':'viralbot','leadgen':'leadgen',
                   'deep':'deepapi','price':'priceguard','leads':'leadgen','viral':'viralbot'}
        for keyword, biz in ceo_map.items():
            if keyword in t:
                # Extract the message after the keyword
                db("INSERT INTO blanca_inbox (from_agent, subject, body, urgency) VALUES (%s,%s,%s,%s)",
                   ('President', f'Instruction for {biz}', text[:500], 'high'))
                db("INSERT INTO ceo_reports (business_id, report_type, summary, issues_found) VALUES (%s,%s,%s,0)",
                   (biz, 'presidential_directive', f'President: {text[:200]}'))
                send_msg(f'🤍 Instrucción enviada a <b>{biz.upper()}</b>. El CEO la procesará en el próximo ciclo.', chat_id, msg_id)
                return

        # ── Ask LLM for complex questions ──
        if len(t) > 10 and '?' in t or '?' in text:
            send_msg('🤍 Consultando al equipo...', chat_id, msg_id)
            answer = self._ask_llm(text)
            send_msg(f'🤍 <b>Respuesta:</b>\n{answer[:800]}', chat_id, msg_id)
            return

        if 'gracias' in t:
            send_msg('🤍 A sus órdenes, Presidente.', chat_id, msg_id)
            return

        # ── Default ──
        db("INSERT INTO blanca_inbox (from_agent, subject, body, urgency, status) VALUES (%s,%s,%s,%s,%s)",
           ('President','Message', text[:500], 'routine', 'acknowledged'))
        send_msg('🤍 Recibido. Si necesita algo específico, escriba <i>ayuda</i>.', chat_id, msg_id)

    def _ask_llm(self, question):
        if not DS_KEY: return 'Lo siento, el motor de IA no está disponible.'
        try:
            context = f"You are Blanca, the Presidential Assistant of Agents Corp. Answer concisely in Spanish. Context: 5 business units (DeepAPI, PriceGuard, ViralBot, LeadGen, Funding). The President asks:"
            payload = json.dumps({
                "model":"deepseek-chat","messages":[
                    {"role":"system","content":context},
                    {"role":"user","content":question}],
                "max_tokens":300,"temperature":0.5}).encode()
            r = urllib.request.Request("https://api.deepseek.com/v1/chat/completions", data=payload,
                headers={"Content-Type":"application/json","Authorization":f"Bearer {DS_KEY}"})
            resp = urllib.request.urlopen(r, timeout=30)
            return json.loads(resp.read())["choices"][0]["message"]["content"]
        except Exception as e:
            return f'Error consultando IA: {str(e)[:100]}'

    def _monitor_services(self):
        for bid, info in SERVICES.items():
            ok = check_service(info['svc'])
            if not ok:
                now = datetime.now(timezone.utc)
                if bid not in self.down_since: self.down_since[bid] = now
                hrs = (now - self.down_since[bid]).total_seconds() / 3600
                if hrs > 1:
                    send_msg(f'<b>🚨 {info["name"]} caído {hrs:.1f}h</b>')
                    self.down_since[bid] = now  # reset cooldown
            else:
                self.down_since.pop(bid, None)

    def _check_briefing_time(self):
        now = datetime.now(timezone.utc)
        if now.hour in (8, 20) and now.minute < 5:
            today = now.date()
            if self.last_briefing != (today, now.hour):
                self._send_briefing(now.hour)
                self.last_briefing = (today, now.hour)

    def _send_briefing(self, hour, immediate=False):
        period = 'AM' if str(hour) in ('8', '08') else 'PM'
        ok = sum(1 for b in SERVICES.values() if check_service(b['svc']))
        down = [info['name'] for bid, info in SERVICES.items() if not check_service(info['svc'])]
        wo = db("SELECT COUNT(*) FROM work_orders WHERE status='open'", fetch=True)[0][0]
        resolved = db("SELECT COUNT(*) FROM work_orders WHERE resolved_at > NOW() - INTERVAL '24 hours'", fetch=True)[0][0]
        complaints = db("SELECT COUNT(*) FROM ceo_reports WHERE created_at > NOW() - INTERVAL '24 hours' AND issues_found > issues_resolved", fetch=True)[0][0]

        m = f'<b>🤍 Blanca — Briefing {period}</b>\n{datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}\n\n'
        m += f'Servicios: {ok}/5\n'
        if down: m += f'⚠️ Caídos: {", ".join(down)}\n'
        m += f'WO abiertas: {wo} | Resueltas 24h: {resolved}\n'
        m += f'Quejas: {complaints}\n'

        reps = db("SELECT business_id, summary FROM ceo_reports WHERE created_at > NOW() - INTERVAL '12 hours' ORDER BY created_at DESC LIMIT 3", fetch=True)
        if reps:
            m += '\n<b>CEO reports:</b>\n'
            for r in reps: m += f'{"⚠️" if "ISSUES" in str(r[1]) else "✅"} <b>{r[0]}</b>: {r[1][:70]}\n'

        db("INSERT INTO blanca_briefings (briefing_type, summary, businesses_reported, services_down) VALUES (%s,%s,%s,%s)",
           (f'daily_{period.lower()}', m[:500], ok, down))
        send_msg(m)
        log(f'Briefing {period} sent')

    def _save_state(self):
        db("INSERT INTO blanca_memory (category,key,value,importance) VALUES ('state','runtime',%s,'routine') ON CONFLICT (category,key) DO UPDATE SET value=%s,updated_at=NOW()",
           (json.dumps({'cycles': self.cycles}),)*2)

    def main_loop(self):
        log('Blanca v3 online — Telegram active, 2 daily briefings')
        while True:
            try:
                self.run_cycle()
                time.sleep(5)  # Poll every 5 seconds for responsiveness
            except KeyboardInterrupt: log('Shutdown'); break
            except Exception as e: log(f'Error: {e}'); time.sleep(30)

if __name__ == '__main__':
    Blanca().main_loop()
