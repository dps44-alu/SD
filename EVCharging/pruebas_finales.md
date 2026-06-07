# Pruebas Finales — EVCharging Network (Release 1 + 2 + 3)

## Preparación general

```bash
# Matar procesos anteriores
pkill -f "python3 EV" 2>/dev/null; sleep 1

# Limpiar estado anterior
rm -f db.json credentials.json audit.log ev_w_config.json

# Arrancar Kafka
docker compose up -d

# Arrancar módulos en este orden (una terminal por proceso):
python3 EV_Registry.py
python3 EV_Central.py
python3 EV_CP_E.py                                     # Engine ALC1
python3 EV_CP_M.py                                     # Monitor ALC1
  → presiona ENTER → opción 1 → introduce dirección y precio
python3 EV_CP_E.py localhost 9092 6001                 # Engine ALC2
python3 EV_CP_M.py localhost 6001 localhost 5000 ALC2  # Monitor ALC2
  → presiona ENTER → opción 1 → introduce dirección y precio
python3 EV_W.py                                        # pide API key la primera vez
python3 EV_Driver.py localhost 9092 Driver1
# Abrir front.html y audit.html en el navegador
```

> **Notas:**
> - EV_W conecta al puerto **8000** (API REST), NO al 5000 (TCP). Si al arrancar EV_W aparece "Error: el servidor no devuelve JSON", estás usando el puerto incorrecto.
> - El archivo `cargas.txt` (12 entradas) se usa para el flujo autónomo — es suficiente para todos los escenarios.
> - `driver1.txt` tiene solo 3 entradas; úsalo solo si quieres una prueba corta.

---

## BLOQUE 1 — Despliegue, parametrización y modularidad

### PRUEBA 1.1 — Parámetros por CLI

**Objetivo:** Confirmar que todos los módulos son parametrizables sin recompilar.

**Pasos:**
1. Lanzar Central en puerto distinto:
   ```bash
   python3 EV_Central.py 5100 localhost 9092
   ```
   **Resultado esperado:** arranca sin tocar el código; escucha en 5100.

2. Lanzar Monitor apuntando al nuevo puerto:
   ```bash
   python3 EV_CP_M.py localhost 6000 localhost 5100 ALC1
   ```
   **Resultado esperado:** Monitor se registra en Registry y autentica en Central en 5100.

3. Lanzar Driver con ID distinto:
   ```bash
   python3 EV_Driver.py localhost 9092 Driver99
   ```
   **Resultado esperado:** arranca identificado como Driver99.

4. Lanzar EV_W apuntando a Central en IP/puerto distinto:
   ```bash
   python3 EV_W.py localhost 8000
   ```
   **Resultado esperado:** conecta correctamente; log muestra "API Central verificada".

5. Abrir front con URL parametrizada:
   ```
   front.html?api=http://localhost:8000
   ```
   **Resultado esperado:** muestra el mismo panel que sin parámetro.

**Resultado esperado global:** todo arranca sin recompilar; todos los parámetros son configurables por CLI.

---

### PRUEBA 1.2 — Múltiples instancias simultáneas

**Objetivo:** Confirmar que se pueden desplegar varios CPs y Drivers sin interferencia.

**Pasos:**
1. Con ALC1 y ALC2 ya activos, lanzar un tercer CP:
   ```bash
   python3 EV_CP_E.py localhost 9092 6002
   python3 EV_CP_M.py localhost 6002 localhost 5000 ALC3
   ```
   → registrar y autenticar ALC3.
2. Verificar que el panel Tkinter muestra los 3 tiles (ALC1, ALC2, ALC3) en verde.
3. Lanzar un segundo Driver:
   ```bash
   python3 EV_Driver.py localhost 9092 Driver2
   ```
4. Pedir una carga desde Driver1 en ALC1 y otra desde Driver2 en ALC2 simultáneamente.
5. Verificar que ambas cargas se procesan sin interferirse.

**Resultado esperado:** múltiples instancias coexisten; el panel refleja el estado correcto de cada CP.

