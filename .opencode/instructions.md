Antes de escribir código o proponer fixes, ejecutar en este orden exacto:

1. cd /opt/trading && venv/bin/python3 scripts/ai_context.py
2. cd /opt/trading && venv/bin/python3 scripts/spec_check.py
3. Si hay ❌ → leer el SPEC del agente afectado en /opt/trading/specs/
4. Si el SPEC no existe o no cubre el problema → leer AGENTS.md completo
5. Seguir el pipeline de diagnóstico del SPEC paso a paso
6. NUNCA crear un módulo nuevo sin verificar que no existe
7. NUNCA proponer un fix sin ver REJECTED en logs
8. Si es cambio de parámetro → usar trading_council.py, no decidir solo
