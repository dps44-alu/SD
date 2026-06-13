# Guía de Ejecución — EVCharging Network

## Requisitos previos

### Python (paquetes)
```bash
pip install kafka-python cryptography flask flask-cors requests urllib3
```

### Docker (para Kafka + Zookeeper)
```bash
docker compose up -d
```
> El `docker-compose.yml` levanta Zookeeper en el puerto **2181** y Kafka en el **9092**.  
> Espera ~10 segundos antes de arrancar los módulos Python.

---

## Archivos de configuración

| Archivo | Propósito | Se crea automáticamente |
|---|---|---|
| `db.json` | Estado de CPs y drivers | Sí (Registry/Central) |
| `credentials.json` | Credenciales generadas por Registry | Sí (Registry) |
| `creds_<CP_ID>.json` | Credenciales locales del Monitor | Sí (Monitor, 1ª vez) |
| `ev_w_config.json` | API key de OpenWeather | Sí (EV_W, 1ª vez) |
| `locations.txt` | CP → ciudad para EV_W | Manual (ver formato) |
| `cargas.txt` | Cargas en lote para EV_Driver | Manual (ver formato) |
| `audit.log` | Log de auditoría | Sí (Central) |

### `locations.txt` (formato)
```
ALC1,Alicante
ALC2,Madrid
```

### `cargas.txt` (formato — un CP_ID por línea)
```
ALC1
ALC2
ALC1
...
```

---

## Ejecución en una sola máquina (localhost)

Abrir **una terminal por módulo** en el orden indicado.

### 1 — Kafka
```bash
docker compose up -d
```

### 2 — EV_Registry
```bash
python3 EV_Registry.py
```
> Escucha en `0.0.0.0:5001` (HTTPS con certificado autofirmado).

### 3 — EV_Central
```bash
python3 EV_Central.py
# o con parámetros explícitos:
python3 EV_Central.py 5000 localhost 9092
```
> TCP en `:5000` · REST en `:8000` · Panel Tkinter en ventana aparte.

### 4 — EV_CP_E (Engine)
```bash
python3 EV_CP_E.py
# o con parámetros:
python3 EV_CP_E.py localhost 9092 6000
```

### 5 — EV_CP_M (Monitor)
```bash
python3 EV_CP_M.py
# o con parámetros:
python3 EV_CP_M.py localhost 6000 localhost 5000 ALC1 localhost 5001
```
> La primera vez pedirá **dirección** y **precio €/kWh** del CP y lo registrará en Registry.  
> Las siguientes veces usará `creds_ALC1.json` y saltará el registro.

### 6 — EV_W (opcional — meteorología)
```bash
python3 EV_W.py
# o con parámetros:
python3 EV_W.py localhost 8000
```
> La primera vez pedirá la **API key de OpenWeather** y la guardará en `ev_w_config.json`.  
> Necesita `locations.txt` en el mismo directorio con al menos una entrada.

### 7 — EV_Driver
```bash
python3 EV_Driver.py
# o con parámetros:
python3 EV_Driver.py localhost 9092 Driver1
```

### 8 — Front web (navegador)
```
Abrir front.html en el navegador
  — o bien —
front.html?api=http://localhost:8000
```

### 9 — Audit Front (navegador)
```
Abrir audit.html en el navegador
  — o bien —
audit.html?api=http://localhost:8000
```

---

## Ejecución distribuida (3 máquinas)

| Máquina | IP de ejemplo | Componentes |
|---|---|---|
| PC1 | `192.168.1.10` | Kafka + EV_Central + Fronts |
| PC2 | `192.168.1.20` | EV_CP_E + EV_CP_M + EV_W |
| PC3 | `192.168.1.30` | EV_Registry + EV_Driver |

### PC1
```bash
docker compose up -d
python3 EV_Central.py 5000 192.168.1.10 9092
```
> Editar `KAFKA_ADVERTISED_LISTENERS` en `docker-compose.yml`:  
> `PLAINTEXT://192.168.1.10:9092`

### PC2
```bash
python3 EV_CP_E.py 192.168.1.10 9092 6000
python3 EV_CP_M.py localhost 6000 192.168.1.10 5000 ALC1 192.168.1.30 5001
python3 EV_W.py 192.168.1.10 8000
```

### PC3
```bash
python3 EV_Registry.py
python3 EV_Driver.py 192.168.1.10 9092 Driver1
```

### Fronts (cualquier navegador)
```
front.html?api=http://192.168.1.10:8000
audit.html?api=http://192.168.1.10:8000
```

---

## Menús de cada módulo

### EV_Central — consola
```
1: Parar CP específico       2: Reanudar CP específico
3: Parar TODOS               4: Reanudar TODOS
5: Ver estado CPs            6: Refrescar mensajes
7: Revocar clave de un CP    8: Ver audit.log
0: Salir
```

