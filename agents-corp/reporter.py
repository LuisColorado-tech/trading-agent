"""
Agents Corp — Unified Reporting & Command System

Runs 24/7. Each business unit CEO reports on schedule via Telegram.
President can reply to any CEO message to give instructions.
The dispatcher processes replies and routes to the correct agent.

Report Schedule:
  VP Development:  every 6h (06:00, 12:00, 18:00, 00:00 UTC)
  CEO DeepAPI:     every 12h (09:00, 21:00 UTC)
  CEO ViralBot:    every 24h (08:00 UTC)
  CEO PriceGuard:  every 12h (10:00, 22:00 UTC)
  CEO LeadGen:     every 24h (07:00 UTC)
  VP Finance:      every 24h (00:00 UTC)
  VP Marketing:    every 48h (Mon/Thu 12:00 UTC)
  Funding Agent:   every 6h (already running via funding_report.py)

Message format:
  [CEO-DeepAPI] Daily Report | 2026-07-09
  Users: 23 (+5) | MRR: $0 | Costs: $2.30
  Status: All systems operational
  Next: Payment integration
  --reply-to ceo-deepapi
"""
import os
import sys
import json
import time
import urllib.request
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/opt/agents-corp')
sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

if not TOKEN or not CHAT_ID:
    print('Missing Telegram config')
    sys.exit(1)

# ─── Telegram helpers ──────────────────────────────────────────────

def send_telegram(text: str, reply_to_msg_id: int = None):
    payload = {'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML'}
    if reply_to_msg_id:
        payload['reply_parameters'] = json.dumps({'message_id': reply_to_msg_id})
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f'https://api.telegram.org/bot{TOKEN}/sendMessage',
        data=data, headers={'Content-Type': 'application/json'})
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        return json.loads(resp.read())
    except Exception as e:
        print(f'Telegram error: {e}')
        return None

def get_updates(offset: int = 0):
    url = f'https://api.telegram.org/bot{TOKEN}/getUpdates?offset={offset}&timeout=30'
    try:
        resp = urllib.request.urlopen(url, timeout=35)
        return json.loads(resp.read())
    except:
        return None

# ─── Report generators ────────────────────────────────────────────

def report_header(role: str, emoji: str, period: str) -> str:
    now = datetime.now(timezone.utc)
    return f'<b>{emoji} [{role}]</b> {period} Report | {now.strftime("%Y-%m-%d %H:%M UTC")}\n'

def get_db_stats(query: str):
    import psycopg2
    try:
        conn = psycopg2.connect(
            host=os.getenv('POSTGRES_HOST', 'localhost'),
            port=int(os.getenv('POSTGRES_PORT', '5432')),
            user=os.getenv('POSTGRES_USER'),
            password=os.getenv('POSTGRES_PASSWORD'),
            dbname=os.getenv('POSTGRES_DB', 'trading_agent'),
            connect_timeout=3)
        cur = conn.cursor()
        cur.execute(query)
        result = cur.fetchone()
        cur.close(); conn.close()
        return result
    except:
        return None

def check_port(port: int) -> str:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(('localhost', port))
        s.close()
        return '🟢'
    except:
        return '🔴'

def check_service(name: str) -> str:
    import subprocess
    r = subprocess.run(['systemctl', 'is-active', name], capture_output=True, text=True)
    return '🟢' if r.stdout.strip() == 'active' else '🔴'

# ─── CEO Reports ──────────────────────────────────────────────────

def report_vp_development():
    msg = report_header('VP Dev', '🔧', '6h')
    msg += f'{check_service("funding-agent")} funding-agent '
    msg += f'{check_service("nginx")} nginx '
    msg += f'{check_service("postgresql@16-main")} postgres '
    msg += f'{check_service("redis-server")} redis\n'
    msg += f'{check_port(8000)} API:8000 '
    msg += f'{check_port(9001)} DeepAPI:9001 '
    msg += f'{check_port(9002)} PriceGuard:9002\n'
    
    # Disk and memory
    import subprocess
    r = subprocess.run(['df', '-h', '/'], capture_output=True, text=True)
    disk = r.stdout.split('\n')[1].split()[4] if len(r.stdout.split('\n')) > 1 else '?'
    r2 = subprocess.run(['free', '-h'], capture_output=True, text=True)
    mem = r2.stdout.split('\n')[1].split()[3] if len(r2.stdout.split('\n')) > 1 else '?'
    msg += f'Disk: {disk} | Mem free: {mem}\n'
    
    # Git status
    r3 = subprocess.run(['git', '-C', '/opt/trading', 'log', '--oneline', '-3'], capture_output=True, text=True)
    msg += f'<i>Last commits:</i>\n<code>{r3.stdout.strip()[:200]}</code>\n'
    msg += '\n<i>--reply-to vp-development</i>'
    send_telegram(msg)

def report_ceo_deepapi():
    msg = report_header('CEO DeepAPI', '🤖', '12h')
    # Get stats from DB
    stats = get_db_stats("SELECT COUNT(*) FROM deepapi_users")
    users = int(stats[0]) if stats else 0
    msg += f'Users: {users} | API status: {check_port(9001)}\n'
    msg += f'Provider: DeepSeek | Model: deepseek-chat\n'
    msg += f'<i>Next: Payment integration (MercadoPago)</i>\n'
    msg += '\n<i>--reply-to ceo-deepapi</i>'
    send_telegram(msg)

def report_ceo_priceguard():
    msg = report_header('CEO PriceGuard', '📊', '12h')
    msg += f'Scrapers: {check_port(9002)}\n'
    # Get monitored product count
    stats = get_db_stats("SELECT COUNT(*) FROM priceguard_products")
    products = int(stats[0]) if stats else 0
    msg += f'Products monitored: {products}\n'
    msg += f'<i>Target: MercadoLibre AR + Amazon US</i>\n'
    msg += f'<i>Next: Alert system + pricing tiers</i>\n'
    msg += '\n<i>--reply-to ceo-priceguard</i>'
    send_telegram(msg)