---

## BLOQUE 2 — Flujo base de carga

### PRUEBA 2.1 — Flujo completo sin interacción (archivo de servicios)

**Objetivo:** El sistema procesa las 12 cargas de `cargas.txt` de forma autónoma; todo es observable en pantalla.

**Pasos:**
1. Con ALC1, ALC2 y Driver1 activos, seleccionar opción `3` en el Driver → introducir `cargas.txt`.
2. Confirmar con `s` y **no tocar ningún terminal**.
3. Observar simultáneamente durante la ejecución:
   - **Panel Tkinter:** ALC1 y ALC2 alternan entre verde (ACTIVE) y verde oscuro (BUSY).
   - **Sección ON GOING DRIVERS REQUESTS:** aparece Driver1 con CP, hora de inicio, kWh y € en tiempo real.
   - **Sección APPLICATION MESSAGES:** registra petición aceptada, consumo, finalización.
   - **Terminal Monitor:** muestra CARGANDO con kWh/€ actualizándose.
   - **Terminal Engine:** muestra conductor activo y acumulado; prompt ENTER visible.
   - **Terminal Driver:** imprime consumo en tiempo real y al final el TICKET con kWh y coste.
4. Verificar que las 12 cargas se completan; el Driver espera 4 segundos entre cargas.

**Resultado esperado:** las 12 cargas terminan sin errores; cada una genera un TICKET en el Driver.

---

### PRUEBA 2.2 — Carga manual desde Monitor

**Objetivo:** El Monitor puede iniciar una carga manual en el Engine.

**Pasos:**
1. Con ALC1 en ACTIVE, pulsar `1` en el Monitor ALC1.
2. Introducir duración (ej: 15 segundos) y confirmar.
3. Verificar que el Engine acepta la carga y ALC1 pasa a BUSY.
4. Esperar a que termine → ALC1 vuelve a ACTIVE.

**Resultado esperado:** carga manual procesada correctamente; visible en panel y terminal.

---

### PRUEBA 2.3 — Autenticación: aceptación y rechazo

**Objetivo:** Solo CPs con credenciales válidas son aceptados por Central.

**Escenario A — Flujo normal de registro:**
1. Borrar `db.json` y `credentials.json` si existen. Reiniciar Registry, Central, Engine y Monitor.
2. Monitor muestra menú de registro → opción `1` → introducir datos.
3. **Resultado esperado:** Monitor se registra en Registry (HTTPS), recibe credenciales, las envía a Central → panel muestra ALC1 en verde.

**Escenario B — Rechazo por credenciales inválidas:**
1. Con ALC1 registrado, editar `credentials.json` y cambiar la contraseña de ALC1.
2. Reiniciar Monitor ALC1 → seleccionar opción `1` (re-registrar).
3. Como las credenciales ya existen en Registry pero son distintas, verificar comportamiento.
   - Alternativa más directa: usar opción `2` (re-registrar) desde un Monitor ya activo → Registry genera nuevas credenciales → opción `3` re-autentica correctamente.
4. Para forzar rechazo: lanzar Monitor con usuario/contraseña inventados editando directamente el código (solo para demostración).
5. **Resultado esperado:** Central imprime "rechazado (credenciales inválidas)" → Monitor imprime error y termina.

---

### PRUEBA 2.4 — STOP / RESUME desde Central

**Objetivo:** Central puede parar y reanudar CPs; los efectos son visibles en panel y Driver.

**Escenario A — STOP con CP libre:**
1. Con ALC1 en ACTIVE, desde el menú de Central opción `1` → introducir `ALC1`.
2. **Resultado esperado:** panel ALC1 → rojo (BROKEN). Monitor muestra "AVERIADO". Log: `CP_STOP`.
3. Driver solicita carga en ALC1 → rechazada.
4. Opción `2` (RESUME) → panel vuelve a verde. Log: `CP_RESUME`.

