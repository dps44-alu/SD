# Pruebas Release 2 — EVCharging Network

## Preparación (ejecutar antes de cada prueba)

```bash
# 0. Matar procesos anteriores (¡importante entre pruebas!)
pkill -f "python3 EV" 2>/dev/null; sleep 1

# 1. Limpiar estado anterior
rm -f db.json credentials.json audit.log creds_*.json ev_w_config.json

# 2. Arrancar en este orden (una terminal por proceso)
docker compose up -d
python3 EV_Registry.py
python3 EV_Central.py
python3 EV_CP_E.py                                    # Engine ALC1
python3 EV_CP_M.py                                    # Monitor ALC1 → muestra menú de registro; seleccionar "1" e introducir dirección y precio
python3 EV_CP_E.py localhost 9092 6001                # Engine ALC2
python3 EV_CP_M.py localhost 6001 localhost 5000 ALC2 # Monitor ALC2 → igual, seleccionar "1" e introducir datos
python3 EV_W.py                                       # pide API key la primera vez
python3 EV_Driver.py localhost 9092 Driver1
# Abrir front: front.html (doble clic o servidor web)
```

> **NOTAS IMPORTANTES:**
> - EV_W conecta al **puerto 8000** (API REST de Central), **NO al 5000** (puerto TCP del Monitor).
>   Si ves "Conexión de Monitor" en Central al arrancar EV_W → estás usando el puerto equivocado.
> - Si aparecen mensajes de Monitor inesperados en Central cuando no hay Monitores activos,
>   ejecuta `pkill -f EV_CP_M.py` para matar procesos huérfanos de pruebas anteriores.

---

## PRUEBA 1 — Parametrización

**Objetivo:** Ningún parámetro hardcodeado; API key de OpenWeather en archivo; localizaciones cambiables en caliente.

**Pasos:**
1. Borrar `ev_w_config.json` si existe. Lanzar `python3 EV_W.py` → debe pedir API key por consola y guardarla en `ev_w_config.json`.
2. Cerrar EV_W y volver a lanzar → debe arrancar sin pedir la key (la lee del archivo).
3. Desde el menú de EV_W, opción `4` → cambiar la API key en caliente → verificar que `ev_w_config.json` se actualiza.
4. Lanzar EV_W apuntando a Central en IP/puerto distinto: `python3 EV_W.py 192.168.x.x 8000`.
5. Abrir front con URL parametrizada: `front.html?api=http://192.168.x.x:8000` → debe conectar correctamente.
6. Desde menú EV_W, opción `1` → cambiar ciudad de ALC1 sin reiniciar → verificar efecto inmediato en lecturas.

**Resultado esperado:** Todo parametrizable sin tocar el código; API key persiste en archivo; localizaciones cambiables en tiempo de ejecución.

---

## PRUEBA 2 — Front: múltiples navegadores y estado completo

**Objetivo:** El front se puede abrir simultáneamente desde cualquier navegador y muestra todo el estado del sistema.

**Pasos:**
1. Con el sistema completo activo, abrir `front.html` en dos navegadores distintos (o dos pestañas).
2. Verificar que ambos muestran datos actualizados cada 2 segundos de forma independiente.
3. Iniciar una carga desde Driver1 → verificar que aparece en la sección **On Going Drivers Requests** en ambos navegadores (conductor, CP, hora de inicio, kWh, €).
4. Verificar que la tabla **Charging Points** muestra: ID, dirección, precio, estado (badge de color), conductor, kWh, coste, conexión Online/Offline, ciudad, temperatura.
5. Verificar que la sección **Weather / Climate Status** muestra las ciudades y temperaturas actuales de EV_W.
6. Verificar que **Application Messages** muestra los últimos eventos del sistema.

**Resultado esperado:** Múltiples navegadores simultáneos; todas las secciones con datos en tiempo real.

---

## PRUEBA 3 — Front: resiliencia de la interfaz

**Objetivo:** El front muestra errores de forma controlada; no se rompe cuando un módulo cae.

**Escenario A — Central cae:**
1. Cerrar Central con `Ctrl+C`.
2. **Resultado esperado:** Front muestra banner rojo "No se puede conectar con Central" y el indicador de estado cambia a "Central no disponible". No se queda en pantalla blanca ni genera excepción JS.
3. Reiniciar Central → front se recupera solo.

