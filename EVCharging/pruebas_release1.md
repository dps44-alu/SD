# Pruebas Release 1 — EVCharging Network

## Preparación (ejecutar antes de cada prueba)

```bash
# 1. Limpiar estado anterior
rm -f db.json credentials.json audit.log creds_*.json

# 2. Arrancar en este orden (una terminal por proceso)
docker compose up -d
python3 EV_Registry.py
python3 EV_Central.py
python3 EV_CP_E.py                                    # Engine ALC1
python3 EV_CP_M.py                                    # Monitor ALC1
python3 EV_CP_E.py localhost 9093                     # Engine ALC2 (puerto distinto si misma máquina)
python3 EV_CP_M.py localhost 6001 localhost 5000 ALC2 # Monitor ALC2
python3 EV_Driver.py localhost 9092 Driver1
```

> **Nota:** Para pruebas de resiliencia se recomienda tener también `python3 EV_Driver.py localhost 9092 Driver2`.

---

## PRUEBA 1 — Parametrización y despliegue

**Objetivo:** Confirmar que ningún parámetro está hardcodeado y que se pueden desplegar múltiples instancias.

**Pasos:**
1. Lanzar Central en puerto distinto: `python3 EV_Central.py 5100` → debe arrancar sin tocar el código.
2. Lanzar Monitor apuntando al nuevo puerto: `python3 EV_CP_M.py localhost 6000 localhost 5100 ALC1`.
3. Lanzar Driver con ID distinto: `python3 EV_Driver.py localhost 9092 Driver2`.
4. Verificar que ALC1 y ALC2 corren simultáneamente sin interferencia.
5. Matar ALC2 con `Ctrl+C` (simular crash) → el sistema sigue funcionando con ALC1.
6. Arrancar un nuevo Monitor ALC2 → se reconecta sin recompilar nada.

**Resultado esperado:** Todo arranca con parámetros distintos a los por defecto; la caída de un módulo no afecta al resto.

---

## PRUEBA 2 — Flujo completo sin interacción

**Objetivo:** El sistema procesa las 12 cargas de `cargas.txt` de forma autónoma; todo es observable en pantalla.

**Pasos:**
1. Con ALC1, ALC2 y Driver1 corriendo, seleccionar opción `3` en el Driver → introducir `cargas.txt`.
2. Confirmar con `s` y **no tocar ningún terminal**.
3. Observar simultáneamente:
   - **Panel Tkinter:** ALC1 y ALC2 cambian verde→azul→verde a medida que procesan cargas.
   - **Sección ON GOING DRIVERS REQUESTS:** aparece Driver1 con CP, hora de inicio, kWh y € en tiempo real.
   - **Sección APPLICATION MESSAGES:** registra cada evento (petición aceptada, consumo, finalización).
   - **Terminal Monitor:** muestra CARGANDO con kWh/€ actualizándose cada segundo.
   - **Terminal Engine:** pantalla estática con conductor activo y acumulado; prompt ENTER visible.
   - **Terminal Driver:** imprime consumo en tiempo real y al final el TICKET con kWh y coste.

**Resultado esperado:** Las 12 cargas se completan sin errores; cada una genera un TICKET en el Driver.

---

## PRUEBA 3 — Autenticación: aceptación y rechazo

**Objetivo:** Solo CPs con credenciales válidas son aceptados por Central.

**Escenario A — recuperación automática de credenciales:**
1. Con ALC1 ya registrado, borrar `creds_ALC1.json` y `credentials.json`.
2. Reiniciar Monitor ALC1.
3. **Resultado esperado:** El Monitor detecta que no tiene credenciales locales, borra el CP del Registry, se re-registra, obtiene credenciales nuevas y se autentica en Central → panel muestra ALC1 en verde.

**Escenario B — rechazo por credenciales inválidas:**
1. Con ALC1 registrado, editar `credentials.json` y cambiar la contraseña de ALC1 por cualquier otra.
2. Reiniciar Monitor ALC1.
3. **Resultado esperado:** Central imprime `rechazado (credenciales inválidas)` → Monitor imprime `Conexión rechazada por Central. Cerrando...` y termina.

---

## PRUEBA 4 — STOP / RESUME

**Objetivo:** Central puede parar y reanudar CPs; los efectos son visibles en el panel y en el Driver.

**Escenario A — STOP con CP libre:**
1. Con ALC1 en verde (ACTIVE), desde el menú de Central opción `1` → introducir `ALC1`.
2. **Resultado esperado:** Panel ALC1 → rojo (BROKEN). Monitor muestra "AVERIADO".
3. Desde Driver solicitar carga en ALC1 → debe ser rechazada.
4. Opción `2` (RESUME) → panel vuelve a verde, ALC1 acepta cargas.

