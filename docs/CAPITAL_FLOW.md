# ARTHAS TRADING — Infraestructura Financiera y Flujo de Capital

> **Objetivo**: Definir cómo entra, se distribuye, opera y sale el capital entre los agentes.
> **Meta del consorcio**: 15% anual compuesto entre todas las líneas de negocio.
> **Jurisdicción**: Colombia — pesos colombianos (COP) como entrada/salida.
> **Última actualización**: Mayo 2026

---

## 1. Principios de seguridad financiera

### Regla #1: Custodia distribuida
Nunca más del 40% del capital total en un solo exchange o wallet. Si Kraken quiebra, si Alpaca congela, si Metamask se compromete — el resto del capital sigue intacto.

### Regla #2: Seed phrase fuera del VPS
La seed phrase de la wallet principal NUNCA se almacena en el VPS. Se guarda offline (papel, metal) en 2 ubicaciones físicas distintas. El VPS solo tiene las API keys de los exchanges (con permisos de trading, no de withdraw).

### Regla #3: Hot/Cold wallet
- **Hot wallet** (Metamask/Rabby en VPS): solo lo necesario para trading (~20% del capital). Clave privada en el VPS.
- **Cold wallet** (Ledger/Trezor o papel): el resto (~80%). Solo se toca para depositar/retirar. NUNCA conectada al VPS.
- **Exchange balances**: solo lo que los agentes necesitan operar (~5-10% cada uno).

### Regla #4: Retiros solo a direcciones whitelisteadas
En Kraken, Binance y Alpaca, configurar address whitelisting. Cualquier retiro solo puede ir a direcciones pre-aprobadas. El VPS no puede cambiar el whitelist (se hace manual desde Colombia).

### Regla #5: Prueba de retiro mensual
Una vez al mes, retirar una cantidad pequeña (~$10) de cada exchange a la wallet principal. Si el retiro falla o se demora más de 24h, investigar antes de depositar más.

---

## 2. Infraestructura de cuentas

### Cuentas bancarias (Colombia)

| Cuenta | Propósito | Institución |
|---|---|---|
| Cuenta principal COP | Recibir P2P, pagar gastos | Bancolombia / Davivienda |
| Cuenta secundaria COP | Respaldo, diversificar | Nequi / Daviplata |
| Cuenta USD (opcional) | Recibir de Alpaca, ahorro en USD | Littio / Global66 / DollarApp |

### Exchanges (trading)

| Exchange | Agentes | Capital operativo | Nivel de confianza |
|---|---|---|---|
| **Kraken** | Crypto Agent, Grid Stable, Basis Trade (futuro) | 40% | Alto (regulado USA) |
| **Binance** | On/off-ramp COP, staking pasivo | 20% (solo custodia) | Medio (problemas regulatorios) |
| **Alpaca Markets** | Stocks Agent, VIX, Pairs, Earnings | 20% | Alto (regulado USA, SIPC) |
| **Deribit** | Options Agent (theta farming) | 10% | Medio (Panamá, no regulado) |

### Wallets (crypto nativo)

| Wallet | Red | Propósito | Seguridad |
|---|---|---|---|
| **Rabby/Metamask** | Polygon | Polymarket Agent (USDC) | Software wallet en VPS — solo trading |
| **Ledger/Trezor** | Multi-chain | Cold storage (80% capital) | Hardware wallet offline |
| **Rabby/Metamask #2** | Ethereum, Polygon | Recibir ganancias, distribuir | Software wallet en máquina local (Colombia) |

---

## 3. Flujo de entrada: COP → Agentes

### Ruta 1: P2P → Binance → Exchanges (recomendada)

