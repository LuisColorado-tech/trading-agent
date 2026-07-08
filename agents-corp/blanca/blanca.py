"""
Blanca — Personal AI Assistant to the President of Agents Corp

Role: Bridge between the company and the President. Like Alfred to Bruce Wayne.
- All CEOs report to Blanca, not directly to the President
- Blanca filters: only critical/strategic matters reach the President via Telegram
- Blanca makes operational decisions autonomously
- Blanca consults an internal advisory council for complex decisions
- Blanca runs 24/7 as a systemd service

Council members:
  - Strategist: long-term vision, resource allocation
  - Analyst: data-driven decisions, metrics
  - Guardian: risk assessment, security, worst-case
  - Diplomat: stakeholder communication, PR

Memory: PostgreSQL tables for persistent context, decisions, and history.
"""
import os, sys, json, time, urllib.request
from datetime import datetime, timezone, timedelta
from collections import defaultdict

sys.path.insert(0, '/opt/agents-corp')
sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')

DS_KEY = os.getenv("DEEPSEEK_API_KEY", "")
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ─── Council of Advisors ───────────────────────────────────────────

COUNCIL = {
    "Strategist": {
        "emoji": "♟️", "role": "Estratega",
        "prompt": "You are the Strategist on Blanca's Advisory Council. Focus on long-term vision, resource allocation, market positioning, and competitive advantage. Be bold. Recommend YES or NO with reasoning in 2-3 sentences."
    },
    "Analyst": {
        "emoji": "📈", "role": "Analista",
        "prompt": "You are the Data Analyst on Blanca's Advisory Council. Focus on metrics, trends, numbers. Be precise. Recommend YES or NO based on data patterns with specific metrics in 2-3 sentences."
    },
    "Guardian": {
        "emoji": "🛡️", "role": "Guardián",
        "prompt": "You are the Risk Guardian on Blanca's Advisory Council. Focus on worst-case scenarios, security, legal exposure, reputation risk. Be conservative. Recommend YES or NO based on risk assessment in 2-3 sentences."
    },
    "Diplomat": {
        "emoji": "🤝", "role": "Diplomática",
        "prompt": "You are the Communications Diplomat on Blanca's Advisory Council. Focus on stakeholder impact, messaging, brand perception, customer experience. Be pragmatic. Recommend YES or NO based on communication impact in 2-3 sentences."
    },
}


# ─── Database ──────────────────────────────────────────────────────

import psycopg2
DB_CONFIG = {
    'host': os.getenv('POSTGRES_HOST', 'localhost'),
    'port': int(os.getenv('POSTGRES_PORT', '5432')),
    'user': os.getenv('POSTGRES_USER'),
    'password': os.getenv('POSTGRES_PASSWORD'),
    'dbname': os.getenv('POSTGRES_DB', 'trading_agent'),
    'connect_timeout': 5,
}

def db_execute(sql: str, params: tuple = None, fetch: bool = False):
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute(sql, params)
    if fetch:
        result = cur.fetchall()
        cur.close(); conn.close()
        return result
    conn.commit()
    cur.close(); conn.close()


# ─── LLM Engine ────────────────────────────────────────────────────

def call_deepseek(system_prompt: str, user_prompt: str, temperature: float = 0.5) -> str:
    if not DS_KEY: return "NO_API_KEY"
    payload = json.dumps({
        "model": "deepseek-chat",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": 500, "temperature": temperature,
    }).encode()
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions", data=payload,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {DS_KEY}"})
    try:
        resp = urllib.request.urlopen(req, timeout=45)
        return json.loads(resp.read())["choices"][0]["message"]["content"]
    except Exception as e:
        return f"LLM_ERROR: {str(e)[:100]}"


def send_telegram(text: str):
    if not TOKEN or not CHAT_ID: return
    payload = {'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'HTML'}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f'https://api.telegram.org/bot{TOKEN}/sendMessage',
        data=data, headers={'Content-Type': 'application/json'})
    try: urllib.request.urlopen(req, timeout=10)
    except: pass


# ─── Blanca Core ───────────────────────────────────────────────────