**Escenario B — STOP durante carga activa:**
1. Iniciar carga de 30s en ALC1.
2. A los ~5s, desde Central opción `1` → `ALC1`.
3. **Resultado esperado:** carga interrumpida. Driver recibe `CHARGE_INTERRUPTED` con kWh parciales. Panel → rojo. Log: `CHARGE_INTERRUPTED`.

**Escenario C — Parar todos / Reanudar todos:**
1. Opción `3` → todos los CPs pasan a BROKEN.
2. Opción `4` → todos vuelven a ACTIVE.
3. **Resultado esperado:** el panel cambia todos los tiles simultáneamente.

---

## BLOQUE 3 — Resiliencia

### PRUEBA 3.1 — Caída del Monitor

**Escenario A — Monitor cae con CP libre:**
1. Con ALC1 en ACTIVE, `Ctrl+C` en el terminal del Monitor ALC1.
2. **Resultado esperado:** panel ALC1 → gris (DESCONECTADO) en menos de 2s.
3. Driver solicita carga en ALC1 → rechazada.
4. Reiniciar Monitor ALC1 (presiona ENTER → opción 1 → re-registrar → opción 3 re-autenticar, o simplemente arrancarlo y seguir el flujo) → panel vuelve a verde.

**Escenario B — Monitor cae durante carga:**
1. Iniciar carga de 30s en ALC1.
2. A los ~5s, `Ctrl+C` en Monitor ALC1.
3. **Resultado esperado:**
   - Engine continúa la carga (Kafka es independiente del Monitor).
   - Driver recibe el TICKET al final de la carga.
   - Panel ALC1 → gris durante la carga y después.
   - Al reiniciar Monitor, ALC1 vuelve a ACTIVE.

---

### PRUEBA 3.2 — Caída del Engine

**Escenario A — Engine cae con CP libre:**
1. Con ALC1 en ACTIVE, `Ctrl+C` en el terminal del Engine ALC1.
2. **Resultado esperado:** Monitor detecta error → envía `OUT_OF_ORDER` a Central → panel → naranja.
3. Reiniciar Engine ALC1 → Monitor detecta disponibilidad → estado vuelve a ACTIVE.

**Escenario B — Engine cae durante carga:**
1. Iniciar carga de 30s en ALC1.
2. A los ~5s, `Ctrl+C` en Engine ALC1.
3. **Resultado esperado:**
   - Monitor notifica OUT_OF_ORDER → panel naranja.
   - Central envía ticket parcial al Driver con kWh acumulados. Log: `CHARGE_INTERRUPTED`.
   - Al reiniciar Engine, CP vuelve a ACTIVE.

---

### PRUEBA 3.3 — Caída del Driver

**Pasos:**
1. Iniciar carga de 30s en ALC1 desde Driver1.
2. A los ~10s, `Ctrl+C` en Driver1.
3. Verificar que Engine sigue cargando (terminal Engine muestra kWh incrementándose).
4. Reiniciar Driver1:
   ```bash
   python3 EV_Driver.py localhost 9092 Driver1
   ```
5. **Resultado esperado:** Driver1 recibe el TICKET pendiente al reconectar (Kafka mantiene el offset del grupo `driver-Driver1`).

---

### PRUEBA 3.4 — Caída de Central

**Pasos:**
1. Iniciar carga de 30s en ALC1.
2. A los ~5s, `Ctrl+C` en Central.
3. **Verificar:**
   - Engine sigue cargando (Kafka es independiente de Central).
   - Intentar nueva carga desde Driver2 en ALC2 → sin respuesta (nadie procesa peticiones).
   - Front muestra banner rojo "No se puede conectar con Central".
4. Reiniciar Central:
   ```bash
   python3 EV_Central.py
   ```
5. **Resultado esperado:** Monitores reconectan automáticamente (sin reiniciarlos); panel vuelve a mostrar ALC1 y ALC2. Front se recupera solo.

---

### PRUEBA 3.5 — Errores visibles en pantalla

**Objetivo:** Los errores del sistema se muestran de forma controlada en todos los interfaces.

