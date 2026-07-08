"""
CEO Supervisor Framework — Hardcoded business oversight.

Each CEO runs 24/7 as a systemd service. They:
1. Monitor their business service health
2. Check for errors in logs
3. Detect issues and create work orders
4. Report status to Blanca (via ceo_reports table)
5. Escalate unresolved issues to Blanca
"""
import os, sys, json, time, socket, subprocess
from datetime import datetime, timezone, timedelta

sys.path.insert(0, '/opt/agents-corp')
sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv
load_dotenv('/opt/trading/config/.env')
import psycopg2

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


class CEOSupervisor:
    def __init__(self, business_id, emoji, service_name, port, log_patterns=None):
        self.bid = business_id; self.emoji = emoji
        self.service = service_name; self.port = port
        self.log_patterns = log_patterns or ['ERROR', 'FATAL', 'exception', 'Traceback']
        self.issues_reported = set()
        self.last_report = None

    def log(self, msg):
        print(f'{datetime.now(timezone.utc).strftime("%H:%M:%S")} | {self.emoji} {self.bid} | {msg}')

    def check_service(self):
        r = subprocess.run(['systemctl', 'is-active', self.service], capture_output=True, text=True)
        return r.stdout.strip() == 'active'

    def check_port(self):
        if not self.port: return True
        try:
            s = socket.socket(); s.settimeout(3)
            s.connect(('localhost', self.port)); s.close(); return True
        except: return False

    def check_logs(self, minutes=60):
        """Scan journal for errors."""
        since = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime('%H:%M:%S')
        r = subprocess.run(['journalctl', '-u', self.service, '--since', since, '--no-pager'],
                          capture_output=True, text=True, timeout=10)
        errors = []
        for pattern in self.log_patterns:
            count = r.stdout.count(pattern)
            if count > 0:
                errors.append((pattern, count))
        return errors

    def create_work_order(self, title, description, priority='normal'):
        existing = db("SELECT id FROM work_orders WHERE title=%s AND status='open'", (title,), fetch=True)
        if existing:
            return  # Don't duplicate

        db("INSERT INTO work_orders (business_id, priority, title, description) VALUES (%s,%s,%s,%s)",
           (self.bid, priority, title, description))
        self.log(f'Work order created: {title[:80]}')

    def report_to_blanca(self, summary, issues_found=0, issues_resolved=0):
        db("INSERT INTO ceo_reports (business_id, summary, issues_found, issues_resolved, metrics) VALUES (%s,%s,%s,%s,%s)",
           (self.bid, summary, issues_found, issues_resolved,
            json.dumps({'service': self.check_service(), 'port_ok': self.check_port()})))

    def run_cycle(self):
        svc_ok = self.check_service()
        port_ok = self.check_port()
        errors = self.check_logs()
        now = datetime.now(timezone.utc)

        issues_found = 0; issues_resolved = 0

        # Service down
        if not svc_ok:
            self.create_work_order(f'{self.service} service is DOWN', f'Systemd reports inactive status', 'critical')
            issues_found += 1

        # Port down
        if not port_ok and self.port:
            self.create_work_order(f'{self.bid} port {self.port} not responding', f'Port check failed', 'high')
            issues_found += 1

        # Log errors
        for pattern, count in errors:
            if count > 5:  # Only report if significant
                issue_key = f'{pattern}:{now.strftime("%Y%m%d_%H")}'
                if issue_key not in self.issues_reported:
                    self.create_work_order(f'{count} {pattern} errors in {self.bid} logs', f'Last hour: {count} occurrences of {pattern}', 'normal')
                    self.issues_reported.add(issue_key)
                    issues_found += 1

        # Check for resolved work orders
        resolved = db("SELECT COUNT(*) FROM work_orders WHERE business_id=%s AND status='resolved' AND resolved_at > NOW() - INTERVAL '24 hours'",
                     (self.bid,), fetch=True)
        if resolved:
            issues_resolved = resolved[0][0]

        # Report to Blanca every 6 hours
        if not self.last_report or (now - self.last_report).total_seconds() > 21600:
            status = 'HEALTHY' if (svc_ok and port_ok and not errors) else 'ISSUES'
            self.report_to_blanca(f'{self.bid}: {status} | svc={svc_ok} port={port_ok} errors={len(errors)}',
                                issues_found, issues_resolved)
            self.last_report = now

        # Clean old issue tracking
        if self.cycles % 24 == 0:
            self.issues_reported = {k for k in self.issues_reported if now.strftime("%Y%m%d_%H") in k}


# ─── CEO Instances ──────────────────────────────────────────────────

class DeepAPI_CEO(CEOSupervisor):
    def __init__(self):
        super().__init__('deepapi', '🤖', 'operator-deepapi', 9001)

class PriceGuard_CEO(CEOSupervisor):
    def __init__(self):
        super().__init__('priceguard', '📊', 'operator-priceguard', 9002)

class ViralBot_CEO(CEOSupervisor):
    def __init__(self):
        super().__init__('viralbot', '📱', 'operator-viralbot', None)

class LeadGen_CEO(CEOSupervisor):
    def __init__(self):
        super().__init__('leadgen', '🎯', 'operator-leadgen', 9003)


def make_ceo_service(business_id, class_name):
    """Generate a Python entry point for a CEO service."""
    return f'''import sys; sys.path.insert(0, '/opt/agents-corp'); sys.path.insert(0, '/opt/trading')
from dotenv import load_dotenv; load_dotenv('/opt/trading/config/.env')
from ceo_supervisor import {class_name}
ceo = {class_name}()
ceo.log('CEO online — supervising {business_id}')
while True:
    try:
        ceo.cycles = getattr(ceo, 'cycles', 0) + 1
        ceo.run_cycle()
        import time; time.sleep(300)
    except KeyboardInterrupt: break
    except Exception as e: ceo.log(f'Error: {{e}}'); time.sleep(60)
'''