def report_ceo_viralbot():
    msg = report_header('CEO ViralBot', '📱', '24h')
    msg += 'Account: @[TBD] | Platform: Twitter/X\n'
    msg += 'Posts today: 0 | Engagement: -\n'
    msg += 'Content generated: 0 threads, 0 scripts\n'
    msg += f'<i>Next: Twitter API integration</i>\n'
    msg += '\n<i>--reply-to ceo-viralbot</i>'
    send_telegram(msg)

def report_ceo_leadgen():
    msg = report_header('CEO LeadGen', '🎯', '24h')
    msg += 'Leads generated: 0 | Sold: 0\n'
    msg += f'<i>Next: Google Maps scraper + email finder</i>\n'
    msg += '\n<i>--reply-to ceo-leadgen</i>'
    send_telegram(msg)

def report_vp_finance():
    msg = report_header('VP Finance', '💰', '24h')
    # Get funding agent earnings
    stats = get_db_stats("SELECT COALESCE(SUM(funding_earned_usd),0) FROM funding_events WHERE timestamp > NOW() - INTERVAL '24 hours'")
    funding = float(stats[0]) if stats else 0
    
    # Get portfolio balance
    stats2 = get_db_stats("SELECT total_balance, available_cash FROM portfolio_v2 ORDER BY timestamp DESC LIMIT 1")
    bal, cash = (float(stats2[0]), float(stats2[1])) if stats2 else (5500, 3500)
    
    msg += f'Funding earned 24h: ${funding:.4f}\n'
    msg += f'Crypto balance: ${bal:,.2f} | Available: ${cash:,.2f}\n'
    msg += f'DeepAPI MRR: $0 | PriceGuard MRR: $0\n'
    msg += f'<b>Total MRR: ${funding*30:.2f}/mo projected</b>\n'
    msg += '\n<i>--reply-to vp-finance</i>'
    send_telegram(msg)

def report_vp_marketing():
    msg = report_header('VP Marketing', '📣', '48h')
    msg += 'Channels status:\n'
    msg += '  GitHub: pending repos\n'
    msg += '  Twitter: pending account\n'
    msg += '  YouTube: pending channel\n'
    msg += '  Communities: 0 groups joined\n'
    msg += '\n<i>--reply-to vp-marketing</i>'
    send_telegram(msg)

# ─── Command Dispatcher ────────────────────────────────────────────

REPORT_SCHEDULE = {
    (0, 0): report_vp_finance,
    (6, 0): report_vp_development,
    (7, 0): report_ceo_leadgen,
    (8, 0): report_ceo_viralbot,
    (9, 0): report_ceo_deepapi,
    (10, 0): report_ceo_priceguard,
    (12, 0): report_vp_development,
    (18, 0): report_vp_development,
    (21, 0): report_ceo_deepapi,
    (22, 0): report_ceo_priceguard,
}

# 48h marketing reports on Monday/Thursday at 12:00
MARKETING_DAYS = {0, 3}  # Monday=0, Thursday=3

def main():
    print(f'Agents Corp Reporter started — {datetime.now(timezone.utc)}')
    last_offset = 0
    last_marketing = None

    while True:
        try:
            now = datetime.now(timezone.utc)
            hour_key = (now.hour, 0)  # round to hour

            # Check if any report is due this hour
            if hour_key in REPORT_SCHEDULE:
                fn = REPORT_SCHEDULE[hour_key]
                fn()
                print(f'  Report sent: {fn.__name__}')

            # Marketing every Monday and Thursday
            if now.hour == 12 and now.weekday() in MARKETING_DAYS:
                today = now.date()
                if last_marketing != today:
                    report_vp_marketing()
                    last_marketing = today
                    print('  Report sent: VP Marketing')

            # Check for President replies (every 60 seconds)
            try:
                updates = get_updates(last_offset + 1)
                if updates and updates.get('ok') and updates.get('result'):
                    for update in updates['result']:
                        last_offset = max(last_offset, update['update_id'])
                        msg = update.get('message', {})
                        reply_to = msg.get('reply_to_message')
                        text = msg.get('text', '')
                        
                        if reply_to and text:
                            reply_text = reply_to.get('text', '')
                            # Extract agent from the original message
                            for agent_id in ['vp-development', 'ceo-deepapi', 'ceo-priceguard',
                                           'ceo-viralbot', 'ceo-leadgen', 'vp-finance', 'vp-marketing']:
                                if f'--reply-to {agent_id}' in reply_text:
                                    # Acknowledge the President's message
                                    ack = f'✅ <b>Message received for [{agent_id}]</b>\n'
                                    ack += f'<i>"{text[:100]}{"..." if len(text)>100 else ""}"</i>\n'
                                    ack += 'Processing instruction...'
                                    send_telegram(ack, reply_to_msg_id=msg['message_id'])
                                    
                                    # Log for later processing
                                    with open(f'/opt/agents-corp/inbox/{agent_id}.log', 'a') as f:
                                        f.write(f'{now.isoformat()}|{text}\n')
                                    break
            except Exception as e:
                pass  # Telegram polling can fail, retry next cycle

            time.sleep(60)  # Check every minute

        except KeyboardInterrupt:
            print('Stopped')
            break
        except Exception as e:
            print(f'Error: {e}')
            time.sleep(60)


if __name__ == '__main__':
    import os
    os.makedirs('/opt/agents-corp/inbox', exist_ok=True)
    main()