| Escenario | Qué debe mostrarse |
|---|---|
| Central caída | Front: banner rojo. Monitor: mensaje de reconexión en curso |
| EV_W caído | Front: temperatura "—" en tabla CPs; sección Weather vacía |
| Engine caído | Monitor: "OUT_OF_ORDER". Panel: naranja. Front: badge "Fuera Servicio" |
| Kafka inasequible | Engine/Driver: mensaje de error al arrancar |

---

## BLOQUE 4 — EV_W y alertas climáticas

### PRUEBA 4.1 — Parametrización de EV_W

**Pasos:**
1. Borrar `ev_w_config.json`. Lanzar `python3 EV_W.py` → debe pedir API key por consola y guardarla.
2. Cerrar EV_W y volver a lanzar → debe arrancar sin pedir la key (la lee del archivo).
3. Lanzar EV_W apuntando a Central en distinto puerto:
   ```bash
   python3 EV_W.py localhost 8000
   ```
4. Intentar con el puerto TCP de Central:
   ```bash
   python3 EV_W.py localhost 5000
   ```
   **Resultado esperado:** EV_W detecta que no es el API REST y muestra error descriptivo. No arranca.

**Resultado esperado:** API key persiste en archivo; parámetros configurables por CLI.

---

### PRUEBA 4.2 — Alertas climáticas

**Escenario A — Alerta con CP libre:**
1. Con ALC1 en ACTIVE, desde menú EV_W opción `1` → poner ALC1 en una ciudad con temperatura < 0°C (ej: "Tromsø" o "Yakutsk").
2. **Resultado esperado en ~4s:**
   - Log EV_W: "ALERTA: ALC1 temperatura crítica".
   - Panel Tkinter: ALC1 → naranja (OUT_OF_ORDER).
   - Front: badge "Fuera Servicio" para ALC1; temperatura en rojo.
   - Log auditoría: `WEATHER_ALERT`.
3. Driver intenta carga en ALC1 → rechazada.
4. Cambiar ALC1 a ciudad con temperatura ≥ 0°C → Central recibe CANCEL → ALC1 vuelve a ACTIVE (verde). Log: `WEATHER_CANCEL`.

**Escenario B — Alerta durante carga activa:**
1. Iniciar carga de 45s en ALC1.
2. Cambiar ciudad de ALC1 a ciudad < 0°C mientras está cargando.
3. **Resultado esperado:** la carga en curso **finaliza con normalidad** (EV_W espera el CHARGE_END). Al terminar, ALC1 pasa a OUT_OF_ORDER. Driver recibe TICKET normal.

**Escenario C — Cambio de localización en caliente:**
1. Usar opción `1` del menú de EV_W para cambiar la ciudad de ALC1 → verificar que el efecto es inmediato sin reiniciar ningún módulo.
2. Verificar que `opción 2` (Ver estado actual) muestra el menú actualizado sin hacer nada.

---

## BLOQUE 5 — Front web

### PRUEBA 5.1 — Múltiples navegadores y datos completos

**Pasos:**
1. Con el sistema completo activo, abrir `front.html` en dos navegadores distintos (o dos pestañas).
2. Verificar que ambos muestran datos actualizados cada 2 segundos de forma independiente.
3. Iniciar una carga desde Driver1 → verificar que aparece en **ON GOING DRIVERS REQUESTS** en ambos navegadores (conductor, CP, hora de inicio, kWh, €).
4. Verificar que la tabla **Charging Points** muestra: ID, dirección, precio, estado (badge de color), conductor activo, kWh, coste, conexión Online/Offline, ciudad, temperatura.
5. Verificar sección **Weather / Climate Status** con ciudades y temperaturas.
6. Verificar sección **Application Messages** con últimos eventos.

**Resultado esperado:** múltiples navegadores simultáneos; todas las secciones con datos en tiempo real.

---

### PRUEBA 5.2 — Resiliencia del front

**Escenario A — Central cae:**
1. Cerrar Central. **Resultado esperado:** banner rojo en front; sin pantalla blanca ni error JS.
2. Reiniciar Central → front se recupera solo.

