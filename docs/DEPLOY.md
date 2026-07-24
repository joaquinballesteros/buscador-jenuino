# Desplegar en un servidor propio

Documento para poner el buscador en un VPS/servidor Linux propio, accesible
por dominio y HTTPS. Para desarrollo local, ver el [README](../README.md).

## Qué necesita el servidor

- **Linux con systemd** (Ubuntu/Debian, Rocky/Alma... cualquiera sirve; los
  ejemplos usan `apt`, adáptalos si es otra distro).
- **Python 3.11+**.
- **Ollama**, si vas a servir búsquedas con embeddings locales (el valor por
  defecto de `config.json` → `providers.embeddings.provider`). Importante:
  aunque el LLM (`providers.llm`) sea una API externa, **los embeddings se
  invocan en cada búsqueda** para vectorizar la consulta — si son locales,
  Ollama tiene que estar corriendo en el propio servidor.
- Un dominio apuntando a la IP del servidor, si quieres HTTPS con nombre
  propio (Caddy/certbot lo gestionan solos, pero necesitan el DNS ya
  resuelto).

El grafo y el índice vectorial de los artículos ya existentes **se versionan
en el repo** (`data/`, `rag_storage/`): desplegar no exige reconstruir nada,
solo clonar, instalar dependencias y arrancar.

## 1. Preparar el servidor

```bash
sudo apt update && sudo apt install -y python3-venv git

# Ollama (omite este bloque si usas embeddings por API en config.json)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull bge-m3
```

El instalador de Ollama ya deja un servicio systemd propio (`ollama.service`)
arrancando en el boot; compruébalo con `systemctl status ollama`.

Crea un usuario de sistema para no correr la app como root:

```bash
sudo useradd --system --create-home --shell /usr/sbin/nologin jenui
```

## 2. Clonar y preparar el proyecto

```bash
sudo -u jenui -H bash -c '
  cd /home/jenui
  git clone https://github.com/joaquinballesteros/buscador-jenuino.git
  cd buscador-jenuino
  python3 -m venv .venv
  .venv/bin/pip install -r requirements.txt
'
```

Si usas un proveedor de LLM o embeddings por API (`config.json` →
`providers`), crea `.env` con la clave — **no se versiona**:

```bash
sudo -u jenui bash -c 'cat > /home/jenui/buscador-jenuino/.env' <<'EOF'
OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=sk-ant-...
EOF
```

Arranque de prueba, sin systemd todavía, para comprobar que carga bien:

```bash
sudo -u jenui -H /home/jenui/buscador-jenuino/scripts/run.sh
# Ctrl-C para pararlo en cuanto veas "Uvicorn running on http://127.0.0.1:8000"
```

> El PDF de cada resultado enlaza directo a aenui.org, así que **no hace
> falta** descargar `pdf/`/`fichas/` para servir búsquedas. Solo son
> necesarias si vas a reconstruir el índice desde cero (ver README).

## 3. Servicio systemd

`scripts/run.sh`/`stop.sh` están pensados para uso manual (matan el proceso
por puerto/nombre con `lsof`/`pgrep`), no para que los gestione systemd a la
vez — si systemd te reinicia el proceso automáticamente y `stop.sh` lo mata
por fuera, se pelean entre sí. Para producción, systemd invoca `server.py`
directamente y **no uses `stop.sh`/`restart.sh`**: usa `systemctl`.

`/etc/systemd/system/jenui.service`:

```ini
[Unit]
Description=Buscador JENUINO
After=network.target ollama.service

[Service]
Type=simple
User=jenui
WorkingDirectory=/home/jenui/buscador-jenuino
ExecStart=/home/jenui/buscador-jenuino/.venv/bin/python scripts/server.py
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now jenui
sudo systemctl status jenui
journalctl -u jenui -f          # logs en vivo
```

El servidor escucha en `127.0.0.1:8000` (fijo en `scripts/server.py`): nunca
queda expuesto directamente a internet, lo expone el reverse proxy del
siguiente paso.

## 4. Reverse proxy + HTTPS

### Opción recomendada: Caddy

Caddy gestiona el certificado HTTPS (Let's Encrypt) solo, sin configuración
extra. Instalación y `/etc/caddy/Caddyfile`:

```bash
sudo apt install -y caddy
```

```caddyfile
buscador.tudominio.es {
	reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo systemctl reload caddy
```

Con el DNS ya apuntando al servidor, en unos segundos tienes HTTPS con
renovación automática.

### Alternativa: nginx + certbot

```nginx
server {
    listen 80;
    server_name buscador.tudominio.es;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

```bash
sudo certbot --nginx -d buscador.tudominio.es
```

## 5. Firewall

Solo 80/443 (y SSH) deben estar abiertos al exterior; el 8000 se queda en
localhost:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp
sudo ufw enable
```

## Actualizar

```bash
sudo -u jenui -H bash -c '
  cd /home/jenui/buscador-jenuino
  git pull
  .venv/bin/pip install -r requirements.txt   # por si cambiaron dependencias
'
sudo systemctl restart jenui
```

Un `git pull` que traiga **artículos nuevos** (corpus, índice, grafo
actualizados) no necesita reiniciar: el servidor detecta los ficheros
cambiados y recarga solo (ver [ARCHITECTURE.md § Recarga en
caliente](ARCHITECTURE.md#7-recarga-en-caliente)). El reinicio solo hace
falta si cambió `config.json`, que se lee al arrancar.

## Comprobar el estado

```bash
curl -s https://buscador.tudominio.es/api/status | python3 -m json.tool
sudo -u jenui /home/jenui/buscador-jenuino/.venv/bin/python \
     /home/jenui/buscador-jenuino/scripts/status.py
```

## Notas

- **Sin autenticación propia.** La app no tiene login ni control de acceso;
  es un buscador sobre contenido público (actas de JENUI). Si necesitas
  restringir el acceso, hazlo en el reverse proxy (auth básica en Caddy/nginx,
  o una VPN/IP allowlist delante).
- **Un solo proceso.** `Searcher` carga el corpus, el índice y el grafo
  enteros en memoria; no hay necesidad ni beneficio en varios workers de
  uvicorn para este volumen de datos y de tráfico esperado (búsqueda
  personal/departamental, no un servicio masivo).
- **CORS.** No hay cabeceras CORS configuradas: la interfaz web funciona
  porque la sirve la propia app (mismo origen). Si quieres consumir
  `/api/search` desde otro dominio (una web distinta que llame por
  `fetch`), añade `CORSMiddleware` en `jenui/web/app.py`.
