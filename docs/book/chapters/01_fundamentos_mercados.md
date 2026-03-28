# Capítulo 1: Fundamentos de Mercados Financieros

> *"El mercado es un mecanismo de transferencia de riqueza del impaciente al paciente."*
> — Warren Buffett

---

## 1.1 Introducción: ¿Qué es un mercado financiero?

Un mercado financiero es un espacio —físico o virtual— donde compradores y vendedores intercambian activos financieros a precios determinados por la oferta y la demanda. En su forma más abstracta, un mercado es una **función de emparejamiento** (matching function) que conecta una orden de compra con una orden de venta, generando un precio de ejecución y una cantidad transaccionada.

Para nuestro agente de trading, los mercados no son entidades monolíticas: cada exchange, cada par de trading y cada tipo de contrato tiene características propias de liquidez, latencia, comisiones y riesgo de contraparte. Comprender estas diferencias es el primer paso para diseñar un sistema que opere con precisión.

---

## 1.2 Mercados Spot vs Futuros vs Perpetuos

### 1.2.1 Mercado Spot (Contado)

El mercado spot es el más intuitivo: compras un activo y lo posees inmediatamente. Si comprás 0.5 BTC en Kraken al contado, esos 0.5 BTC aparecen en tu billetera del exchange. La liquidación es **T+0** (instantánea en crypto, T+2 en mercados tradicionales).

**Características clave:**
- **Propiedad real**: poseés el activo subyacente.
- **Sin apalancamiento nativo**: comprás con tu capital disponible (1:1).
- **Sin fecha de expiración**: la posición existe mientras conserves el activo.
- **Riesgo**: limitado al capital invertido (no podés perder más de lo que pusiste).

En nuestro sistema, **todos los pares crypto (BTC, ETH, SOL) y el oro tokenizado (XAU vía XAUT)** operan en mercado spot. La razón es pragmática: para un agente en fase de paper trading, el spot elimina la complejidad del margen, las liquidaciones forzadas y el funding rate.

### 1.2.2 Mercados de Futuros

Un contrato de futuros es un **acuerdo estandarizado** para comprar o vender un activo a un precio fijo en una fecha futura. Matemáticamente, el precio del futuro ($F$) se relaciona con el precio spot ($S$) mediante la fórmula de **cost of carry**:

$$F = S \cdot e^{(r - y)(T - t)}$$

Donde:
- $r$ = tasa libre de riesgo
- $y$ = rendimiento por tenencia del activo (dividendos, conveniencia)
- $T - t$ = tiempo hasta el vencimiento

Los futuros requieren **margen** (un depósito de garantía, típicamente 5-20% del valor nocional) y se **liquidan** periódicamente (mark-to-market). Si el margen cae por debajo del nivel de mantenimiento, el exchange emite un **margin call** o liquida la posición automáticamente.

### 1.2.3 Contratos Perpetuos (Perpetual Swaps)

Los contratos perpetuos son una innovación del ecosistema crypto, popularizados por BitMEX en 2016. Son como futuros **sin fecha de vencimiento**: el contrato nunca expira, pero un mecanismo llamado **funding rate** mantiene el precio del perpetuo anclado al precio spot.

**Funding Rate:**

$$\text{Funding} = \text{Position Size} \times \text{Funding Rate}$$

El funding rate se calcula típicamente cada 8 horas. Si el perpetuo cotiza **por encima** del spot (premium), los longs pagan a los shorts (incentivando ventas para alinear precios). Si cotiza **por debajo** (discount), los shorts pagan a los longs.

**¿Por qué nuestro agente usa perpetuos para plata (XAG)?**

La plata no tiene un token spot ampliamente líquido en el ecosistema crypto. A diferencia del oro, donde existen tokens como XAUT (Tether Gold) y PAXG (Pax Gold) respaldados 1:1 por onzas troy físicas, la plata carece de un equivalente con liquidez suficiente. OKX ofrece el par `XAG/USDT:USDT` como contrato perpetuo, que es la única vía accesible para operar plata desde nuestro VPS. Esto implica:

1. **Necesidad de margen**: el agente debe gestionar colateral.
2. **Funding rate**: costo periódico que afecta el P&L.
3. **Riesgo de liquidación**: si el margen es insuficiente, la posición se cierra forzosamente.