**Escenario B — EV_W cae:**
1. Cerrar EV_W. **Resultado esperado:** columna temperatura muestra "—"; sección Weather vacía. El resto del sistema funciona.
2. Reiniciar EV_W → temperatura vuelve en el siguiente ciclo.

---

## BLOQUE 6 — Seguridad

### PRUEBA 6.1 — Registry HTTPS

**Pasos:**
1. Verificar que el Registry rechaza HTTP:
   ```bash
   curl http://localhost:5001/register
   ```
   **Resultado esperado:** falla o redirige.

2. Registro vía curl HTTPS:
   ```bash
   curl -k -X POST https://localhost:5001/register \
     -H "Content-Type: application/json" \
     -d '{"id":"TEST1","address":"Calle Test 1","price":0.30}'
   ```
   **Resultado esperado:** HTTP 201 con `username` y `password`.

3. Consulta:
   ```bash
   curl -k https://localhost:5001/register/TEST1
   ```

4. Baja:
   ```bash
   curl -k -X DELETE https://localhost:5001/register/TEST1
   ```

**Resultado esperado:** solo acepta HTTPS; API accesible desde Postman/curl.

---

### PRUEBA 6.2 — Cifrado Fernet en Kafka

**Pasos:**
1. Con una carga activa, observar el tópico Kafka `consumo_cps`:
   ```bash
   docker exec -it kafka kafka-console-consumer \
     --bootstrap-server localhost:9092 --topic consumo_cps --from-beginning
   ```
   **Resultado esperado:** los mensajes son texto cifrado en base64 (ilegibles en plano).

2. Verificar que ALC1 y ALC2 generan texto cifrado distinto para el mismo tipo de mensaje (claves distintas por CP).

---

### PRUEBA 6.3 — Revocación de clave y re-autenticación

**Pasos:**
1. Con el sistema activo, desde Central opción `7` → introducir `ALC1`.
2. **Resultado esperado simultáneamente (en < 2s):**
   - **Monitor ALC1:** banner rojo "AVISO: Clave revocada por Central. Usa opcion 3 para re-autenticarte."
   - **Engine ALC1:** banner `!!!!` "AVISO: CLAVE REVOCADA POR CENTRAL".
   - **Panel Tkinter:** ALC1 → naranja (OUT_OF_ORDER).
   - **Front:** badge "Fuera Servicio" para ALC1.
   - **Application Messages (panel y front):** log de la revocación.
   - **Audit log:** entrada `KEY_REVOKED`.
3. Iniciar carga en el tópico Kafka desde ALC1 → Central muestra "CP ALC1 — mensaje no comprensible (clave incorrecta)".
4. Driver intenta carga en ALC1 → rechazada.
5. Desde Monitor ALC1, pulsar `3` (Re-autenticarse con Central).
6. **Resultado esperado:**
   - Monitor obtiene nueva clave Fernet y la envía al Engine.
   - Banner de clave revocada desaparece en Monitor y Engine.
   - ALC1 vuelve a ACTIVE. Cargas aceptadas de nuevo.
   - Mensajes Kafka de ALC1 vuelven a ser descifrados correctamente por Central.

---

## BLOQUE 7 — Log de auditoría

### PRUEBA 7.1 — Formato y contenido del log

**Pasos:**
1. Ejecutar el flujo normal: registrar CPs, autenticar, realizar cargas, revocar clave, alerta climática.
2. Abrir `audit.log` y verificar formato:
   ```
   YYYY-MM-DD HH:MM:SS | ACCIÓN              | FUENTE         | DETALLES
   ```
3. Verificar presencia de eventos:

