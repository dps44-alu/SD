# Estado del Proyecto — EVCharging Network

## Arquitectura

| Componente | Tecnología | Puerto(s) | Descripción |
|---|---|---|---|
| EV_Registry | Flask HTTPS | 5001 | Registro de CPs, genera credenciales |
| EV_Central | TCP + Flask + Kafka + Tkinter | 5000 (TCP) / 8000 (REST) | Controlador central, panel visual |
| EV_CP_E (Engine) | TCP + Kafka | 6000 | Motor del punto de carga |
| EV_CP_M (Monitor) | TCP | — | Proxy Central↔Engine, muestra estado |
| EV_Driver | Kafka | — | Cliente conductor, solicita cargas |
| EV_W | REST (cliente) | — | Servicio meteorológico, empuja datos a Central |
| Front | HTML/JS estático | — | Panel web, consume API REST de Central |

**Tópicos Kafka:** `peticiones_conductores`, `peticiones_carga`, `consumo_cps`, `respuestas_central`

**Base de datos compartida:** `db.json` (Registry + Central)  
**Credenciales:** `credentials.json` (Registry) + `creds_<CP_ID>.json` (Monitor local)  
**Log de auditoría:** `audit.log` (generado por Central)  
**Config EV_W:** `ev_w_config.json` (API key OpenWeather)

---

## Estado de implementación

### Funcionalidad base (Release 1)
| Función | Estado |
|---|---|
| Parámetros por línea de comandos (todos los módulos) | ✅ |
| Registro de CPs en Registry (HTTPS + credenciales) | ✅ |
| Autenticación CP en Central (aceptar / rechazar) | ✅ |
| Cifrado Fernet en mensajes Kafka CP→Central | ✅ |
| Flujo completo de carga: REQUEST → BUSY → TICKET | ✅ |
| STOP / RESUME desde menú de Central | ✅ |
| Carga manual desde Monitor | ✅ |
| Carga desde archivo (EV_Driver opción 3) | ✅ |
| Log de auditoría (`audit.log`) | ✅ |
| Revocación de clave desde menú Central (opción 7) | ✅ |

### Panel Tkinter (EV_Central)
| Elemento | Estado |
|---|---|
| Tiles CP con colores por estado | ✅ |
| ACTIVE = verde / BUSY = azul / OUT_OF_ORDER = naranja / BROKEN = rojo / DESCONECTADO = gris | ✅ |
| Sección ON GOING DRIVERS REQUESTS (conductor, CP, inicio, kWh, €) | ✅ |
| Sección APPLICATION MESSAGES con colores por tipo y scrollbar | ✅ |

### Resiliencia (Release 1)
| Escenario | Estado |
|---|---|
| Monitor cae → panel muestra DESCONECTADO | ✅ |
| Monitor cae → Central bloquea nuevas cargas (INACTIVE en db) | ✅ |
| Monitor cae durante carga → carga termina, CP queda INACTIVE al final | ✅ |
| Engine cae → Monitor notifica OUT_OF_ORDER a Central | ✅ |
| Central cae → Driver recibe aviso; carga continúa; ticket al reconectar | ✅ |
| Central cae → Monitor reconecta automáticamente al volver | ✅ |
| Driver cae → carga continúa, Driver recibe TICKET al reconectar | ✅ |
| Monitor arranca con puerto TCP incorrecto → aborta con error | ✅ |

### Release 2 — EV_W
| Función | Estado |
|---|---|
| API key de OpenWeather en archivo `ev_w_config.json` | ✅ |
| API key pedida por consola si no existe el archivo | ✅ |
| Cambio de API key en caliente (opción 4 del menú) | ✅ |
| IP y puerto de Central parametrizables por CLI (`<CENTRAL_IP> <CENTRAL_PORT>`) | ✅ |
| Verificación al arranque de que el puerto apunta al API REST (no al TCP) | ✅ |
| Localizaciones cargadas desde `locations.txt` al arrancar | ✅ |
| Localizaciones añadidas / cambiadas en caliente (opción 1, sin reiniciar) | ✅ |
| Temperatura enviada a Central (`POST /weather/data`) cada 4 segundos | ✅ |
| Alerta climática (temp < 0°C) → CP pasa a OUT_OF_ORDER | ✅ |
| Cancelación de alerta (temp ≥ 0°C) → CP vuelve a ACTIVE | ✅ |

### Release 2 — Front web
| Función | Estado |
|---|---|
| URL del API de Central parametrizable (`?api=http://...`) | ✅ |
| Tabla Charging Points: ID, dirección, precio, estado, conductor, kWh, €, Online/Offline, ciudad, temp | ✅ |
| Sección On Going Drivers Requests | ✅ |
| Sección Weather / Climate Status | ✅ |
| Sección Application Messages | ✅ |
| Temperatura muestra "—" si EV_W lleva más de 8s sin actualizar | ✅ |
| Banner de error si Central no responde | ✅ |
| Múltiples navegadores simultáneos (polling cada 2s, sin estado) | ✅ |