```
Paso 1: COP → USDT (Binance P2P)
  En Binance app: P2P Trading → Buy USDT
  Filtrar por: vendedor verificado, +95% completion, +500 trades
  Pagar con: transferencia Bancolombia/Nequi/Daviplata
  Fee: 0% (el spread del vendedor es ~1-2% sobre TRM)
  Tiempo: 5-15 minutos
  Límite diario: ~$2,000 USD (varía por cuenta)

Paso 2: USDT en Binance → distribuir a exchanges
  ┌─────────────────────────────────────────────────────────┐
  │ Desde Binance (Withdraw → USDT)                         │
  │                                                         │
  │ ├── Kraken (Funding → Deposit → USDT)                  │
  │ │   Network: TRC20 (Tron)                               │
  │ │   Fee: ~$1 USD                                        │
  │ │   Tiempo: 2-5 min                                     │
  │ │   Dirección: obtener en Kraken → Funding              │
  │ │                                                       │
  │ ├── Wallet Polygon (para Polymarket)                   │
  │ │   Network: Polygon                                    │
  │ │   Asset: USDC (no USDT — Polymarket usa USDC)        │
  │ │   Fee: ~$0.10                                         │
  │ │   Tiempo: 1-2 min                                     │
  │ │   Dirección: tu wallet Metamask/Rabby en Polygon      │
  │ │                                                       │
  │ └── Wallet Ethereum (para Deribit, opcional)           │
  │     Network: ERC20 o Arbitrum                           │
  │     Asset: USDC o ETH                                   │
  │     Fee: ~$3-8 (ERC20 caro) o ~$0.50 (Arbitrum)        │
  └─────────────────────────────────────────────────────────┘

Paso 3: Wallet → Polymarket
  En Metamask/Rabby (Polygon network):
  Conectar a polymarket.com → Deposit → aprobar USDC
  Gas fee: ~$0.01 MATIC
  Tiempo: 1 min

Paso 4: Wallet → Alpaca (USD fiat, opción futura)
  Desde Littio/Global66: ACH transfer a Alpaca
  Tiempo: 1-2 días hábiles
  Fee: $0-5
```

### Ruta 2: Crypto.com / Exchange con tarjeta

```
COP → comprar crypto en exchange local (Buda, Bitso)
    → enviar a Kraken/Alpaca/Deribit
    → gastar ganancias con tarjeta de débito crypto
```

### Cuánto capital en cada lugar

| Agente | Capital mínimo | Capital objetivo | Exchange/Wallet | Red |
|---|---|---|---|---|
| **Crypto Agent** | $100 | $500+ | Kraken | USDT spot |
| **Grid Stable** | $50 | $200 | Kraken | ETH/BTC spot |
| **Polymarket** | $80 | $200 | Polygon wallet → Polymarket | USDC |
| **Stocks Agent** | $220 | $500+ | Alpaca | USD fiat |
| **Options Agent** | — (pausado) | $500+ | Deribit | BTC o USDC |
| **Basis Trade** (futuro) | $100 | $300 | Kraken | USDT spot + futures |
| **VIX/Pairs/Earnings** | $100 c/u | $300 c/u | Alpaca | USD fiat |
| **Reserva cold wallet** | 20% del total | Siempre | Ledger/Trezor | USDC/BTC |

---

## 4. Flujo de salida: Agentes → COP (recuperar capital)

### Escenario A: Retiro programado (normal)

```
Paso 1: Consolidar ganancias en exchange principal
  Kraken: USDT → Binance (TRC20, ~$1)
  Polymarket: USDC → Binance (Polygon, ~$0.10)
  Alpaca: USD → Littio → Binance (comprar USDT)

Paso 2: USDT en Binance → COP
  Binance P2P → Sell USDT
  Filtrar comprador verificado
  Recibir: transferencia a Bancolombia/Nequi
  Fee: 0% (spread ~1-2%)
  Tiempo: 5-15 min
  Límite: ~$5,000/día (varía)

Paso 3: COP en cuenta bancaria → disponible
```

### Escenario B: Emergencia — recuperar TODO el capital

Si necesitás sacar todo el capital de golpe (problema legal, personal, mercado):

```
⚠️ ORDEN DE PRIORIDAD (más rápido a más lento):

1. Kraken → Binance → P2P → COP
   Tiempo: 30 min
   Retirar todo el USDT/BTC disponible

2. Polymarket → Wallet Polygon → Binance → P2P → COP
   Tiempo: 1 hora
   Cerrar todas las posiciones abiertas primero
   Retirar USDC a wallet → bridge a Binance

3. Alpaca → Littio/Global66 → Binance → P2P → COP
   Tiempo: 3-5 días hábiles
   Vender todas las posiciones (market order)
   Esperar T+2 settlement
   ACH transfer a Littio
   Convertir USD a USDT → P2P a COP

4. Deribit → Kraken/Binance → P2P → COP
   Tiempo: 1-2 horas
   Cerrar opciones, retirar BTC

5. Cold wallet (Ledger) → Binance → P2P → COP
   Tiempo: 1-2 horas
   Solo si los exchanges fallan
```

### Escenario C: Exchange caído o hackeado