| Evento | Cuándo aparece |
|---|---|
| `SYSTEM_START` | Al arrancar Central |
| `AUTH_SUCCESS` | Al autenticar un CP con credenciales válidas |
| `AUTH_FAIL` | Al intentar con credenciales inválidas |
| `CHARGE_END` | Al finalizar una carga |
| `CHARGE_INTERRUPTED` | Al interrumpir (STOP o Engine caído) |
| `KEY_REVOKED` | Al revocar una clave desde Central |
| `WEATHER_ALERT` | Al recibir alerta de EV_W |
| `WEATHER_CANCEL` | Al cancelar alerta de EV_W |
| `CP_STOP` | Al parar un CP desde Central |
| `CP_RESUME` | Al reanudar un CP desde Central |
| `CP_DISCONNECTED` | Al desconectarse un Monitor |

4. Verificar que la columna FUENTE contiene la IP del CP o "central_menu" según corresponda.

**Resultado esperado:** todos los eventos registrados con fecha, acción, origen y detalles.

---

## BLOQUE 8 — API REST de auditoría y Audit Front

### PRUEBA 8.1 — API REST de auditoría

**Pasos:**
1. Arrancar sistema y realizar acciones (autenticar CP, carga, revocar clave).
2. Todas las entradas:
   ```bash
   curl http://localhost:8000/api/audit
   ```
   **Resultado:** JSON con `status: SUCCESS` y array `data` con `timestamp`, `action`, `source`, `details`.

3. Filtrar por tipo:
   ```bash
   curl "http://localhost:8000/api/audit?action=AUTH_SUCCESS"
   curl "http://localhost:8000/api/audit?action=CHARGE_END"
   curl "http://localhost:8000/api/audit?action=KEY_REVOKED"
   ```

4. Filtrar por fuente:
   ```bash
   curl "http://localhost:8000/api/audit?source=127.0.0.1"
   curl "http://localhost:8000/api/audit?source=central_menu"
   ```

5. Limitar entradas:
   ```bash
   curl "http://localhost:8000/api/audit?limit=5"
   ```
   **Resultado:** máximo 5 entradas (las más recientes).

6. Combinar filtros:
   ```bash
   curl "http://localhost:8000/api/audit?action=CHARGE_END&limit=3"
   ```

**Resultado esperado:** API funcional; respuestas JSON correctamente formadas.

---

### PRUEBA 8.2 — Audit Front: carga inicial y colores

**Pasos:**
1. Abrir `audit.html` en el navegador.
2. **Resultado esperado:**
   - Tabla con todas las entradas existentes en `audit.log`.
   - Cada fila: Fecha/Hora, Evento (badge de color), Fuente, Detalles.
   - Indicador superior "En tiempo real" (punto verde).
3. Verificar colores de badges:
   - `AUTH_SUCCESS` → verde
   - `AUTH_FAIL` → rojo
   - `KEY_REVOKED` → naranja
   - `SYSTEM_START` → morado
   - `CHARGE_END` → verde oscuro
   - `WEATHER_ALERT` → azul

---

### PRUEBA 8.3 — Audit Front: tiempo real (SSE)

**Pasos:**
1. Con `audit.html` abierto, iniciar una carga desde el Driver.
2. **Resultado esperado (en ≤2s, sin recargar):** fila `CHARGE_END` aparece con destello.
3. Revocar clave de un CP → `KEY_REVOKED` aparece en tiempo real.
4. Arrancar un Monitor con credenciales incorrectas → `AUTH_FAIL` aparece en tiempo real.

---

### PRUEBA 8.4 — Audit Front: filtros

**Pasos:**
1. Seleccionar tipo en el desplegable (ej. `AUTH_SUCCESS`).
   **Resultado:** solo filas de ese tipo. Contador actualizado.
2. Pulsar "Limpiar filtros" → todas las filas vuelven.
3. Con filtro `AUTH_FAIL` activo, generar un `AUTH_SUCCESS` → **no** debe aparecer en la tabla.
   Limpiar filtro → aparece.

---

### PRUEBA 8.5 — Audit Front: resiliencia y despliegue distribuido

**Escenario A — Central cae:**
1. Cerrar Central. **Resultado:** indicador rojo + "Sin conexión". Banner de error visible.
2. Reiniciar Central. **Resultado:** indicador vuelve a verde en ≤3s; nuevas entradas se reciben.