Estas consideraciones adicionales están codificadas en el `RiskManager`, que aplica reglas más conservadoras para activos en perpetuos.

---

## 1.3 OHLCV: La Estructura Universal de Datos de Mercado

### 1.3.1 Anatomía de una Vela

Toda la información de precios que consume nuestro agente llega en formato **OHLCV** (Open, High, Low, Close, Volume). Cada registro representa un período de tiempo (timeframe) y contiene:

| Campo     | Significado                                                   |
|-----------|---------------------------------------------------------------|
| **Open**  | Primer precio transaccionado en el período                    |
| **High**  | Precio máximo alcanzado durante el período                    |
| **Low**   | Precio mínimo alcanzado durante el período                    |
| **Close** | Último precio transaccionado en el período                    |
| **Volume**| Cantidad total de activo transaccionado en el período         |

Esta abstracción, conocida como **vela japonesa** (candlestick), fue inventada en el Japón del siglo XVIII por Munehisa Homma para analizar el mercado del arroz. Siglos después, sigue siendo la representación estándar en todos los mercados financieros del mundo.

### 1.3.2 ¿Por qué OHLCV y no tick data?

El tick data (cada transacción individual) contiene la máxima granularidad posible, pero presenta problemas prácticos:
- **Volumen de datos**: millones de ticks por día para activos líquidos.
- **Ruido**: la mayoría de los ticks no tienen significancia estadística.
- **Costo**: los feeds de tick data en tiempo real son caros.

OHLCV comprime la información en intervalos manejables, preservando las **cuatro dimensiones más relevantes** del precio (apertura, máximo, mínimo, cierre) más el volumen como proxy de convicción del mercado. Es un compromiso óptimo entre información y eficiencia.

### 1.3.3 Timeframes en el Sistema

Nuestro agente consume datos en múltiples timeframes:
- **1m (1 minuto)**: máxima resolución, usado para timing de entrada/salida.
- **5m (5 minutos)**: balance entre resolución y ruido.
- **15m (15 minutos)**: timeframe principal de análisis.
- **1h (1 hora)**: perspectiva de tendencia macro.

No todos los activos tienen todos los timeframes. Por ejemplo, XAG (plata) solo está configurado en 15m y 1h, dado que su volatilidad intradía no justifica timeframes más cortos en un contrato perpetuo con funding rate.

---

## 1.4 Microestructura de Mercado

### 1.4.1 El Libro de Órdenes (Order Book)

El corazón de cualquier exchange es su **order book**: una estructura de datos que mantiene dos listas ordenadas:
- **Bids** (ofertas de compra): ordenadas de mayor a menor precio.
- **Asks** (ofertas de venta): ordenadas de menor a mayor precio.

El **best bid** es el precio más alto que alguien está dispuesto a pagar; el **best ask** es el precio más bajo al que alguien está dispuesto a vender. La diferencia entre ambos es el **bid-ask spread**.

### 1.4.2 Bid-Ask Spread

$$\text{Spread} = P_{ask} - P_{bid}$$

$$\text{Spread relativo} = \frac{P_{ask} - P_{bid}}{P_{mid}} \times 100\%$$

Donde $P_{mid} = \frac{P_{ask} + P_{bid}}{2}$ es el precio medio (mid price).

El spread es un **costo implícito** de transacción. Cada vez que nuestro agente ejecuta una orden de mercado, paga el spread completo. Para BTC/USDT en Kraken, el spread típico es de 0.01-0.05% (extremadamente líquido). Para XAG/USDT en OKX, puede ser 0.1-0.3% (menor liquidez).

### 1.4.3 Slippage

El slippage es la diferencia entre el precio esperado y el precio real de ejecución. Ocurre cuando:
1. **Liquidez insuficiente**: la orden consume múltiples niveles del order book.
2. **Latencia**: el mercado se mueve entre el envío y la ejecución de la orden.

$$\text{Slippage} = P_{ejecutado} - P_{esperado}$$