**Escenario B — EV_W cae:**
1. Cerrar EV_W.
2. **Resultado esperado:** La columna "Temperatura" en la tabla de CPs muestra "—" y la sección Weather muestra "Sin datos de EV_W". El resto del sistema funciona con normalidad.
3. Reiniciar EV_W → temperatura vuelve a aparecer en el front en el siguiente ciclo de 4 segundos.

---

## PRUEBA 4 — EV_W: alertas climáticas

**Objetivo:** EV_W detecta temperatura < 0°C, notifica a Central, CP pasa a OUT_OF_ORDER; se ve en Tkinter y en Front.

**Escenario A — Alerta con CP libre:**
1. Con ALC1 en ACTIVE, desde menú EV_W opción `1` → poner ALC1 en una ciudad con temperatura < 0°C (ej: Tromsø, Noruega, o cualquier ciudad ártica en invierno).
2. **Resultado esperado (en ~4s):** Log EV_W muestra ALERTA. Panel Tkinter → ALC1 naranja (OUT_OF_ORDER). Front → badge "Fuera Servicio" para ALC1. Temperatura aparece en rojo con icono de alerta.
3. Driver intenta carga en ALC1 → rechazada.
4. Cambiar ALC1 a ciudad con temperatura ≥ 0°C → Central recibe CANCEL → ALC1 vuelve a ACTIVE (verde).

**Escenario B — Alerta durante carga activa:**
1. Iniciar carga de 30s en ALC1.
2. Cambiar ciudad de ALC1 a ciudad < 0°C.
3. **Resultado esperado:** La carga en curso **finaliza con normalidad** (EV_W espera al CHARGE_END). Al terminar, ALC1 pasa a OUT_OF_ORDER. Driver recibe TICKET normal.

**Escenario C — Cambio de localización en caliente:**
1. Usar opción `1` del menú de EV_W para cambiar la ciudad de ALC1 → verificar que el efecto es inmediato sin reiniciar ningún módulo.

---

## PRUEBA 5 — Seguridad: Registry HTTPS

**Objetivo:** El canal entre CP y Registry es seguro (HTTPS); el API es accesible desde herramientas externas.

**Pasos:**
1. Verificar que el Registry rechaza HTTP: `curl http://localhost:5001/register` → debe fallar o redirigir.
2. Registro exitoso vía curl:
   ```bash
   curl -k -X POST https://localhost:5001/register \
     -H "Content-Type: application/json" \
     -d '{"id":"TEST1","address":"Calle Test 1","price":0.30}'
   ```
   **Resultado esperado:** HTTP 201 con `username` y `password`.
3. Consulta de CP registrado:
   ```bash
   curl -k https://localhost:5001/register/TEST1
   ```
4. Baja del CP:
   ```bash
   curl -k -X DELETE https://localhost:5001/register/TEST1
   ```

**Resultado esperado:** Solo acepta HTTPS; API operativa desde Postman/curl; credenciales protegidas.

---

## PRUEBA 6 — Seguridad: cifrado en Kafka y revocación de claves

**Objetivo:** Los mensajes en Kafka están cifrados con Fernet; cada CP tiene clave distinta; la revocación obliga a re-autenticarse; el error es visible en todos los interfaces.

**Escenario A — Verificación del cifrado:**
1. Con el sistema en marcha y una carga activa, observar el tópico Kafka `consumo_cps` desde consola:
   ```bash
   docker exec -it kafka kafka-console-consumer \
     --bootstrap-server localhost:9092 --topic consumo_cps --from-beginning
   ```
   **Resultado esperado:** Los mensajes son texto cifrado (base64 Fernet), no legibles en plano.

**Escenario B — Revocación de clave:**
1. Desde Central, opción `7` → revocar clave de ALC1.
2. **Resultado esperado simultáneamente:**
   - **Monitor ALC1:** aparece aviso "AVISO: Clave revocada por Central. Usa opción 3 para re-autenticarte."
   - **Panel Tkinter Central:** ALC1 → naranja (OUT_OF_ORDER).
   - **Front:** ALC1 badge "Fuera Servicio".
   - **Application Messages (front y Tkinter):** log de la revocación.