**Escenario B — STOP durante carga activa:**
1. Iniciar carga de 30 segundos en ALC1 desde el Driver.
2. A los ~5s, desde Central opción `1` → `ALC1`.
3. **Resultado esperado:** La carga se interrumpe. Driver recibe `CHARGE_INTERRUPTED` con los kWh parciales acumulados hasta ese momento. Panel ALC1 → rojo.

---

## PRUEBA 5 — Resiliencia: caída del Monitor

**Objetivo:** `Monitor_KO + Engine_OK → DESCONECTADO`; no se aceptan nuevas cargas.

**Escenario A — Monitor cae con CP libre:**
1. Con ALC1 en ACTIVE, hacer `Ctrl+C` en el terminal del Monitor ALC1.
2. **Resultado esperado:** Panel ALC1 → gris (DESCONECTADO) en menos de 2 segundos.
3. Desde Driver solicitar carga en ALC1 → debe ser rechazada (CP en INACTIVE).
4. Reiniciar Monitor ALC1 → reconecta, panel vuelve a verde.

**Escenario B — Monitor cae durante carga:**
1. Iniciar carga de 30s en ALC1.
2. A los ~5s, `Ctrl+C` en Monitor ALC1.
3. **Resultado esperado:**
   - Engine continúa la carga (funciona por Kafka independientemente del Monitor).
   - Driver recibe el TICKET al final de la carga.
   - Panel ALC1 → gris durante toda la carga y después.
   - Al reiniciar Monitor, ALC1 vuelve a ACTIVE (no a BUSY, la carga ya terminó).

---

## PRUEBA 6 — Resiliencia: caída del Engine

**Objetivo:** `Monitor_OK + Engine_KO → Averiado (OUT_OF_ORDER)`; Central recibe la señal.

**Escenario A — Engine cae con CP libre:**
1. Con ALC1 en ACTIVE, `Ctrl+C` en el terminal del Engine ALC1.
2. **Resultado esperado:** Monitor detecta error de socket → envía `CHANGE#ALC1#None#None#OUT_OF_ORDER` a Central → panel ALC1 → naranja.
3. Reiniciar Engine ALC1 → Monitor detecta el Engine disponible en el siguiente ciclo de polling → estado vuelve a ACTIVE.

**Escenario B — Engine cae durante carga:**
1. Iniciar carga de 30s en ALC1.
2. A los ~5s, `Ctrl+C` en Engine ALC1.
3. **Resultado esperado:**
   - Monitor notifica OUT_OF_ORDER a Central → panel naranja.
   - Central envía ticket parcial al Driver con los kWh acumulados hasta la caída.
   - Al reiniciar Engine, CP vuelve a ACTIVE.

---

## PRUEBA 7 — Resiliencia: caída del Driver

**Objetivo:** La carga continúa si el Driver se cierra; al reconectar ve el resultado.

**Pasos:**
1. Iniciar carga de 30s en ALC1 desde Driver1.
2. A los ~10s, `Ctrl+C` en Driver1.
3. Verificar que Engine sigue cargando (terminal Engine muestra kWh incrementándose).
4. Reiniciar Driver1: `python3 EV_Driver.py localhost 9092 Driver1`.
5. **Resultado esperado:** Driver1 recibe el TICKET pendiente (Kafka mantiene el offset del grupo `driver-Driver1` y entrega el mensaje al reconectar).

---

## PRUEBA 8 — Resiliencia: caída de Central

**Objetivo:** CPs terminan la carga en curso; no se aceptan nuevas peticiones; al reiniciar Central los Monitores reconectan solos.

**Pasos:**
1. Iniciar carga de 30s en ALC1 desde Driver1.
2. A los ~5s, `Ctrl+C` en Central.
3. **Verificar:**
   - Engine sigue cargando (Kafka es independiente de Central).
   - Intentar nueva carga desde Driver2 en ALC2 → sin respuesta (nadie procesa `peticiones_conductores`).
4. Reiniciar Central: `python3 EV_Central.py`.
5. **Resultado esperado:** Los Monitores detectan que la conexión con Central se ha restablecido y reconectan automáticamente (sin reiniciar los Monitores). Panel vuelve a mostrar ALC1 y ALC2 con su estado actual.

---

## Tabla resumen de criterios evaluados

| Criterio (guía de corrección) | Prueba |
|---|---|
| Parámetros por CLI, sin recompilar | 1 |
| Múltiples instancias del mismo módulo | 1 |
| Flujo normal sin interacción, observable en pantalla | 2 |
| Autenticación: aceptación y denegación | 3 |
| STOP / RESUME desde Central | 4 |
| Monitor KO → DESCONECTADO, bloqueo de nuevas cargas | 5 |
| Engine KO → Averiado (OUT_OF_ORDER) notificado a Central | 6 |
| Driver KO → carga continúa, TICKET al reconectar | 7 |
| Central KO → CPs terminan carga, reconexión automática | 8 |
