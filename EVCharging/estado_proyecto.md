# Estado del Proyecto — EVCharging Network

## Arquitectura

| Componente | Tecnología | Puerto(s) | Descripción |
|---|---|---|---|
| EV_Registry | Flask HTTPS | 5001 | Registro de CPs, genera credenciales |
| EV_Central | TCP + Flask + Kafka | 5000 (TCP) / 8000 (REST) | Controlador central, panel Tkinter |
| EV_CP_E (Engine) | TCP + Kafka | 6000 | Motor del punto de carga, gestiona la carga física |
| EV_CP_M (Monitor) | TCP | — | Proxy entre Central↔Engine, muestra estado |
| EV_Driver | Kafka | — | Cliente conductor, solicita cargas |
| EV_W | Flask + REST | — | Servicio meteorológico |

**Tópicos Kafka:** `peticiones_conductores`, `peticiones_carga`, `consumo_cps`, `respuestas_central`

**Base de datos compartida:** `db.json` (Registry + Central)  
**Credenciales:** `credentials.json` (Registry) + `creds_<CP_ID>.json` (Monitor local)  
**Log de auditoría:** `audit.log` (generado por Central)

---

## Estado de implementación

### Funcionalidad base
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
| Archivo `cargas.txt` con 12 entradas | ✅ |
| Log de auditoría (`audit.log`) | ✅ |
| Revocación de clave desde menú Central (opción 7) | ✅ |

### Panel Tkinter (EV_Central)
| Elemento | Estado |
|---|---|
| Tiles CP con colores por estado | ✅ |
| ACTIVE = verde oscuro / BUSY = azul / OUT_OF_ORDER = naranja / BROKEN = rojo / DESCONECTADO = gris | ✅ |
| Tiles de igual tamaño (columnas con peso uniforme) | ✅ |
| CPs ordenados alfabéticamente por ID | ✅ |
| Sección ON GOING DRIVERS REQUESTS (conductor, CP, inicio, kWh, €) | ✅ |
| Sección APPLICATION MESSAGES con colores por tipo y scrollbar | ✅ |

### Resiliencia
| Escenario | Estado |
|---|---|
| Monitor cae → panel muestra DESCONECTADO | ✅ |
| Monitor cae → Central bloquea nuevas cargas (INACTIVE en db) | ✅ (Bug 1 corregido) |
| Monitor cae durante carga → carga termina, CP queda INACTIVE al final | ✅ (Bug 1 corregido) |
| Engine cae → Monitor notifica OUT_OF_ORDER a Central | ✅ (Bug 2 corregido) |
| Central cae → Monitor reconecta automáticamente al volver | ✅ (Bug 4 corregido) |
| Driver cae → carga continúa, Driver recibe TICKET al reconectar | ✅ |
| URL del Registry parametrizada (args 6 y 7 del Monitor) | ✅ (Bug 3 corregido) |

---

## Tabla de estados del CP (según guía de corrección)

| Monitor | Engine | Estado en panel | Color |
|---|---|---|---|
| OK | OK | ACTIVE / BUSY | Verde / Azul |
| OK | KO (caído) | OUT_OF_ORDER | Naranja |
| KO (caído) | OK | DESCONECTADO | Gris |
| KO (caído) | KO (caído) | DESCONECTADO | Gris |

---

## Parámetros de arranque

```
# Cada módulo acepta parámetros posicionales; sin parámetros usa los valores por defecto

EV_Registry.py
  (sin parámetros — escucha en 0.0.0.0:5001 HTTPS)

EV_Central.py  [CENTRAL_PORT]  [BROKER_IP]  [BROKER_PORT]
  defecto:      5000             localhost     9092

EV_CP_E.py     [BROKER_IP]  [BROKER_PORT]
  defecto:      localhost     9092

EV_CP_M.py     [ENGINE_IP]  [ENGINE_PORT]  [CENTRAL_IP]  [CENTRAL_PORT]  [CP_ID]  [REGISTRY_IP]  [REGISTRY_PORT]
  defecto:      localhost     6000           localhost      5000            ALC1     localhost       5001

EV_Driver.py   [BROKER_IP]  [BROKER_PORT]  [DRIVER_ID]
  defecto:      localhost     9092           Driver1
```

---

## Despliegue distribuido (3 máquinas)

| Máquina | Componentes |
|---|---|
| PC1 | Kafka + EV_Central + Front (front.html) |
| PC2 | EV_CP_E + EV_CP_M + EV_W |
| PC3 | EV_Driver + EV_Registry |

Sustituir `localhost` por la IP real de cada máquina en los parámetros.

---

## Pendiente (Release 2 — no iniciada)

- Front web: sección Drivers activos
- EV_W: datos de temperatura reales en el panel
- Re-autenticación del CP tras revocación de clave sin reinicio
