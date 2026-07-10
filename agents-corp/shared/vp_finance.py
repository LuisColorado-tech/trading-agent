"""
VP-Finance Cost Monitor — Real API cost tracking.
Runs every 6h. Reports to Blanca if costs exceed projections.
"""
import os, sys, json, urllib.request
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/opt/trading/agents-corp')
sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')
import psycopg2

DB = {
    'host': os.getenv('POSTGRES_HOST'), 'port': int(os.getenv('POSTGRES_PORT', '5432')),
    'user': os.getenv('POSTGRES_USER'), 'password': os.getenv('POSTGRES_PASSWORD'),
    'dbname': os.getenv('POSTGRES_DB'), 'connect_timeout': 5,
}
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')

def db(sql, params=None, fetch=False):
    conn = psycopg2.connect(**DB); cur = conn.cursor()
    cur.execute(sql, params)
    r = cur.fetchall() if fetch else None
    conn.commit(); cur.close(); conn.close()
    return r

def report_to_blanca(subject, body, urgency='routine'):
    db("INSERT INTO blanca_inbox (from_agent, subject, body, category, urgency) VALUES (%s,%s,%s,%s,%s)",
       ('VP-Finance', subject, body, 'finance', urgency))

DEEPSEEK_COST_PER_1M = 0.14  # $0.14 per million tokens

def get_real_costs():
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)

    # DeepAPI user token usage (24h and 30d)
    row_24h = db("SELECT COALESCE(SUM(tokens_used),0) FROM api_users WHERE created_at > NOW() - INTERVAL '24 hours'", fetch=True)
    row_total = db("SELECT COALESCE(SUM(tokens_used),0) FROM api_users", fetch=True)

    tokens_24h = int(row_24h[0][0]) if row_24h else 0
    tokens_total = int(row_total[0][0]) if row_total else 0

    cost_24h = (tokens_24h / 1_000_000) * DEEPSEEK_COST_PER_1M
    cost_total = (tokens_total / 1_000_000) * DEEPSEEK_COST_PER_1M

    # Check DeepAPI service cost efficiency
    users = db("SELECT COUNT(*) FROM api_users", fetch=True)[0][0]
    paying = db("SELECT COUNT(*) FROM api_users WHERE plan IN ('starter','pro','business')", fetch=True)[0][0]

    # Estimate: each funding agent call uses ~200 tokens for LLM
    funding_calls = db("SELECT COUNT(*) FROM funding_sessions WHERE opened_at > NOW() - INTERVAL '7 days'", fetch=True)[0][0]
    funding_cost = (funding_calls * 200 / 1_000_000) * DEEPSEEK_COST_PER_1M

    return {
        'tokens_24h': tokens_24h, 'tokens_total': tokens_total,
        'cost_24h': cost_24h, 'cost_total': cost_total,
        'users': users, 'paying': paying,
        'funding_cost': funding_cost, 'funding_calls': funding_calls,
    }


def run():
    costs = get_real_costs()
    now = datetime.now(timezone.utc)

    # Build summary
    total_daily = costs['cost_24h'] + costs['funding_cost']

    if total_daily > 1.0:  # More than $1/day
        body = f"""
Real DeepSeek API costs ({now.strftime('%Y-%m-%d')}):

DeepAPI users: {costs['tokens_24h']:,} tokens in 24h = ${costs['cost_24h']:.6f}
Total all-time: {costs['tokens_total']:,} tokens = ${costs['cost_total']:.6f}
Funding agent LLM: ~${costs['funding_cost']:.4f} (est)

Users: {costs['users']} total, {costs['paying']} paying
Cost per user: ${costs['cost_24h']/costs['users']:.8f}  (${costs['cost_24h']/costs['users']*1e6:.2f} per million users)

Daily burn rate: ${total_daily:.6f}
Monthly projection: ${total_daily*30:.4f}
        """.strip()
        report_to_blanca('Daily cost summary', body, 'routine')
    else:
        # Only report if there's significant usage
        pass  # Costs are negligible, don't bother Blanca

    # Alert if costs spike >3x from yesterday
    yesterday = now - timedelta(days=1)
    # (simplified - in production we'd compare against stored history)

    print(f'VP-Finance: ${total_daily:.6f}/day | {costs["users"]} users | {costs["tokens_24h"]} tokens/24h')


if __name__ == '__main__':
    run()
