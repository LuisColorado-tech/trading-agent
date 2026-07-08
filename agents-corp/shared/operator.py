"""
Business Operator Framework — Agents Corp

Cada negocio tiene un Operator que:
1. Ejecuta tareas programadas (scraping, monitoreo, generación)
2. Mantiene estado y memoria entre ejecuciones
3. Recibe instrucciones del Presidente vía Telegram
4. Reporta métricas y escalada problemas
5. Maneja solicitudes de soporte de clientes

Patrón: cada Operator es un proceso systemd 24/7 con ciclo principal.
"""
import os
import json
import time
import subprocess
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass, field, asdict


@dataclass
class BusinessMemory:
    """Estado persistente de un negocio. Se guarda en JSON."""
    business_id: str
    last_run: str = ""
    total_tasks_completed: int = 0
    total_errors: int = 0
    current_phase: str = "setup"  # setup | mvp | growth | scale
    pending_tasks: list = field(default_factory=list)
    completed_tasks: list = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    decisions: list = field(default_factory=list)
    support_tickets: list = field(default_factory=list)
    president_instructions: list = field(default_factory=list)

    def save(self, path: str):
        self.last_run = datetime.now(timezone.utc).isoformat()
        with open(path, 'w') as f:
            json.dump(asdict(self), f, indent=2, default=str)

    @classmethod
    def load(cls, path: str, business_id: str) -> 'BusinessMemory':
        if os.path.exists(path):
            with open(path) as f:
                data = json.load(f)
                return cls(**data)
        return cls(business_id=business_id)


class BusinessOperator:
    """Operador 24/7 de un negocio. Heredar para cada unidad."""

    def __init__(self, business_id: str, emoji: str, port: int = None):
        self.business_id = business_id
        self.emoji = emoji
        self.port = port
        self.memory_path = f'/opt/agents-corp/state/{business_id}.json'
        self.memory = BusinessMemory.load(self.memory_path, business_id)
        self.inbox_path = f'/opt/agents-corp/inbox/{business_id}.log'

    def run_cycle(self):
        """Ciclo principal. Override en subclases."""
        self._check_inbox()
        self._do_work()
        self._report_status()
        self.memory.save(self.memory_path)

    def _check_inbox(self):
        """Lee instrucciones del Presidente desde Telegram."""
        if not os.path.exists(self.inbox_path):
            return
        with open(self.inbox_path, 'r') as f:
            lines = f.readlines()
        if lines:
            new_instructions = [l.strip() for l in lines]
            self.memory.president_instructions.extend(new_instructions)
            # Clear inbox after reading
            open(self.inbox_path, 'w').close()
            self.log(f'Received {len(new_instructions)} presidential instructions')

    def _do_work(self):
        """Override: lógica específica del negocio."""
        pass

    def _report_status(self):
        """Override: reportar métricas."""
        pass

    def add_task(self, task: str, priority: int = 1):
        self.memory.pending_tasks.append({
            'task': task, 'priority': priority,
            'created': datetime.now(timezone.utc).isoformat()
        })

    def complete_task(self, task_desc: str):
        self.memory.completed_tasks.append({
            'task': task_desc,
            'completed': datetime.now(timezone.utc).isoformat()
        })
        self.memory.total_tasks_completed += 1

    def log_error(self, error: str):
        self.memory.total_errors += 1
        self.log(f'ERROR: {error}', level='ERROR')

    def log(self, msg: str, level: str = 'INFO'):
        ts = datetime.now(timezone.utc).strftime('%H:%M:%S')
        print(f'{ts} | {level:<5} | {self.emoji} {self.business_id} | {msg}')

    def send_telegram(self, text: str):
        """Envía mensaje al Presidente vía Telegram."""
        import urllib.request, json as j
        from dotenv import load_dotenv
        load_dotenv('/opt/trading/config/.env')
        token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        if not token or not chat_id:
            return
        payload = {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'}
        data = j.dumps(payload).encode()
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{token}/sendMessage',
            data=data, headers={'Content-Type': 'application/json'})
        try:
            urllib.request.urlopen(req, timeout=10)
        except:
            pass

    def escalate(self, issue: str, severity: str = 'MEDIUM'):
        """Escala un problema al Presidente."""
        msg = f'<b>🚨 {severity} — {self.emoji} {self.business_id}</b>\n{issue}'
        self.send_telegram(msg)

    def handle_support(self, ticket: dict):
        """Procesa ticket de soporte de cliente."""
        self.memory.support_tickets.append(ticket)
        if ticket.get('severity') == 'CRITICAL':
            self.escalate(f'Support CRITICAL: {ticket["summary"]}', 'HIGH')
        else:
            self.add_task(f'Support: {ticket["summary"]}')

    def main_loop(self, interval_seconds: int = 300):
        """Loop principal 24/7."""
        cycle = 0
        while True:
            try:
                cycle += 1
                self.run_cycle()
                time.sleep(interval_seconds)
            except KeyboardInterrupt:
                self.log('Stopped by signal')
                self.memory.save(self.memory_path)
                break
            except Exception as e:
                self.log_error(str(e))
                time.sleep(60)