### Release 2 — Re-autenticación tras revocación de clave
| Función | Estado |
|---|---|
| Central envía `KEY_REVOKED` al Monitor via TCP al revocar | ✅ |
| Monitor muestra aviso de clave revocada en su menú | ✅ |
| Monitor opción 4: re-autenticarse con Central sin reiniciar | ✅ |
| Central genera nueva clave Fernet y la distribuye al reconectar | ✅ |
| Engine recibe la nueva clave; cifrado restaurado | ✅ |

### Release 2 — API REST de Central
| Endpoint | Estado |
|---|---|
| `GET  /api/charging_points` | ✅ |
| `GET  /api/charging_points/<id>` | ✅ |
| `GET  /api/active_drivers` | ✅ |
| `GET  /api/weather` | ✅ |
| `GET  /api/system/status` | ✅ |
| `GET  /api/messages` | ✅ |
| `GET  /api/health` | ✅ |
| `POST /weather/alert` | ✅ |
| `POST /weather/data` | ✅ |

---

## Estado de pruebas (Release 2)

| Prueba | Descripción | Estado |
|---|---|---|
| Prueba 1 | Parametrización (API key, URL Central, URL front) | ✅ Pasada |
| Prueba 2 | Front: múltiples navegadores, estado completo | ✅ Pasada |
| Prueba 3 | Front: resiliencia (Central caída, EV_W caído) | ✅ Pasada |
| Prueba 4 | EV_W: alertas climáticas y cambio de localización en caliente | ✅ Pasada |
| Prueba 5 | Seguridad: Registry HTTPS | ✅ Pasada |
| Prueba 6 | Seguridad: cifrado Kafka y revocación de claves | ✅ Pasada |
| Prueba 7 | Log de auditoría | ✅ Pasada |
| Prueba 8 | Resiliencia general (criterios Release 1 con sistema Release 2) | ✅ Pasada |

---

## Tabla de estados del CP

| Monitor | Engine | Estado en panel | Color |
|---|---|---|---|
| OK | OK | ACTIVE / BUSY | Verde / Azul |
| OK | KO (caído) | OUT_OF_ORDER | Naranja |
| KO (caído) | OK | DESCONECTADO | Gris |
| KO (caído) | KO (caído) | DESCONECTADO | Gris |
| CP parado por Central | — | BROKEN | Rojo |

---

## Parámetros de arranque

```
EV_Registry.py
  (sin parámetros — escucha en 0.0.0.0:5001 HTTPS)

EV_Central.py  [CENTRAL_PORT]  [BROKER_IP]  [BROKER_PORT]
  defecto:      5000             localhost     9092
  (el API REST siempre arranca en el puerto 8000)

EV_CP_E.py     [BROKER_IP]  [BROKER_PORT]  [ENGINE_PORT]
  defecto:      localhost     9092           6000

EV_CP_M.py     [ENGINE_IP]  [ENGINE_PORT]  [CENTRAL_IP]  [CENTRAL_PORT]  [CP_ID]  [REGISTRY_IP]  [REGISTRY_PORT]
  defecto:      localhost     6000           localhost      5000            ALC1     localhost       5001

EV_Driver.py   [BROKER_IP]  [BROKER_PORT]  [DRIVER_ID]
  defecto:      localhost     9092           Driver1

EV_W.py        [CENTRAL_IP]  [CENTRAL_API_PORT]
  defecto:      localhost      8000
  (CENTRAL_API_PORT = puerto REST de Central, siempre 8000; NO el puerto TCP 5000)

Front:
  front.html                              (conecta a http://localhost:8000 por defecto)
  front.html?api=http://<IP>:8000         (despliegue distribuido)
```

---

## Despliegue distribuido (3 máquinas)

| Máquina | Componentes |
|---|---|
| PC1 | Kafka + EV_Central + Front (front.html) |
| PC2 | EV_CP_E + EV_CP_M + EV_W |
| PC3 | EV_Driver + EV_Registry |

```bash
# PC1 (192.168.1.10):
python3 EV_Central.py 5000 192.168.1.10 9092

# PC2 (192.168.1.20):
python3 EV_CP_E.py 192.168.1.10 9092 6000
python3 EV_CP_M.py localhost 6000 192.168.1.10 5000 ALC1 192.168.1.30 5001
python3 EV_W.py 192.168.1.10 8000

# PC3 (192.168.1.30):
python3 EV_Driver.py 192.168.1.10 9092 Driver1
python3 EV_Registry.py

# Front (cualquier navegador):
front.html?api=http://192.168.1.10:8000
```