Para nuestro agente, el slippage es especialmente relevante en:
- Activos de menor liquidez (XAG, SOL).
- Momentos de alta volatilidad (breakouts, noticias).
- Órdenes de tamaño grande relativo a la profundidad del order book.

### 1.4.4 Market Makers y Liquidez

Los **market makers** son participantes que colocan órdenes límite en ambos lados del book (bid y ask), proporcionando liquidez al mercado a cambio del spread como ganancia. Sin market makers, los spreads serían enormes y el mercado funcionaría de forma intermitente.

En crypto, los market makers suelen ser firmas algorítmicas (Jump Trading, Wintermute, GSR) que operan con latencias de microsegundos. Nuestro agente, operando con latencias de segundos, no compite con ellos: es un **liquidity taker** (tomador de liquidez) que ejecuta órdenes de mercado contra la liquidez provista por los makers.

---

## 1.5 Activos del Sistema

### 1.5.1 Crypto Majors

**Bitcoin (BTC)** — El activo digital de mayor capitalización y liquidez. Su volatilidad anualizada oscila entre 50-80%, lo que lo hace ideal para estrategias de trend following y breakout. El agente lo opera en Kraken como par spot BTC/USDT.

**Ethereum (ETH)** — Segunda mayor capitalización. Presenta una correlación alta con BTC ($\rho$ ≈ 0.85) pero con mayor beta (movimientos amplificados). Interesante para mean reversion cuando diverge temporalmente de BTC. Par spot ETH/USDT en Kraken.

**Solana (SOL)** — Crypto de alta beta ($\beta$ ≈ 1.5-2.0 respecto a BTC). Mayor volatilidad implica mayor riesgo y mayor oportunidad. El agente aplica posiciones más pequeñas por su volatilidad. Par spot SOL/USDT en Kraken.

### 1.5.2 Metales Preciosos Tokenizados

**Oro (XAU vía XAUT)** — Tether Gold (XAUT) es un token ERC-20 respaldado 1:1 por una onza troy de oro físico depositado en bóvedas suizas. Su precio sigue fielmente al oro spot ($XAU). Volatilidad anualizada ~15-20%, significativamente menor que crypto. Ideal para mean reversion y como activo no correlacionado con crypto, proporcionando diversificación real al portafolio.

**Plata (XAG)** — Operado como contrato perpetuo `XAG/USDT:USDT` en OKX. La plata tiene un ratio histórico XAU/XAG de ~80:1, con reversiones a la media bien documentadas. Volatilidad ~20-25% anualizada. Su inclusión en el portafolio responde a dos razones:
1. **Diversificación real**: correlación con crypto < 0.3.
2. **Mean reversion**: el ratio oro/plata es uno de los mean-reverting trades más estudiados en la historia financiera.

### 1.5.3 ¿Por qué estos activos específicos?

La selección no es arbitraria. Responde a criterios de:
- **Liquidez**: todos tienen volumen diario suficiente para que el agente opere sin impacto de mercado significativo.
- **Diversificación**: la combinación crypto + metales reduce la correlación del portafolio total.
- **Disponibilidad**: todos son accesibles desde los exchanges que operamos (Kraken + OKX).
- **Cobertura estratégica**: cada activo tiene una "personalidad" que favorece distintas estrategias (BTC para breakout, XAU para mean reversion, SOL para momentum).

---

## 1.6 Exchanges: Kraken y OKX

### 1.6.1 Kraken — Exchange Primario

Kraken es uno de los exchanges de criptomonedas más antiguos (fundado en 2011) y reputados. Fue elegido como exchange primario por:
- **Regulación**: licenciado en múltiples jurisdicciones.
- **Uptime**: historial de disponibilidad superior al 99.5%.
- **API robusta**: REST + WebSocket con buena documentación y rate limits razonables.
- **Comisiones competitivas**: 0.16% maker / 0.26% taker para volúmenes base.
- **Accesibilidad**: sin restricciones geográficas para nuestro VPS.

### 1.6.2 OKX — Exchange Secundario/Metales

OKX funciona como exchange secundario, con una función crítica: **es el único exchange accesible que ofrece perpetuos de plata (XAG)**. Además:
- Soporta oro tokenizado (XAUT/USDT) como alternativa a Kraken.
- Ofrece perpetuos de metales con liquidez aceptable.
- Su API ccxt es madura y estable.

