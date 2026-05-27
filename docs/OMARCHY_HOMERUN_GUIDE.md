# Omarchy + Homerun — Guía de instalación

> **Objetivo**: Convertir tu PC vieja (i7 7th gen, 16GB RAM) en un laboratorio
> de prediction markets corriendo Homerun 24/7 sobre Omarchy Linux.

---

## 1. Qué es Omarchy

Omarchy es un Linux basado en Arch, creado por DHH (Basecamp/37signals/Rails).
Viene con todo preinstalado para desarrollo: Neovim, Docker, Chromium, OpenCode.

**Características clave para nosotros:**
- **OpenCode** preinstalado — la misma IA que usamos ahora
- **Docker** listo para Homerun
- **Lazydocker** — TUI para gestionar contenedores sin terminal
- **SSH server** — accedé remotamente desde el VPS
- **Hyprland** — todo se maneja con teclado (como un power user)
- **Actualizaciones con un click** desde el menú Omarchy

**Precaución**: Omarchy formatea el disco completo. Hacé backup de lo que necesites.

---

## 2. Instalación de Omarchy

### Requisitos
- USB stick de 8GB+
- PC con Secure Boot DESACTIVADO en BIOS
- Disco dedicado (Omarchy borra todo)
- Internet por cable (más fácil que WiFi durante la instalación)

### Paso a paso

**1. Descargar la ISO**
```bash
# Desde cualquier computadora:
wget https://iso.omarchy.org/omarchy-3.8.0.iso
```

**2. Crear USB booteable**
- Windows/Mac: [balenaEtcher](https://etcher.balena.io/)
- Linux: `sudo dd if=omarchy-3.8.0.iso of=/dev/sdX bs=4M status=progress`

**3. Bootear del USB**
- Reiniciá la PC, entrá al BIOS (F2/F12/DEL)
- Desactivá Secure Boot y TPM
- Seleccioná boot desde USB

**4. Instalación**
- El instalador hace preguntas (idioma, teclado, usuario, contraseña)
- Seleccioná el disco → confirmá
- La instalación tarda ~10 minutos
- Al reiniciar, ya tenés Omarchy

**5. Primeros pasos**
```
Super + Space         → lanzador de aplicaciones
Super + Return        → terminal (Alacritty)
Super + Shift + Return → navegador (Chromium)
Super + Alt + Space   → menú Omarchy (instalar paquetes, updates, temas)
Super + K             → ver todos los atajos de teclado
Super + Ctrl + Shift + Space → cambiar tema (19 temas incluidos)
```

---

## 3. Instalar Homerun en Omarchy

```bash
# 1. Abrir terminal (Super + Return)

# 2. Instalar git (viene preinstalado, pero por las dudas)
omarchy pkg add git

# 3. Clonar Homerun
cd ~
git clone https://github.com/braedonsaunders/homerun.git
cd homerun

# 4. Crear archivo .env
cat > .env << 'EOF'
APP_SECRETS_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
FRONTEND_PORT=3000
BACKEND_PORT=8001

POSTGRES_USER=homerun
POSTGRES_PASSWORD=homerun_lab_2026
POSTGRES_DB=homerun

# Shadow mode — sin API keys reales
POLYMARKET_PRIVATE_KEY=
POLYMARKET_API_KEY=
POLYMARKET_API_SECRET=
POLYMARKET_API_PASSPHRASE=

# LLM (opcional — usa tu DeepSeek key)
DEEPSEEK_API_KEY=
EOF

# 5. Arrancar Homerun
docker compose up -d

# 6. Verificar que está corriendo
docker compose ps
curl -s -o /dev/null -w "Dashboard: HTTP %{http_code}\n" http://localhost:3000
```

---

## 4. Acceder remotamente (desde fuera de casa)

### Opción A — Tailscale (recomendado, más fácil)
```bash
# En Omarchy:
omarchy pkg add tailscale
sudo systemctl enable --now tailscaled
tailscale up

# En el VPS:
tailscale up

# Ya podés acceder desde el VPS a:
# http://<ip-tailscale-pc>:3000
```

### Opción B — SSH tunnel
```bash
# Desde el VPS, creás un túnel:
ssh -L 3001:localhost:3000 usuario@<ip-local-pc>
# Dashboard accesible en http://localhost:3001
```

### Opción C — IP pública + port forwarding
- En el router de tu casa, forwardeá puerto 3000 a la IP de la PC
- Accedé via `http://<tu-ip-publica>:3000`
- ⚠️ Sin autenticación — solo en red local o con VPN

---

## 5. Mantenimiento

```bash
# Actualizar Omarchy y paquetes (hacer 1 vez por semana):
Super + Alt + Space → Update → Omarchy

# Ver estado de Homerun:
cd ~/homerun && docker compose ps

# Reiniciar Homerun tras updates:
cd ~/homerun && docker compose down && docker compose up -d

# Monitorear recursos (TUI):
Super + Shift + D   → Lazydocker (contenedores)
btop                → recursos del sistema (CPU, RAM, red)

# Ver logs de Homerun:
cd ~/homerun && docker compose logs -f --tail 50
```

---

## 6. Comandos rápidos (chuleta)

| Tecla | Acción |
|---|---|
| `Super + Space` | Lanzador de apps |
| `Super + Return` | Terminal |
| `Super + Shift + Return` | Navegador |
| `Super + Alt + Space` | Menú Omarchy |
| `Super + Escape` | Menú sistema (suspender, reiniciar) |
| `Super + Ctrl + L` | Bloquear pantalla |
| `Super + K` | Todos los atajos |
| `Super + J` | Cambiar ventanas horizontal/vertical |
| `Super + T` | Toggle ventana flotante |
| `Super + W` | Cerrar ventana |
| `Super + Ctrl + Alt + T` | Fecha y hora |
| `Super + Ctrl + Shift + Space` | Cambiar tema |
| `Super + Shift + D` | Lazydocker |
| `Super + Ctrl + Space` | Cambiar fondo de pantalla |

---

## 7. Troubleshooting

**Docker no arranca**:
```bash
sudo systemctl enable --now docker
sudo usermod -aG docker $USER  # cerrar sesión y volver a entrar
```

**Homerun no responde en :3000**:
```bash
cd ~/homerun && docker compose logs backend --tail 30
```

**Mucho consumo de CPU/RAM**:
```bash
docker stats --no-stream
# Si algún contenedor consume >100% CPU:
docker restart <nombre-contenedor>
```

**La PC se apagó y Homerun no arrancó solo**:
```bash
cd ~/homerun && docker compose up -d
# Para que arranque automático al prender:
sudo systemctl enable docker
docker compose up -d  # los contenedores con restart: unless-stopped ya se auto-inician
```

---

> **Nota**: Esta guía asume Omarchy 3.8. Si instalás una versión más nueva, 
> los comandos deberían ser compatibles. Las actualizaciones de Omarchy son 
> rolling release — mantenelo actualizado semanalmente.