3. Los mensajes Kafka de ALC1 ya no se descifran → **Central muestra en APPLICATION MESSAGES** "CP ALC1 — mensaje no comprensible (clave incorrecta)"; el Front también lo recibe vía `/api/messages`.
4. Driver intenta carga en ALC1 → rechazada.
5. Desde Monitor ALC1, opción `3` (Re-autenticarse con Central).
6. **Resultado esperado:** Monitor obtiene nueva clave Fernet, la envía al Engine. ALC1 vuelve a ACTIVE. Cargas aceptadas de nuevo.

---

## PRUEBA 7 — Log de auditoría

**Objetivo:** `audit.log` registra todos los eventos relevantes con el formato especificado.

**Pasos:**
1. Ejecutar el flujo normal: registrar CPs, autenticar, cargar, revocar clave, alerta climática.
2. Abrir `audit.log` y verificar que contiene entradas con el formato:
   ```
   YYYY-MM-DD HH:MM:SS | ACCIÓN              | FUENTE         | DETALLES
   ```
3. Verificar presencia de los siguientes tipos de evento:
   - `SYSTEM_START` — al arrancar Central
   - `AUTH_SUCCESS` — al autenticar un CP con credenciales válidas
   - `AUTH_FAIL` — al intentar autenticar con credenciales inválidas
   - `AUTH_NEW_CP` — al registrar un CP nuevo
   - `CHARGE_END` — al finalizar una carga
   - `CHARGE_INTERRUPTED` — al interrumpir una carga (STOP o Engine caído)
   - `KEY_REVOKED` — al revocar una clave
   - `WEATHER_ALERT` — al recibir alerta de EV_W
   - `WEATHER_CANCEL` — al cancelar alerta de EV_W
4. Verificar que la columna FUENTE contiene la IP del CP o "central_menu" según corresponda.

**Resultado esperado:** Cada evento relevante queda registrado con fecha, acción, origen y detalles.

---

## PRUEBA 8 — Resiliencia general (criterios Release 1 con sistema Release 2)

**Objetivo:** Todos los criterios de resiliencia de Release 1 se mantienen con el sistema completo.

**Pasos:**
1. Repetir las **Pruebas 5, 6, 7 y 8 de Release 1** con EV_W y Front activos.
2. Verificar adicionalmente para cada escenario:
   - El **Front** muestra el cambio de estado del CP en tiempo real (sin recargar).
   - Los **errores** son visibles en el Front (banner de error o cambio en las secciones).
   - EV_W y sus alertas **no se ven afectados** por la caída de otros módulos.

**Escenarios clave a verificar:**
- Monitor cae → Front muestra CP desconectado (gris/Offline); EV_W sigue monitorizando.
- Engine cae → Front muestra OUT_OF_ORDER (naranja).
- Driver cae → Carga continúa; Driver recibe ticket al reconectar.
- Central cae → Front muestra error; Monitores reconectan solos al reiniciar Central; EV_W sigue funcionando.

**Resultado esperado:** Todos los escenarios de Release 1 funcionan igual; el Front refleja cada estado; la caída de Front o EV_W no afecta al núcleo del sistema.

---

## Tabla resumen de criterios evaluados

| Criterio (guía de corrección) | Prueba |
|---|---|
| Parámetros sin hardcodear; API key en archivo/menú | 1 |
| Localizaciones cambiables en caliente | 1 |
| Front múltiples navegadores; datos completos | 2 |
| Front: errores visibles de forma controlada | 3 |
| EV_W: alertas climáticas → CP OUT_OF_ORDER | 4 |
| EV_W: carga en curso termina antes de parar CP | 4B |
| Registry HTTPS; API accesible desde Postman/curl | 5 |
| Cifrado Kafka simétrico; claves únicas por CP | 6A |
| Revocación de clave visible en todos los interfaces | 6B |
| Re-autenticación sin reiniciar el Monitor | 6B |
| Log de auditoría estructurado | 7 |
| Criterios resiliencia Release 1 mantenidos | 8 |
| Front muestra estado en tiempo real | 2, 8 |