### 1.6.3 La Historia de Binance: HTTP 451

La configuración original del agente contemplaba Binance como exchange primario. Sin embargo, al desplegar el sistema en el VPS (ubicación geográfica restringida), todas las peticiones a `api.binance.com` recibían **HTTP 451 — Unavailable For Legal Reasons**. Esta restricción geográfica, implementada a nivel de CDN, bloqueaba tanto la API principal como los endpoints de testnet spot.

El archivo `exchange_config.yaml` documenta esta decisión:

```yaml
# ── NOTA sobre Binance (main) ──
# api.binance.com está bloqueado desde este VPS (HTTP 451 — geo-restriction).
# Testnet spot y futures mainnet también bloqueados.
# Solo testnet.binancefuture.com y api.binance.us responden.
# Decisión: usar Kraken + OKX como reemplazo total.
```

Binance US queda como backup deshabilitado (`enabled: false`), disponible solo para BTC y ETH con volumen inferior.

---

## 1.7 Implementación: `market_feed.py` — Obtención Multi-Exchange

El módulo `market_feed.py` es la interfaz entre el agente y los exchanges. Implementa tres responsabilidades fundamentales: descarga de datos, persistencia y consulta.

### 1.7.1 Configuración Dirigida por YAML

En lugar de hardcodear exchanges y pares en el código, el sistema usa `exchange_config.yaml` como fuente de verdad. Esto permite:
- Cambiar de exchange sin tocar código Python.
- Habilitar/deshabilitar exchanges con un flag booleano.
- Agregar activos o timeframes editando YAML.

La función `_build_asset_map()` construye un diccionario que mapea cada activo a su exchange preferido:

```python
def _build_asset_map():
    """Construye mapeo de assets priorizando exchange primario."""
    asset_map = {}
    for exc_name, exc_cfg in _EXCHANGE_CFG['exchanges'].items():
        if not exc_cfg.get('enabled', False):
            continue
        role = exc_cfg.get('role', 'backup')
        for asset_key, asset_cfg in exc_cfg.get('assets', {}).items():
            if asset_key not in asset_map or role == 'primary':
                asset_map[asset_key] = {
                    'exchange': exc_name,
                    'ccxt_id': exc_cfg['ccxt_id'],
                    'pair': asset_cfg['pair'],
                    'timeframes': asset_cfg['timeframes'],
                }
    return asset_map
```

La lógica de prioridad es elegante: itera todos los exchanges habilitados. Si un activo aparece en múltiples exchanges, el de rol `primary` siempre gana. Así, BTC se resuelve a Kraken (primary) aunque también existe en OKX, pero XAG se resuelve a OKX (el único que lo ofrece).

### 1.7.2 Instanciación de Exchanges vía CCXT

CCXT (CryptoCurrency eXchange Trading Library) es una librería que abstrae las APIs de más de 100 exchanges bajo una interfaz unificada. La clase `MarketFeed` instancia dinámicamente los exchanges habilitados:

```python
class MarketFeed:
    def __init__(self):
        self._exchanges = {}
        for exc_name, exc_cfg in _EXCHANGE_CFG['exchanges'].items():
            if not exc_cfg.get('enabled', False):
                continue
            ccxt_id = exc_cfg['ccxt_id']
            cls = getattr(ccxt, ccxt_id)
            env_prefix = exc_name.upper()
            self._exchanges[exc_name] = cls({
                'apiKey': os.getenv(f'{env_prefix}_API_KEY', ''),
                'secret': os.getenv(f'{env_prefix}_SECRET', ''),
                'enableRateLimit': exc_cfg.get('rate_limit', True),
            })
```

Nótese el patrón: `getattr(ccxt, ccxt_id)` obtiene la clase del exchange dinámicamente (e.g., `ccxt.kraken`, `ccxt.okx`), y las credenciales se leen de variables de entorno con el prefijo del exchange (`KRAKEN_API_KEY`, `OKX_SECRET`).

### 1.7.3 El Patrón Cache-Aside

El método `refresh()` implementa el patrón **cache-aside** (también llamado lazy loading):