```
Si Kraken cae (ej: quiebra FTX-style):
  → El capital en Kraken está en riesgo
  → Activar cold wallet para seguir operando
  → Migrar Crypto Agent a OKX (ya tenés fallback configurado)
  → Iniciar proceso de reclaim con Kraken (largo, incierto)

Si Alpaca falla:
  → Capital en Alpaca está asegurado por SIPC hasta $500K
  → Migrar a Interactive Brokers o TradeStation
  → Los stocks se transfieren, no se pierden

Si Binance falla:
  → Solo afecta on/off-ramp, no el trading
  → Usar Kraken para withdraw directo a wallet
  → On/off-ramp alternativo: Bitso, Buda, Littio

Si Polymarket falla:
  → Los fondos están en la wallet Polygon, no en Polymarket
  → Siempre podés retirar USDC de Polygon aunque Polymarket caiga
```

---

## 5. Automatización de flujos (cuando escale)

### Rebalanceo automático mensual

Cuando el capital total supere ~$2,000, implementar un script de rebalanceo:

```
Cada 1er día del mes:
  1. Consultar balance en Kraken, Alpaca, Polymarket, Deribit
  2. Calcular profit de cada agente
  3. Si algún agente excede 1.5× su capital objetivo:
     → Retirar excedente a wallet central
  4. Si algún agente está por debajo de su capital mínimo:
     → Depositar desde wallet central
  5. Reporte Telegram con distribución actual
```

Este script corre MANUAL (no automático) — requiere confirmación tuya.

---

## 6. Proyección de crecimiento

### Con 15% anual compuesto

| Año | Capital inicial | Capital final | Distribución sugerida |
|---|---|---|---|
| 1 | $300 | $345 | Todo en Crypto Agent (concentrado) |
| 2 | $345 | $1,000 | Crypto 50%, Stocks 25%, Poly 15%, Grid 10% |
| 3 | $1,000 | $2,500 | Agregar Basis Trade y VIX |
| 4 | $2,500 | $7,000+ | Activar todos los agentes. Cold wallet 20% |

### Gatillos para rondas de inversión

- **Ronda 1 ($5K-$10K)**: 12 meses track record con PF≥1.3 en 3 agentes. Dashboard público. Capital de amigos/familia.
- **Ronda 2 ($50K-$100K)**: 24 meses track record. Auditoría externa. Inversores ángel.
- **No antes de**: tener cold wallet, multisig, y estructura legal (SAS en Colombia o LLC en USA).

---

## 7. Checklist de seguridad — Antes de fondear

Antes de pasar de paper a live con cualquier agente:

- [ ] Whitelist de direcciones de retiro activado en Kraken
- [ ] 2FA (no SMS, sí authenticator app) en TODOS los exchanges
- [ ] API keys con permisos RESTRINGIDOS (trading sí, withdraw NO)
- [ ] Seed phrase de cold wallet guardada en 2 ubicaciones físicas
- [ ] Prueba de depósito/retiro con $10 completada
- [ ] Capital en exchanges ≤ 80% del total (20% en cold wallet)
- [ ] Límites de pérdida diaria configurados
- [ ] Telegram alertas funcionando (health check cada 3h)
- [ ] Plan de emergencia impreso (este documento, sección 4)

---

## 8. Resumen visual del flujo

```
                      COLOMBIA (COP)
                           │
                    ┌──────┴──────┐
                    │  Binance P2P │  ← On/off-ramp
                    └──────┬──────┘
                           │ USDT
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         ┌────────┐  ┌─────────┐  ┌──────────┐
         │ Kraken │  │ Polygon │  │  Ledger   │
         │ 40%    │  │ Wallet  │  │  (cold)   │
         │────────│  │ 15%     │  │  20%      │
         │ Crypto │  │─────────│  │──────────│
         │ Grid   │  │ Poly    │  │ Reserva  │
         │ Basis  │  │ market  │  │ estratég.│
         └────────┘  └─────────┘  └──────────┘
                           │
              ┌────────────┤
              ▼            ▼
         ┌────────┐  ┌──────────┐
         │ Alpaca │  │ Deribit  │
         │ 20%    │  │ 5%       │
         │────────│  │──────────│
         │ Stocks │  │ Options  │
         │ VIX    │  │ (pausado)│
         │ Pairs  │  └──────────┘
         │ Earn.  │
         └────────┘

GANANCIAS → Binance P2P → COP → Bancolombia/Nequi
           (ruta inversa, misma infraestructura)
```

---

## 9. Contactos de emergencia

| Recurso | Contacto/URL |
|---|---|
| Kraken Support | support.kraken.com |
| Alpaca Support | alpaca.markets/support |
| Binance P2P Appeal | binance.com/es/peer-to-peer |
| Polymarket Discord | discord.gg/polymarket |
| Cambio P2P alternativo | Buda.com, Bitso.com (Colombia) |
| Cuenta USD sin banco | Littio.app, Global66.com |

---

*Este documento debe imprimirse y guardarse offline. Es el manual de recuperación de capital.*
