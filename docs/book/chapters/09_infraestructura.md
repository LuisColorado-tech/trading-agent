# Capítulo 9: Infraestructura de Producción

## 9.1 Stack Tecnológico

El agente corre en un VPS con Ubuntu 24.04 LTS. Stack mínimo, sin orquestadores ni contenedores — complejidad operativa innecesaria para un solo servicio.

| Componente | Versión | Rol |
|---|---|---|
| Python | 3.12 | Runtime del agente |
| PostgreSQL | 16 | Persistencia principal |
| Redis | 7 | Pub/sub entre componentes, cache de indicadores |
| Systemd | — | Gestión de procesos |
| Streamlit | latest | Dashboard de monitoreo |

El virtualenv vive en `/opt/trading/venv/`. Todo el código del proyecto en `/opt/trading/`.

```
/opt/trading/
├── scripts/          # entry points (run_trading.py)
├── src/              # módulos del agente
├── dashboard/        # Streamlit app
├── docs/             # documentación
├── .env              # API keys (no versionado)
└── venv/             # virtualenv Python 3.12
```

---

## 9.2 PostgreSQL Schema

### Tablas principales

**`market_data`** — Datos OHLCV con constraint de unicidad para evitar duplicados:

```sql
CREATE TABLE market_data (
    id SERIAL PRIMARY KEY,
    asset VARCHAR(20) NOT NULL,
    timeframe VARCHAR(10) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    exchange VARCHAR(20) NOT NULL,
    open NUMERIC, high NUMERIC, low NUMERIC, close NUMERIC,
    volume NUMERIC,
    UNIQUE(asset, timeframe, timestamp, exchange)
);
```

**`trades`** — Ciclo de vida completo de cada operación:

```sql
CREATE TABLE trades (
    id SERIAL PRIMARY KEY,
    asset VARCHAR(20),
    side VARCHAR(4),              -- BUY | SELL
    entry_price NUMERIC,
    exit_price NUMERIC,
    stop_loss NUMERIC,
    take_profit NUMERIC,
    position_size NUMERIC,
    status VARCHAR(10),           -- OPEN | CLOSED
    close_reason VARCHAR(20),     -- STOP_LOSS | TAKE_PROFIT | MANUAL
    pnl NUMERIC,
    pnl_pct NUMERIC,
    metadata JSONB DEFAULT '{}',  -- trailing_activated, claude_reasoning, etc.
    timestamp_open TIMESTAMPTZ DEFAULT NOW(),
    timestamp_close TIMESTAMPTZ
);
```

**`signals`** — Señales técnicas detectadas por el agente.

**`portfolio`** — Snapshots del estado del portfolio (serie temporal para equity curve).

**`claude_explanations`** — Registro completo de consultas y respuestas de Claude. Sirve como audit trail de las decisiones del LLM.

### Índices clave

```sql
CREATE INDEX idx_trades_status ON trades(status);
CREATE INDEX idx_trades_asset ON trades(asset);
CREATE INDEX idx_market_data_lookup ON market_data(asset, timeframe, timestamp DESC);
```

El índice en `market_data` con `timestamp DESC` es crítico — el TradeMonitor consulta el *último* precio disponible para cada activo en cada ciclo.

---

## 9.3 Servicios Systemd

Dos servicios independientes: el agente de trading y el dashboard.

### trading-agent.service

```ini
[Unit]
Description=AI Trading Agent
After=postgresql.service redis.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/trading
ExecStart=/opt/trading/venv/bin/python3 /opt/trading/scripts/run_trading.py
Restart=always
RestartSec=5
EnvironmentFile=/opt/trading/.env

[Install]
WantedBy=multi-user.target
```

- `Restart=always` + `RestartSec=5`: si el proceso muere, systemd lo reinicia en 5 segundos
- `After=postgresql.service redis.service`: no arranca hasta que las dependencias estén up
- `EnvironmentFile`: carga API keys desde `.env` sin hardcodear en el servicio

### trading-dashboard.service

```ini
[Unit]
Description=Trading Dashboard (Streamlit)
After=postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/trading
ExecStart=/opt/trading/venv/bin/streamlit run dashboard/app.py \
    --server.port 8501 \
    --server.address 127.0.0.1
Restart=always
RestartSec=5
EnvironmentFile=/opt/trading/.env

[Install]
WantedBy=multi-user.target
```

`--server.address 127.0.0.1` — el dashboard solo escucha en localhost. Acceso exclusivamente por SSH tunnel.

### Comandos operativos

