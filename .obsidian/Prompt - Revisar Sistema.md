# Prompt — Revisar Sistema

> Pegar este texto exacto en una nueva sesión de OpenCode sin contexto.

---

```
Leé /opt/trading/AGENTS.md completo. Luego ejecutá:

cd /opt/trading && venv/bin/python3 scripts/spec_check.py

Si hay ❌, leé el SPEC del agente en /opt/trading/specs/ antes de tocar código.

Reglas:
- NUNCA crear módulos nuevos sin verificar que no existen (ls core/*guard*)
- NUNCA proponer un fix sin ver "REJECTED:" en logs
- Si es cambio de parámetro → trading_council.py
- spec_check.py ANTES y DESPUÉS de cualquier cambio
- Python: /opt/trading/venv/bin/python3 (nunca python3 del sistema)
```