```python
def refresh(self, asset, timeframe, limit=OHLCV_LIMIT):
    """Fetch + save + return from DB."""
    df = self.fetch_ohlcv(asset, timeframe, limit)
    if not df.empty:
        self.save_ohlcv(df)
    return self.get_latest(asset, timeframe, n=limit)
```

El flujo es:
1. **Fetch**: descarga datos frescos del exchange.
2. **Save**: persiste en PostgreSQL con upsert (ignora duplicados vía `ON CONFLICT DO NOTHING`).
3. **Return from DB**: lee desde la base de datos, garantizando datos ordenados y consistentes.

¿Por qué no devolver directamente el DataFrame descargado? Porque la base de datos actúa como **fuente de verdad normalizada**: los datos están deduplicados, ordenados temporalmente y son consultables por otros componentes del sistema sin depender del exchange.

### 1.7.4 Persistencia con Upsert

El método `save_ohlcv()` usa una sentencia SQL con `ON CONFLICT DO NOTHING`, lo que convierte cada inserción en idempotente. Si la vela (identificada por `asset + timeframe + timestamp + exchange`) ya existe, la inserción se ignora silenciosamente. Esto permite ejecutar `refresh()` frecuentemente sin preocuparse por duplicados.

---

## 1.8 Modelo de Datos: La Tabla `market_data`

La tabla PostgreSQL `market_data` tiene la siguiente estructura:

| Columna     | Tipo          | Descripción                        |
|-------------|---------------|------------------------------------|
| asset       | VARCHAR       | Identificador del activo (BTC, ETH, XAG) |
| timeframe   | VARCHAR       | Intervalo temporal (1m, 5m, 15m, 1h) |
| timestamp   | TIMESTAMPTZ   | Momento exacto de la vela (UTC)    |
| open        | DECIMAL       | Precio de apertura                 |
| high        | DECIMAL       | Precio máximo                      |
| low         | DECIMAL       | Precio mínimo                      |
| close       | DECIMAL       | Precio de cierre                   |
| volume      | DECIMAL       | Volumen transaccionado             |
| exchange    | VARCHAR       | Exchange de origen                 |

La clave única compuesta `(asset, timeframe, timestamp, exchange)` garantiza que no haya velas duplicadas. Esta constraint es la que habilita el `ON CONFLICT DO NOTHING` en el upsert.

---

## 1.9 Flujo Completo: Del Exchange al Indicador

Para cerrar el capítulo, visualicemos el flujo completo de datos:

```
Exchange (Kraken/OKX)
    │
    ▼ CCXT: fetch_ohlcv()
    │
MarketFeed.fetch_ohlcv()
    │
    ▼ DataFrame con OHLCV
    │
MarketFeed.save_ohlcv()
    │
    ▼ PostgreSQL (market_data)
    │
MarketFeed.get_latest()
    │
    ▼ DataFrame limpio y ordenado
    │
IndicatorEngine.calculate()
    │
    ▼ IndicatorSet (frozen dataclass)
    │
StrategyEngine.evaluate()
```

Este pipeline transforma datos crudos de mercado en señales de trading accionables. En el próximo capítulo, nos sumergiremos en el corazón matemático de `IndicatorEngine.calculate()`: las fórmulas, intuiciones y limitaciones de cada indicador técnico.

---

## 1.10 Resumen del Capítulo

- Los **mercados spot** implican propiedad directa; los **perpetuos** usan margen y funding rate. Nuestro agente usa spot para crypto/oro y perpetuos solo para plata (XAG).
- **OHLCV** es la representación universal de datos de precios. Comprime tick data en velas con la información esencial: apertura, máximo, mínimo, cierre y volumen.
- La **microestructura** (order books, spread, slippage) impone costos implícitos que el agente debe considerar.
- Los **5 activos** del sistema (BTC, ETH, SOL, XAU, XAG) fueron seleccionados por liquidez, diversificación y cobertura estratégica.
- **Kraken** (primario) y **OKX** (secundario) reemplazan a Binance, bloqueado por restricción geográfica.
- `market_feed.py` implementa el patrón **cache-aside**: descarga, persiste en PostgreSQL y sirve datos normalizados al resto del sistema.
