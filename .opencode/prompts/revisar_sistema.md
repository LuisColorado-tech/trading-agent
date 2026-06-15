Revisá el sistema de trading completo. Empezá por leer estos archivos en orden:

@AGENTS.md

Luego ejecutá:
```bash
cd /opt/trading && venv/bin/python3 scripts/spec_check.py
```

Si hay errores (❌), leé el SPEC del agente afectado:
@specs/SPEC_SYSTEM.md
@specs/SPEC_TREND_MOMENTUM.md  
@specs/SPEC_STOCKS.md

Para cualquier agente que no opere, seguí el protocolo del SPEC:
1. ¿Está vivo? → `systemctl is-active <servicio>`
2. ¿Está operando? → métricas de DB, no opiniones
3. Si no opera, TRAZAR SEÑAL COMPLETA → `Opportunity:` → `REJECTED:` → `Executed trade:`
4. El motivo de REJECTED es la causa raíz. No asumir nada sin verlo.

Reglas absolutas:
- NUNCA crear un módulo nuevo sin verificar que no existe
- NUNCA proponer un fix sin ver REJECTED en los logs
- Si es cambio de parámetro → Council, no decidir solo
- Ejecutar spec_check.py ANTES y DESPUÉS de cualquier cambio