class Blanca:
    def __init__(self):
        self.name = "Blanca"
        self.emoji = "🤍"
        self.start_time = datetime.now(timezone.utc)
        self.cycles = 0
        self.log(f"Blanca online. Protecting the President's time.")

    def log(self, msg: str, level: str = "INFO"):
        ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
        print(f'{ts} | {self.emoji} Blanca | {msg}')

    def run_cycle(self):
        self.cycles += 1
        self._process_inbox()
        self._review_pending_decisions()
        self._update_context()
        self._save_snapshot()

    # ─── Inbox Processing ──────────────────────────────────────

    def _process_inbox(self):
        """Read incoming messages from agents and process them."""
        rows = db_execute(
            "SELECT id, from_agent, subject, body, category, urgency FROM blanca_inbox WHERE status='pending' ORDER BY created_at LIMIT 5",
            fetch=True)

        for row in rows:
            msg_id, agent, subject, body, category, urgency = row
            self.log(f"Processing: [{urgency}] {agent}: {subject[:60]}")

            if urgency == 'critical':
                # Immediate escalation to President
                self._escalate(agent, subject, body, urgency)
                db_execute("UPDATE blanca_inbox SET status='escalated', blanca_decision='President notified', escalated=true, resolved_at=NOW() WHERE id=%s", (msg_id,))
            elif urgency == 'high':
                # Consult council, then decide
                decision = self._consult_council(agent, subject, body, category)
                if decision.get('escalate'):
                    self._escalate(agent, subject, body, urgency)
                    db_execute("UPDATE blanca_inbox SET status='escalated', blanca_decision=%s, escalated=true, resolved_at=NOW() WHERE id=%s",
                              (decision['summary'], msg_id))
                else:
                    db_execute("UPDATE blanca_inbox SET status='resolved', blanca_decision=%s, resolved_at=NOW() WHERE id=%s",
                              (decision['summary'], msg_id))
            else:
                # Routine: resolve autonomously
                db_execute("UPDATE blanca_inbox SET status='resolved', blanca_decision='Routine - resolved autonomously', resolved_at=NOW() WHERE id=%s",
                          (msg_id,))

    def _review_pending_decisions(self):
        """Review unresolved decisions and escalate if stuck."""
        rows = db_execute(
            "SELECT id, summary FROM blanca_decisions WHERE resolved=false AND created_at < NOW() - INTERVAL '24 hours'",
            fetch=True)
        if rows:
            for row in rows:
                self._escalate("Blanca", f"Decision pendiente >24h", row[1], "warning")
                db_execute("UPDATE blanca_decisions SET escalated_to_president=true WHERE id=%s", (row[0],))

    def _update_context(self):
        """Keep Blanca's context fresh."""
        # Store current state snapshot
        state = json.dumps({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "cycles": self.cycles,
            "uptime_hours": (datetime.now(timezone.utc) - self.start_time).total_seconds() / 3600,
        })
        db_execute(
            "INSERT INTO blanca_memory (category, key, value, importance) VALUES ('state', 'runtime', %s, 'routine') ON CONFLICT (category, key) DO UPDATE SET value=%s, updated_at=NOW()",
            (state, state))

    def _save_snapshot(self):
        """Save quick snapshot every cycle."""
        pass  # Data already persited through DB operations

    # ─── Council Consultation ──────────────────────────────────

    def _consult_council(self, agent: str, subject: str, body: str, category: str) -> dict:
        """Convene Blanca's advisory council for a decision."""
        self.log(f"Convening council for: {subject[:60]}")

        context = f"""Context from {agent}:
Category: {category}
Subject: {subject}
Details: {body[:1000]}

Question: Should this be escalated to the President immediately, or can Blanca handle it autonomously? Answer YES to escalate, NO to handle."""

        votes = {}
        recommendations = []
        for name, info in COUNCIL.items():
            response = call_deepseek(info['prompt'], context, temperature=0.4)
            vote_yes = response.strip().upper().startswith('YES')
            votes[name] = {"vote": "YES" if vote_yes else "NO", "reasoning": response}
            recommendations.append(f"{info['emoji']} {name}: {response[:150]}")
            self.log(f"  {info['emoji']} {name}: {'ESCALATE' if vote_yes else 'HANDLE'}")

        yes_count = sum(1 for v in votes.values() if v['vote'] == 'YES')
        escalate = yes_count >= 2  # Majority vote to escalate

        decision_summary = "ESCALATE to President" if escalate else f"Handled autonomously ({yes_count}/4 votes to escalate)"

        # Store decision
        context_json = json.dumps({"body": body[:500], "category": category})
        votes_json = json.dumps(votes)
        db_execute(
            "INSERT INTO blanca_decisions (source, summary, context, decision, council_consulted, council_votes, resolved) VALUES (%s, %s, %s, %s, true, %s, true)",
            (agent, subject, context_json, decision_summary, votes_json))

        recs_text = '\n'.join(recommendations)
        return {"escalate": escalate, "summary": decision_summary, "votes": votes, "council": recs_text}

    # ─── Presidential Communication ────────────────────────────

    def _escalate(self, agent: str, subject: str, body: str, urgency: str):
        """Send message to President. ONLY for truly important matters."""
        emoji_map = {'critical': '🚨', 'high': '⚠️', 'warning': '📋'}
        emoji = emoji_map.get(urgency, 'ℹ️')

        msg = f'{emoji} <b>Blanca — {urgency.upper()}</b>\n'
        msg += f'<b>From:</b> {agent}\n'
        msg += f'<b>Subject:</b> {subject}\n\n'
        msg += f'{body[:800]}\n\n'
        msg += f'<i>— Blanca 🤍 | {datetime.now(timezone.utc).strftime("%H:%M UTC")}</i>'

        send_telegram(msg)
        self.log(f"Escalated to President: {subject[:60]}")

    def send_update(self):
        """Daily briefing to President (only if there's relevant news)."""
        # Count pending items
        pending = db_execute("SELECT COUNT(*) FROM blanca_inbox WHERE status='pending'", fetch=True)
        decisions = db_execute("SELECT COUNT(*) FROM blanca_decisions WHERE resolved=false", fetch=True)
        escalated = db_execute("SELECT COUNT(*) FROM blanca_inbox WHERE escalated=true AND resolved_at > NOW() - INTERVAL '24 hours'", fetch=True)

        p_count = pending[0][0] if pending else 0
        d_count = decisions[0][0] if decisions else 0
        e_count = escalated[0][0] if escalated else 0

        if p_count == 0 and d_count == 0 and e_count == 0:
            return  # Nothing to report

        msg = f'<b>🤍 Blanca — Daily Briefing</b>\n'
        msg += f'{datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}\n\n'
        msg += f'Pending inbox: {p_count}\n'
        msg += f'Open decisions: {d_count}\n'
        msg += f'Escalated (24h): {e_count}\n\n'

        # Top pending items
        if p_count > 0:
            rows = db_execute("SELECT from_agent, subject, urgency FROM blanca_inbox WHERE status='pending' ORDER BY CASE urgency WHEN 'critical' THEN 1 WHEN 'high' THEN 2 ELSE 3 END, created_at LIMIT 3", fetch=True)
            msg += '<b>Top pending:</b>\n'
            for r in rows:
                msg += f'  [{r[2]}] {r[0]}: {r[1][:80]}\n'

        msg += f'\n<i>Routine matters handled autonomously.</i>'
        send_telegram(msg)

    # ─── Main Loop ─────────────────────────────────────────────

    def main_loop(self):
        self.log("Blanca's systems active. Filtering the noise.")
        last_daily = None
        while True:
            try:
                self.run_cycle()

                # Daily briefing at 08:00 UTC
                now = datetime.now(timezone.utc)
                if now.hour == 8 and now.minute < 5 and last_daily != now.date():
                    self.send_update()
                    last_daily = now.date()

                time.sleep(60)  # Check every minute
            except KeyboardInterrupt:
                self.log("Shutting down. The President's time is safe.")
                break
            except Exception as e:
                self.log(f"Error: {e}")
                time.sleep(60)


# ─── Entry Point ───────────────────────────────────────────────────

if __name__ == '__main__':
    blanca = Blanca()

    # Check if DeepSeek API key is available
    if not DS_KEY:
        blanca.log("WARNING: No DeepSeek API key. Council will be unavailable.")

    blanca.main_loop()