```bash
# Estado
systemctl status trading-agent
journalctl -u trading-agent -f          # logs en tiempo real

# Reiniciar
systemctl restart trading-agent

# Habilitar al boot
systemctl enable trading-agent trading-dashboard
```

---

## 9.4 Logging

Loguru como framework de logging, configurado con rotación diaria y retención de 30 días:

```python
from loguru import logger

logger.add(
    "/opt/trading/logs/trading_{time:YYYY-MM-DD}.log",
    rotation="00:00",    # nuevo archivo cada medianoche
    retention="30 days",
    compression="gz",
    level="DEBUG"
)
```

### Niveles y uso

| Nivel | Uso |
|---|---|
| `DEBUG` | Valores de indicadores, precios intermedios |
| `INFO` | Apertura/cierre de trades, inicio de ciclo, señales detectadas |
| `WARNING` | Fallo en llamada a Claude (retry automático), datos de mercado incompletos |
| `ERROR` | Excepciones capturadas, fallo de conexión a DB |
| `CRITICAL` | Drawdown excede límite — el agente se detiene |

### Ejemplo de output

```
2026-03-15 14:32:01 | INFO | TradeMonitor: Evaluando 3 trades abiertos
2026-03-15 14:32:01 | INFO | Trade #142 BTC BUY: precio=$67,450 SL=$65,000 TP=$70,000 → HOLD
2026-03-15 14:32:01 | INFO | Trade #145 ETH SELL: precio=$3,180 SL=$3,300 TP=$2,900 → HOLD
2026-03-15 14:32:02 | INFO | Trailing activado trade #143: SL movido a break-even $3,050
```

---

## 9.5 Dashboard (Streamlit)

Dashboard de monitoreo con 4 tabs, conectado directamente a PostgreSQL.

### Tabs

1. **Portfolio** — Balance actual, drawdown, equity curve (Plotly line chart desde `portfolio` snapshots)
2. **Trades** — Tabla de trades con filtros por status, asset, fecha. Detalle de cada trade con metadata
3. **Signals** — Señales técnicas recientes, agrupadas por asset
4. **AI Analysis** — Últimas explicaciones de Claude, con el prompt enviado y la respuesta completa

### Equity Curve

```python
import plotly.express as px

df = pd.read_sql("SELECT timestamp, balance FROM portfolio ORDER BY timestamp", conn)
fig = px.line(df, x='timestamp', y='balance', title='Equity Curve')
st.plotly_chart(fig, use_container_width=True)
```

### Acceso

El dashboard **no** está expuesto públicamente. Puerto 8501 escucha solo en `127.0.0.1`. Para acceder:

```bash
ssh -L 8501:localhost:8501 root@<IP_DEL_VPS>
# Luego abrir http://localhost:8501 en el browser local
```

---

## 9.6 Seguridad

### Firewall (UFW)

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    # SSH
ufw enable
```

Solo puerto 22 abierto. PostgreSQL (5432), Redis (6379) y Streamlit (8501) no son accesibles desde el exterior.

### API Keys

Todas las credenciales en `/opt/trading/.env`:

```bash
ANTHROPIC_API_KEY=sk-ant-...
SUPABASE_URL=https://...
SUPABASE_KEY=...
ALPHA_VANTAGE_KEY=...
```

El archivo `.env` tiene permisos `600` y está en `.gitignore`. Systemd lo carga via `EnvironmentFile`.

### Superficie de ataque

| Vector | Mitigación |
|---|---|
| SSH | Solo key-based auth, no password |
| Dashboard | SSH tunnel, no público |
| DB | Solo localhost, no TCP externo |
| Redis | Solo localhost, sin auth (interno) |
| API keys | `.env` con permisos restrictivos |
| Dependencias | `pip audit` periódico |

El principio es simple: **nada está expuesto excepto SSH**. Todo lo demás se accede por tunnel.

---

## Resumen del Capítulo

| Componente | Decisión | Razón |
|---|---|---|
| VPS bare metal | Sin Docker/K8s | Un solo servicio, complejidad innecesaria |
| PostgreSQL | Persistencia principal | ACID, JSONB, time-series friendly |
| Redis | Pub/sub + cache | Desacoplamiento entre componentes |
| Systemd | 2 servicios | Restart automático, gestión nativa |
| Loguru | Logging estructurado | Rotación diaria, compresión, retención |
| UFW | Solo SSH abierto | Superficie mínima de ataque |
| SSH tunnel | Acceso a dashboard | Sin endpoints públicos |