**Escenario B — Despliegue distribuido (si hay 2 máquinas):**
1. Abrir `audit.html?api=http://<IP_CENTRAL>:8000` desde otro equipo.
2. **Resultado:** mismo comportamiento que en local.

---

## BLOQUE 9 — Despliegue distribuido en 3 máquinas

> **Ejecutar este bloque solo en laboratorio con 3 equipos.**

### Escenario de distribución

| Máquina | Componentes | IP (ejemplo) |
|---|---|---|
| PC1 | Kafka + EV_Central + Fronts | 192.168.1.10 |
| PC2 | EV_CP_E + EV_CP_M + EV_W | 192.168.1.20 |
| PC3 | EV_Driver + EV_Registry | 192.168.1.30 |

### Comandos de arranque

```bash
# PC1
docker compose up -d
python3 EV_Central.py 5000 192.168.1.10 9092

# PC2
python3 EV_CP_E.py 192.168.1.10 9092 6000
python3 EV_CP_M.py localhost 6000 192.168.1.10 5000 ALC1 192.168.1.30 5001
python3 EV_W.py 192.168.1.10 8000

# PC3
python3 EV_Registry.py
python3 EV_Driver.py 192.168.1.10 9092 Driver1

# Navegador (cualquier PC)
front.html?api=http://192.168.1.10:8000
audit.html?api=http://192.168.1.10:8000
```

### Verificaciones

1. **Conectividad:** Panel Tkinter en PC1 muestra ALC1 verde.
2. **Flujo completo:** Driver en PC3 solicita carga → Engine en PC2 procesa → TICKET vuelve a PC3.
3. **Front distribuido:** `front.html` abierto en PC3 muestra estado en tiempo real desde PC1.
4. **Audit distribuido:** `audit.html` abierto en PC3 recibe eventos SSE desde PC1.
5. **Resiliencia distribuida:** apagar PC2 → PC1 muestra DESCONECTADO. Reiniciar PC2 → reconecta.

---

## Tabla resumen de criterios evaluados

| Criterio (guía de corrección) | Prueba |
|---|---|
| Parámetros por CLI, sin recompilar | 1.1 |
| Múltiples instancias del mismo módulo | 1.2 |
| Flujo normal sin interacción, observable en pantalla | 2.1 |
| Carga manual desde Monitor | 2.2 |
| Autenticación: aceptación y denegación | 2.3 |
| STOP / RESUME desde Central (CP individual y todos) | 2.4 |
| Monitor KO → DESCONECTADO, bloqueo nuevas cargas | 3.1 |
| Engine KO → OUT_OF_ORDER notificado a Central | 3.2 |
| Driver KO → carga continúa, TICKET al reconectar | 3.3 |
| Central KO → CPs terminan carga, reconexión automática | 3.4 |
| Errores visibles de forma controlada en todos los interfaces | 3.5 |
| EV_W: parametrización (API key, IP/puerto) | 4.1 |
| EV_W: alertas climáticas → CP OUT_OF_ORDER | 4.2A |
| EV_W: carga en curso termina antes de parar CP | 4.2B |
| EV_W: localizaciones cambiables en caliente | 4.2C |
| Front: múltiples navegadores; datos completos | 5.1 |
| Front: errores visibles de forma controlada | 5.2 |
| Registry HTTPS; API accesible desde Postman/curl | 6.1 |
| Cifrado Kafka simétrico; claves únicas por CP | 6.2 |
| Revocación de clave visible en CP_E, Monitor, front y central | 6.3 |
| Re-autenticación sin reiniciar Monitor | 6.3 |
| Log de auditoría estructurado con todos los eventos | 7.1 |
| `GET /api/audit` y filtros `?action=` `?source=` `?limit=` | 8.1 |
| Audit front: historial completo al abrir | 8.2 |
| Audit front: tiempo real SSE | 8.3 |
| Audit front: filtros sobre la tabla | 8.4 |
| Audit front: reconexión automática si Central cae | 8.5 |
| Despliegue en 3 máquinas distintas | 9 |