### EV_CP_M (Monitor)
```
1: Carga manual   2: Re-registrar en Registry   3: Re-autenticar con Central   0: Salir
```

### EV_W
```
1: Añadir / cambiar localización   2: Ver estado actual   0: Salir
```

### EV_Driver
```
1: Solicitar carga manual   2: Ver CPs disponibles   3: Cargar desde archivo   0: Salir
```

---

## Escenarios de prueba habituales

### Flujo básico de carga
1. Arrancar en orden: Kafka → Registry → Central → Engine → Monitor → Driver.
2. En **EV_Driver** opción `1` → introducir `ALC1` y duración `10`.
3. Observar en el panel Tkinter cómo el CP pasa a BUSY (verde oscuro) y luego a ACTIVE.
4. El Driver recibe el TICKET con kWh y coste.

### Carga desde archivo
En **EV_Driver** opción `3` → seleccionar `cargas.txt` (12 entradas, CPs ALC1 y ALC2).

### STOP y RESUME desde Central
- Menú Central opción `1` → ID del CP → el CP pasa a BROKEN (rojo).
- Menú Central opción `2` → mismo ID → vuelve a ACTIVE (verde).

### Carga manual desde Monitor
- Monitor opción `1` → introducir conductor y duración.
- La carga se inicia directamente en el Engine sin pasar por Kafka/Driver.

### Alerta climática (EV_W)
- EV_W detecta temperatura < 0 °C y envía ALERT a Central.
- Central manda STOP al CP → pasa a OUT_OF_ORDER (naranja).
- Si el CP estaba en carga, la termina antes de parar (PENDING_WEATHER_STOP).
- Al subir la temperatura ≥ 0 °C, Central envía RESUME y el CP vuelve a ACTIVE.

### Revocación de clave
- Central opción `7` → ID del CP → clave Fernet invalidada.
- Monitor y Engine muestran banner de clave revocada.
- Monitor opción `3` → re-autenticación → nueva clave distribuida automáticamente.

### Simular caída del Engine
- En la terminal del Engine pulsar `ENTER` → CP pasa a OUT_OF_ORDER 3 s y se recupera solo.

### Resiliencia ante caída del Monitor
- Cerrar la terminal del Monitor.
- Panel Central → CP pasa a DESCONECTADO (gris).
- Las cargas en curso continúan en el Engine.
- Reiniciar Monitor → reconecta automáticamente → CP vuelve a ACTIVE.

### Resiliencia ante caída de Central
- Cerrar Central y relanzarla.
- Monitor reconecta automáticamente al detectar la caída.
- El Engine reenvía el último CHARGE_END con la nueva clave para que el Driver reciba su TICKET.

---

## Parámetros de arranque — referencia rápida

```
EV_Registry.py
  (sin parámetros — HTTPS en 0.0.0.0:5001)

EV_Central.py  [CENTRAL_PORT]  [BROKER_IP]  [BROKER_PORT]
               5000             localhost     9092

EV_CP_E.py     [BROKER_IP]  [BROKER_PORT]  [ENGINE_PORT]
               localhost     9092           6000

EV_CP_M.py     [ENGINE_IP]  [ENGINE_PORT]  [CENTRAL_IP]  [CENTRAL_PORT]  [CP_ID]  [REGISTRY_IP]  [REGISTRY_PORT]
               localhost     6000           localhost      5000            ALC1     localhost       5001

EV_Driver.py   [BROKER_IP]  [BROKER_PORT]  [DRIVER_ID]
               localhost     9092           Driver1

EV_W.py        [CENTRAL_IP]  [CENTRAL_API_PORT]
               localhost      8000
               ⚠ CENTRAL_API_PORT = puerto REST (8000), NO el TCP (5000)
```

---

## Tabla de estados del CP

| Estado | Color panel | Significado |
|---|---|---|
| ACTIVE | Verde | Listo para cargar |
| BUSY | Verde oscuro | Carga en curso |
| OUT_OF_ORDER | Naranja | Fallo temporal o alerta climática |
| BROKEN | Rojo | Detenido por comando STOP de Central |
| INACTIVE | Gris (conectado) | Monitor conectado pero CP no disponible |
| DESCONECTADO | Gris | Monitor caído |

---

## Problemas frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| `NoBrokersAvailable` al arrancar | Kafka aún no está listo | Esperar 10 s tras `docker compose up -d` |
| Monitor rechazado por Central | `credentials.json` no coincide con `creds_<ID>.json` | Borrar `creds_<ID>.json` y reiniciar Monitor para re-registrar |
| EV_W no encuentra localizaciones | `locations.txt` ausente o vacío | Crear el archivo con formato `CP_ID,Ciudad` |
| Panel Tkinter no aparece | Central arrancó sin display gráfico | Asegurarse de tener entorno de escritorio o usar `DISPLAY=:0` |
| `InsecureRequestWarning` visible | Normal — certificado autofirmado de Registry | No es un error; las advertencias están suprimidas en el código |
