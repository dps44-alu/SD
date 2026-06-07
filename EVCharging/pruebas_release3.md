# Pruebas Release 3 — Audit Log API + Front

## Preparación

```bash
# Sistema completo arrancado (igual que siempre)
pkill -f "python3 EV" 2>/dev/null; sleep 1
rm -f db.json credentials.json audit.log creds_*.json ev_w_config.json

docker compose up -d
python3 EV_Registry.py
python3 EV_Central.py
python3 EV_CP_E.py
python3 EV_CP_M.py
python3 EV_Driver.py localhost 9092 Driver1
```

---

## PRUEBA 1 — API REST de auditoría

**Objetivo:** El endpoint `/api/audit` devuelve las entradas del log en JSON.

**Pasos:**

1. Arrancar el sistema y realizar algunas acciones (autenticar un CP, hacer una carga).

2. Consultar todas las entradas:
   ```bash
   curl http://localhost:8000/api/audit
   ```
   **Resultado esperado:** JSON con `status: SUCCESS` y array `data` con entradas que tienen `timestamp`, `action`, `source`, `details`.

3. Filtrar por tipo de evento:
   ```bash
   curl "http://localhost:8000/api/audit?action=AUTH_SUCCESS"
   ```
   **Resultado esperado:** Solo entradas con `action = AUTH_SUCCESS`.

4. Filtrar por fuente:
   ```bash
   curl "http://localhost:8000/api/audit?source=127.0.0.1"
   ```
   **Resultado esperado:** Solo entradas cuya fuente contiene `127.0.0.1`.

5. Limitar número de entradas:
   ```bash
   curl "http://localhost:8000/api/audit?limit=5"
   ```
   **Resultado esperado:** Máximo 5 entradas (las más recientes).

6. Combinar filtros:
   ```bash
   curl "http://localhost:8000/api/audit?action=CHARGE_END&limit=3"
   ```

**Resultado esperado:** API funcional, respuestas JSON correctamente formadas.

---

## PRUEBA 2 — Front web de auditoría: carga inicial

**Objetivo:** `audit.html` carga el historial completo al abrirse.

**Pasos:**

1. Abrir `audit.html` en el navegador (doble clic o servidor web).
2. **Resultado esperado:**
   - Se muestra una tabla con todas las entradas existentes en `audit.log`.
   - Cada fila tiene: Fecha/Hora, Evento (badge de color), Fuente, Detalles.
   - El indicador superior muestra "En tiempo real" (punto verde).

3. Verificar colores por tipo de evento:
   - `AUTH_SUCCESS` → badge verde
   - `AUTH_FAIL` → badge rojo
   - `KEY_REVOKED` → badge naranja
   - `SYSTEM_START` → badge morado
   - `CHARGE_END` → badge verde oscuro
   - `WEATHER_ALERT` → badge azul

4. Verificar que el contador de entradas es correcto.

**Resultado esperado:** Tabla completa con historial, colores por tipo, contador correcto.

---

## PRUEBA 3 — Front web: tiempo real (SSE)

**Objetivo:** Las nuevas entradas del log aparecen en el front sin recargar la página.

**Pasos:**

1. Con `audit.html` abierto en el navegador, realizar una nueva acción en el sistema (ej. iniciar una carga desde el Driver).

2. **Resultado esperado (en ≤2s, sin recargar):**
   - La fila correspondiente (`CHARGE_END` o similar) aparece al final de la tabla.
   - La fila nueva aparece con una animación de destello (flash morado).

3. Revocar la clave de un CP desde Central (opción 7).
   - **Resultado esperado:** Aparece `KEY_REVOKED` en la tabla en tiempo real.

4. Provocar un fallo de autenticación: arrancar un Monitor con credenciales incorrectas.
   - **Resultado esperado:** Aparece `AUTH_FAIL` en tiempo real.

**Resultado esperado:** Todas las acciones del sistema se reflejan en el front sin recargar.

---

## PRUEBA 4 — Front web: filtros

**Objetivo:** Los filtros funcionan sobre el historial mostrado.

**Pasos:**

1. Con datos en la tabla, seleccionar un tipo de evento en el desplegable (ej. `AUTH_SUCCESS`).
   - **Resultado esperado:** Solo se muestran filas de ese tipo. El contador se actualiza.

2. Pulsar "Limpiar filtros" → todas las filas vuelven a aparecer.

3. Verificar que las nuevas entradas SSE **también respetan los filtros activos** (si hay filtro `AUTH_FAIL` activo y llega un `AUTH_SUCCESS`, este no se muestra).

**Resultado esperado:** Filtros funcionan en tiempo real sobre la tabla.

---

## PRUEBA 5 — Front web: resiliencia

**Objetivo:** El front se recupera si Central cae y vuelve.

**Escenario A — Central cae:**
1. Cerrar Central con `Ctrl+C`.
2. **Resultado esperado:** El indicador cambia a punto rojo + "Sin conexión". Aparece banner de error con la URL.

3. Reiniciar Central.
4. **Resultado esperado:** El front se reconecta solo (en ≤3s), el punto vuelve a verde, las nuevas entradas se reciben de nuevo.

**Escenario B — Despliegue distribuido:**
1. Abrir `audit.html?api=http://<IP_CENTRAL>:8000` desde otro equipo.
2. **Resultado esperado:** Mismo comportamiento que en local.

**Resultado esperado:** Reconexión automática sin recargar la página.

---

## Tabla resumen

| Criterio | Prueba |
|---|---|
| `GET /api/audit` devuelve JSON con todas las entradas | 1 |
| Filtros `?action=`, `?source=`, `?limit=` funcionan | 1 |
| Front muestra historial completo al abrir | 2 |
| Colores por tipo de evento | 2 |
| Nuevas entradas aparecen en tiempo real (SSE) | 3 |
| Filtros funcionan sobre la tabla | 4 |
| Front se recupera si Central cae | 5 |
| URL `?api=` permite despliegue distribuido | 5B |
