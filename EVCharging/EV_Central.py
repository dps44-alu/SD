import sys
import socket
import json
import threading
import time
import tkinter as tk
from kafka import KafkaProducer, KafkaConsumer
import os
import signal
from cryptography.fernet import Fernet

from flask import Flask, request, jsonify
from flask_cors import CORS


app = Flask(__name__)
CORS(app)


CENTRAL_IP = "localhost"
DB_FILE = "db.json"
CREDENTIALS_FILE = "credentials.json"
AUDIT_LOG_FILE = "audit.log"
LABELS = {}
MESSAGE_WIDGET = None
DRIVERS_WIDGET = None
CHARGING_START_TIMES = {}
CHARGING_START_LOCK = threading.Lock()
DB_LOCK = threading.Lock()
ACTIVE_CONNECTIONS = {}
CONNECTIONS_LOCK = threading.Lock()
MESSAGE_BUFFER = []
MESSAGE_LOCK = threading.Lock()
IN_MENU = False
SHUTDOWN_FLAG = False
MENU_REFRESH_EVENT = threading.Event()

CP_KEYS = {}            # {cp_id: Fernet instance}
CP_KEYS_LOCK = threading.Lock()
PENDING_WEATHER_STOP = set()    # CPs that should stop after current charge ends


# ---------------------------
# Sistema de mensajes y auditoría
# ---------------------------
def log_message(message):
    with MESSAGE_LOCK:
        MESSAGE_BUFFER.append(f"[{time.strftime('%H:%M:%S')}] {message}")
    MENU_REFRESH_EVENT.set()


def audit(action, source, details=""):
    entry = f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {action:<20} | {source:<15} | {details}\n"
    try:
        with open(AUDIT_LOG_FILE, "a") as f:
            f.write(entry)
    except Exception:
        pass


def load_credentials():
    try:
        with open(CREDENTIALS_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


# Limpiar pantalla de forma multiplataforma
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


# Muestra todos los mensajes pendientes
def display_pending_messages():
    with MESSAGE_LOCK:
        if MESSAGE_BUFFER:
            print("\n" + "="*60)
            print("  MENSAJES DEL SISTEMA")
            print("="*60)

            for msg in MESSAGE_BUFFER:
                print(f"  {msg}")

            print("="*60)
            MESSAGE_BUFFER.clear()
            return True
        
    return False


# ---------------------------
# Funciones DB
# ---------------------------
def load_db():
    with DB_LOCK:
        try:
            with open(DB_FILE, "r") as f:
                content = f.read()

                if not content.strip():
                    return {"charging_points": [], "drivers": []}
                
                return json.loads(content)
            
        except FileNotFoundError:
            return {"charging_points": [], "drivers": []}
        
        except json.JSONDecodeError:
            log_message("Central: Error leyendo BD, retornando BD vacía")
            return {"charging_points": [], "drivers": []}


def save_db(data):
    with DB_LOCK:
        with open(DB_FILE, "w") as f:
            json.dump(data, f, indent=4)


def update_charging_point(cp_id, new_status, driver_id = "", kwh_consumed = 0, money_consumed = 0):
    db = load_db()
    for cp in db["charging_points"]:
        if cp["id"] == cp_id:
            cp["status"] = new_status
            cp["driver"] = driver_id
            cp["kwh_consumed"] = kwh_consumed
            cp["money_consumed"] = money_consumed
            break
    save_db(db)


def get_charging_point(cp_id):
    db = load_db()
    for cp in db["charging_points"]:
        if cp["id"] == cp_id:
            return cp
        
    return None


def add_charging_point(cp_id, address, price, status):
    db = load_db()
    db["charging_points"].append({
        "id": cp_id, 
        "address": address, 
        "price": price, 
        "status": status,
        "driver": "",
        "kwh_consumed": 0,
        "money_consumed": 0
    })
    save_db(db)


def list_charging_points():
    db = load_db()
    return sorted(db["charging_points"], key=lambda cp: cp["id"])


# ---------------------------
# Control de CPs
# ---------------------------
# Envía un comando (STOP o RESUME) a un CP específico
def send_command_to_cp(cp_id, command):
    with CONNECTIONS_LOCK:
        if cp_id not in ACTIVE_CONNECTIONS:
            log_message(f"Central: CP {cp_id} no está conectado")
            return False
        
        conn = ACTIVE_CONNECTIONS[cp_id]
    
    try:
        msg = f"COMMAND#{cp_id}#{command}"
        conn.sendall(msg.encode())
        log_message(f"Central: Comando {command} enviado a {cp_id}")
        
        # Esperar confirmación con timeout más largo
        try:
            # Guardar el timeout original
            original_timeout = conn.gettimeout()
            conn.settimeout(5)                      # Timeout de 5 segundos
            
            response = conn.recv(1024).decode()
            log_message(f"Central: Respuesta de {cp_id}: {response}")
            
            # Restaurar timeout original
            if original_timeout is not None:
                conn.settimeout(original_timeout)
            else:
                conn.settimeout(None)
            
            # Actualizar BD según el comando y la respuesta
            if "OK" in response:
                if command == "STOP":
                    # Obtener el driver actual antes de cambiar el estado
                    cp = get_charging_point(cp_id)
                    current_driver = cp.get("driver", "") if cp else ""
                    current_kwh = cp.get("kwh_consumed", 0) if cp else 0
                    current_cost = cp.get("money_consumed", 0) if cp else 0
                    # Cambiar a BROKEN (rojo) y mantener info de carga
                    update_charging_point(cp_id, "BROKEN", current_driver, current_kwh, current_cost)
                    log_message(f"Central: BD actualizada - {cp_id} → BROKEN (Averiado)")

                elif command == "RESUME":
                    update_charging_point(cp_id, "ACTIVE", "")
                    log_message(f"Central: BD actualizada - {cp_id} → ACTIVE")

                return True
            
            else:
                log_message(f"Central: Comando no confirmado por {cp_id}")
                return False
                
        except socket.timeout:
            log_message(f"Central: Timeout esperando respuesta de {cp_id}")
            return False
            
    except Exception as e:
        log_message(f"Central: Error enviando comando a {cp_id}: {e}")
        return False


# Para un punto de carga específico
def stop_charging_point(cp_id):
    log_message(f"Central: Parando CP {cp_id}")
    return send_command_to_cp(cp_id, "STOP")


# Reanuda un punto de carga específico
def resume_charging_point(cp_id):
    log_message(f"Central: Reanudando CP {cp_id}")
    return send_command_to_cp(cp_id, "RESUME")


# Para todos los puntos de carga
def stop_all_charging_points():
    cps = list_charging_points()
    stopped_count = 0
    for cp in cps:
        if stop_charging_point(cp["id"]):
            stopped_count += 1

    log_message(f"Central: {stopped_count}/{len(cps)} CPs detenidos")
    return stopped_count


# Reanuda todos los puntos de carga
def resume_all_charging_points():
    cps = list_charging_points()
    resumed_count = 0
    for cp in cps:
        if resume_charging_point(cp["id"]):
            resumed_count += 1

    log_message(f"Central: {resumed_count}/{len(cps)} CPs reanudados")
    return resumed_count


# ---------------------------
# Menú de control
# ---------------------------
# Muestra el menú de control de la central
def show_control_menu():
    clear_screen()
    
    # Mostrar mensajes pendientes ANTES del menú
    has_messages = display_pending_messages()
    
    if has_messages:
        print()  # Línea en blanco después de mensajes
    
    print(f"{'='*60}")
    print(f"  MENÚ DE CONTROL - CENTRAL")
    print(f"{'='*60}")
    print(f"  1. Parar un punto de carga específico")
    print(f"  2. Reanudar un punto de carga específico")
    print(f"  3. Parar TODOS los puntos de carga")
    print(f"  4. Reanudar TODOS los puntos de carga")
    print(f"  5. Ver estado de todos los CPs")
    print(f"  6. Actualizar (refrescar mensajes)")
    print(f"  7. Revocar clave de un CP")
    print(f"  8. Ver log de auditoría")
    print(f"  0. Salir del menú")
    print(f"{'='*60}")


# Bucle principal del menú de control
def control_menu_loop():
    global IN_MENU, SHUTDOWN_FLAG
    IN_MENU = True
    
    # Thread para monitorear mensajes nuevos
    def monitor_messages():
        while not SHUTDOWN_FLAG and IN_MENU:
            # Esperar hasta que haya un mensaje nuevo
            if MENU_REFRESH_EVENT.wait(timeout = 2):
                MENU_REFRESH_EVENT.clear()
    
    threading.Thread(target=monitor_messages, daemon=True).start()
    
    while not SHUTDOWN_FLAG:
        try:
            show_control_menu()
            
            print("\n  Selecciona una opción: ", end='', flush=True)
            option = input().strip()
            
            if option == "1":
                # Parar un CP específico
                clear_screen()
                display_pending_messages()
                
                cps = list_charging_points()
                print(f"\n  Puntos de carga disponibles:")
                for cp in cps:
                    print(f"    - {cp['id']} ({cp['status']})")
                
                cp_id = input("\n  Introduce el ID del CP a parar: ").strip()
                if cp_id:
                    print(f"\n  Enviando comando STOP a {cp_id}...")
                    if stop_charging_point(cp_id):
                        print(f"  CP {cp_id} detenido correctamente (estado: BROKEN)")
                    else:
                        print(f"  No se pudo detener el CP {cp_id}")
                else:
                    print(f"  ID vacío, operación cancelada")
                input("\n  Presiona ENTER para continuar...")
                
            elif option == "2":
                # Reanudar un CP específico
                clear_screen()
                display_pending_messages()
                
                cps = list_charging_points()
                print(f"\n  Puntos de carga disponibles:")
                for cp in cps:
                    print(f"    - {cp['id']} ({cp['status']})")
                
                cp_id = input("\n  Introduce el ID del CP a reanudar: ").strip()
                if cp_id:
                    print(f"\n  Enviando comando RESUME a {cp_id}...")
                    if resume_charging_point(cp_id):
                        print(f"  CP {cp_id} reanudado correctamente")
                    else:
                        print(f"  No se pudo reanudar el CP {cp_id}")
                else:
                    print(f"  ID vacío, operación cancelada")
                input("\n  Presiona ENTER para continuar...")
                
            elif option == "3":
                # Parar todos los CPs
                clear_screen()
                display_pending_messages()
                
                confirm = input("\n  ¿Seguro que deseas parar TODOS los CPs? (s/n): ").strip().lower()
                if confirm == 's':
                    print(f"\n  Deteniendo todos los puntos de carga...")
                    count = stop_all_charging_points()
                    print(f"  {count} puntos de carga detenidos")
                else:
                    print("  Operación cancelada")
                input("\n  Presiona ENTER para continuar...")
                
            elif option == "4":
                # Reanudar todos los CPs
                clear_screen()
                display_pending_messages()
                
                confirm = input("\n  ¿Seguro que deseas reanudar TODOS los CPs? (s/n): ").strip().lower()
                if confirm == 's':
                    print(f"\n  Reanudando todos los puntos de carga...")
                    count = resume_all_charging_points()
                    print(f"  {count} puntos de carga reanudados")
                else:
                    print("  Operación cancelada")
                input("\n  Presiona ENTER para continuar...")
                
            elif option == "5":
                # Ver estado de todos los CPs
                clear_screen()
                display_pending_messages()
                
                cps = list_charging_points()
                print(f"\n{'─'*60}")
                print(f"  ESTADO DE PUNTOS DE CARGA")
                print(f"{'─'*60}")
                for cp in cps:
                    with CONNECTIONS_LOCK:
                        connected = "Conectado" if cp["id"] in ACTIVE_CONNECTIONS else "Desconectado"
                    print(f"  {cp['id']:<10} - {cp['status']:<15} - {connected}")
                print(f"{'─'*60}")
                input("\n  Presiona ENTER para continuar...")
                
            elif option == "6":
                continue

            elif option == "7":
                # Revocar clave de un CP
                clear_screen()
                display_pending_messages()

                with CP_KEYS_LOCK:
                    active_keys = list(CP_KEYS.keys())

                if not active_keys:
                    print("\n  No hay CPs con clave activa")
                    input("\n  Presiona ENTER para continuar...")
                    continue

                print(f"\n  CPs con clave activa: {', '.join(active_keys)}")
                cp_id = input("\n  ID del CP al que revocar clave: ").strip()

                if cp_id in active_keys:
                    with CP_KEYS_LOCK:
                        del CP_KEYS[cp_id]
                    update_charging_point(cp_id, "OUT_OF_ORDER")
                    audit("KEY_REVOKED", "central_menu", f"cp_id={cp_id}")
                    log_message(f"Central: Clave revocada para {cp_id} → OUT_OF_ORDER")
                    print(f"  Clave de {cp_id} revocada. CP puesto en OUT_OF_ORDER.")
                else:
                    print(f"  CP '{cp_id}' no encontrado")
                input("\n  Presiona ENTER para continuar...")

            elif option == "8":
                # Ver log de auditoría
                clear_screen()
                print(f"\n{'─'*70}")
                print(f"  LOG DE AUDITORÍA")
                print(f"{'─'*70}")
                try:
                    with open(AUDIT_LOG_FILE, "r") as f:
                        lines = f.readlines()
                    last_lines = lines[-30:] if len(lines) > 30 else lines
                    for line in last_lines:
                        print(f"  {line}", end="")
                except FileNotFoundError:
                    print("  (sin entradas aún)")
                print(f"{'─'*70}")
                input("\n  Presiona ENTER para continuar...")

            elif option == "0":
                print(f"\n  Saliendo del menú de control...")
                break
                
            elif option:  # Solo mostrar error si se ingresó algo
                print(f"\n  Opción inválida")
                time.sleep(1)
                
        except KeyboardInterrupt:
            print(f"\n\n  Saliendo del menú de control...")
            SHUTDOWN_FLAG = True
            break
        except Exception as e:
            print(f"\n  Error: {e}")
            time.sleep(1)
    
    IN_MENU = False


# ---------------------------
# Panel Tkinter
# ---------------------------
status_colors = {
    "ACTIVE":       "#2e7d32",   # dark green
    "BUSY":         "#1565c0",   # blue
    "OUT_OF_ORDER": "#e65100",   # orange
    "BROKEN":       "#b71c1c",   # red
    "INACTIVE":     "#424242",   # dark grey
    "DISCONNECTED": "#424242",
}


def _cp_tile_content(cp):
    """Return (text, color) for a CP tile."""
    with CONNECTIONS_LOCK:
        connected = cp["id"] in ACTIVE_CONNECTIONS
    if not connected:
        return (f"{cp['id']}\n{cp['address']}\n{cp['price']}€/kWh\nDESCONECTADO",
                status_colors["DISCONNECTED"])
    status = cp["status"]
    if status == "BUSY":
        text = (f"{cp['id']}\n{cp['address']}\n{cp['price']}€/kWh\n"
                f"{cp['driver']}\n{cp['kwh_consumed']} kWh\n{cp['money_consumed']}€")
    elif status in ("OUT_OF_ORDER", "BROKEN"):
        text = f"{cp['id']}\n{cp['address']}\n{cp['price']}€/kWh\nFuera de Servicio"
    else:
        text = f"{cp['id']}\n{cp['address']}\n{cp['price']}€/kWh\n{status}"
    return text, status_colors.get(status, status_colors["INACTIVE"])


def _make_section(parent, title, text_height):
    """Create a labelled dark section with a Text widget + scrollbar. Returns Text widget."""
    frame = tk.Frame(parent, bg="#1e1e1e")
    tk.Label(frame, text=title, bg="#1e1e1e", fg="#888888",
             font=("Arial", 9, "bold")).pack(anchor="w", padx=6, pady=(6, 1))
    inner = tk.Frame(frame, bg="#1e1e1e")
    inner.pack(fill="both", expand=True, padx=6, pady=(0, 6))
    scroll = tk.Scrollbar(inner, bg="#3a3a3a", troughcolor="#2d2d2d",
                          activebackground="#555555", width=10)
    scroll.pack(side="right", fill="y")
    widget = tk.Text(inner, height=text_height, bg="#1a1a2e", fg="#c9d1d9",
                     font=("Consolas", 9), state="disabled", wrap="none",
                     borderwidth=0, relief="flat", insertbackground="white",
                     selectbackground="#264f78",
                     yscrollcommand=scroll.set)
    widget.pack(side="left", fill="both", expand=True)
    scroll.config(command=widget.yview)
    return frame, widget


def create_panel():
    global LABELS, MESSAGE_WIDGET, DRIVERS_WIDGET

    root = tk.Tk()
    root.title("SD EV Charging Solution - Monitorization Panel")
    root.configure(bg="#1e1e1e")

    cols = 3
    cps = list_charging_points()

    for c in range(cols):
        root.columnconfigure(c, weight=1)

    for i, cp in enumerate(cps):
        r, c = i // cols, i % cols
        text, color = _cp_tile_content(cp)
        label = tk.Label(root, text=text, bg=color, fg="white",
                         font=("Arial", 12), width=20, height=8,
                         relief="flat", borderwidth=0)
        label.grid(row=r, column=c, padx=4, pady=4, sticky="nsew")
        LABELS[cp["id"]] = label

    bottom_row = (max(len(cps) - 1, 0) // cols) + 1

    # --- ON GOING DRIVERS REQUESTS (first) ---
    drv_frame, DRIVERS_WIDGET = _make_section(root, "ON GOING DRIVERS REQUESTS", 5)
    drv_frame.grid(row=bottom_row, column=0, columnspan=cols,
                   padx=4, pady=(8, 2), sticky="ew")
    # monospace header/row tags
    DRIVERS_WIDGET.tag_configure("header", foreground="#58a6ff", font=("Consolas", 9, "bold"))
    DRIVERS_WIDGET.tag_configure("sep",    foreground="#30363d")
    DRIVERS_WIDGET.tag_configure("row",    foreground="#c9d1d9")
    DRIVERS_WIDGET.tag_configure("empty",  foreground="#484f58")

    # --- APPLICATION MESSAGES (second) ---
    msg_frame, MESSAGE_WIDGET = _make_section(root, "APPLICATION MESSAGES", 8)
    msg_frame.grid(row=bottom_row + 1, column=0, columnspan=cols,
                   padx=4, pady=(2, 8), sticky="ew")
    MESSAGE_WIDGET.tag_configure("ts",   foreground="#484f58")
    MESSAGE_WIDGET.tag_configure("ok",   foreground="#3fb950")
    MESSAGE_WIDGET.tag_configure("warn", foreground="#d29922")
    MESSAGE_WIDGET.tag_configure("err",  foreground="#f85149")
    MESSAGE_WIDGET.tag_configure("info", foreground="#8b949e")

    root.after(500, refresh_panel, root)
    root.mainloop()


def refresh_panel(root):
    if SHUTDOWN_FLAG:
        root.quit()
        return

    cps = list_charging_points()

    # CP tiles
    for cp in cps:
        label = LABELS.get(cp["id"])
        if label:
            text, color = _cp_tile_content(cp)
            label.config(text=text, bg=color)

    # ON GOING DRIVERS REQUESTS
    if DRIVERS_WIDGET:
        busy = [cp for cp in cps if cp.get("status") == "BUSY" and cp.get("driver")]
        with CHARGING_START_LOCK:
            start_times = dict(CHARGING_START_TIMES)
        DRIVERS_WIDGET.config(state="normal")
        DRIVERS_WIDGET.delete("1.0", "end")
        if busy:
            hdr = f"  {'CONDUCTOR':<16} {'CP':<8} {'INICIO':<10} {'kWh':>6}  {'COSTE':>8}\n"
            DRIVERS_WIDGET.insert("end", hdr, "header")
            DRIVERS_WIDGET.insert("end", "  " + "─" * 54 + "\n", "sep")
            for cp in busy:
                start = start_times.get(cp["id"], "--:--:--")
                line = (f"  {cp['driver']:<16} {cp['id']:<8} {start:<10}"
                        f" {cp['kwh_consumed']:>6.2f}  {cp['money_consumed']:>7.2f}€\n")
                DRIVERS_WIDGET.insert("end", line, "row")
        else:
            DRIVERS_WIDGET.insert("end", "  (sin cargas activas)\n", "empty")
        DRIVERS_WIDGET.config(state="disabled")

    # APPLICATION MESSAGES
    if MESSAGE_WIDGET:
        with MESSAGE_LOCK:
            msgs = list(MESSAGE_BUFFER[-20:])
        MESSAGE_WIDGET.config(state="normal")
        MESSAGE_WIDGET.delete("1.0", "end")
        for m in msgs:
            # Split "[HH:MM:SS] rest"
            if m.startswith("[") and "]" in m:
                idx = m.index("]") + 1
                ts, rest = m[:idx], m[idx:]
            else:
                ts, rest = "", m
            if ts:
                MESSAGE_WIDGET.insert("end", ts, "ts")
            low = rest.lower()
            if any(w in low for w in ("error", "rechazad", "fallo", "broken", "fail")):
                tag = "err"
            elif any(w in low for w in ("alerta", "avería", "out_of_order", "interrumpid")):
                tag = "warn"
            elif any(w in low for w in ("autenticado", "aceptad", "active", "reanud", " ok")):
                tag = "ok"
            else:
                tag = "info"
            MESSAGE_WIDGET.insert("end", rest + "\n", tag)
        MESSAGE_WIDGET.see("end")
        MESSAGE_WIDGET.config(state="disabled")

    root.after(500, refresh_panel, root)


# ---------------------------
# Kafka - Escuchar consumo de CPs
# ---------------------------
# Escucha las actualizaciones de consumo que envían los CPs
def listen_cp_consumption(broker_ip, broker_port):
    consumer = KafkaConsumer(
        "consumo_cps",
        bootstrap_servers=f"{broker_ip}:{broker_port}",
        value_deserializer=lambda v: v.decode("utf-8"),
        group_id="central-consumption"
    )
    
    producer = KafkaProducer(
        bootstrap_servers=f"{broker_ip}:{broker_port}",
        value_serializer=lambda v: v.encode("utf-8")
    )
    
    log_message("Central: Escuchando actualizaciones de consumo de CPs")

    for msg in consumer:
        if SHUTDOWN_FLAG:
            break

        raw = msg.value
        # Format: "cp_id#<fernet_token>" or plain text (legacy/unencrypted)
        try:
            sep = raw.index("#")
            cp_id_prefix = raw[:sep]
            token = raw[sep+1:]
            with CP_KEYS_LOCK:
                fernet = CP_KEYS.get(cp_id_prefix)
            if fernet:
                consumption = fernet.decrypt(token.encode()).decode()
            else:
                consumption = raw
        except Exception:
            consumption = raw

        parts = consumption.split("#")
        
        if parts[0] == "CONSUMPTION":
            driver_id = parts[1]
            cp_id = parts[2]
            kwh = float(parts[3])
            cost = float(parts[4])

            cp = get_charging_point(cp_id)
            if cp and cp["status"] != "BROKEN":
                update_charging_point(cp_id, "BUSY", driver_id, kwh, cost)

            producer.send("respuestas_central", consumption)
            producer.flush()
            log_message(f"Central: Consumo en {cp_id}: {kwh:.2f} kWh, {cost:.2f}€")
            
        elif parts[0] == "CHARGE_END":
            driver_id = parts[1]
            cp_id = parts[2]
            kwh = float(parts[3])
            cost = float(parts[4])

            log_message(f"Central: Carga finalizada en {cp_id}: {kwh:.2f} kWh, {cost:.2f}€")
            audit("CHARGE_END", cp_id, f"driver={driver_id} kwh={kwh:.2f} cost={cost:.2f}")

            cp = get_charging_point(cp_id)
            if cp and cp["status"] != "BROKEN":
                if cp_id in PENDING_WEATHER_STOP:
                    PENDING_WEATHER_STOP.discard(cp_id)
                    update_charging_point(cp_id, "OUT_OF_ORDER")
                    stop_charging_point(cp_id)
                    log_message(f"Central: {cp_id} → OUT_OF_ORDER (alerta climática pendiente)")
                else:
                    with CONNECTIONS_LOCK:
                        monitor_connected = cp_id in ACTIVE_CONNECTIONS
                    if monitor_connected:
                        update_charging_point(cp_id, "ACTIVE")
                    else:
                        update_charging_point(cp_id, "INACTIVE")
                        log_message(f"Central: {cp_id} → INACTIVE (Monitor desconectado)")

            with CHARGING_START_LOCK:
                CHARGING_START_TIMES.pop(cp_id, None)

            ticket = f"TICKET#{driver_id}#{cp_id}#{kwh:.2f}#{cost:.2f}"
            producer.send("respuestas_central", ticket)
            producer.flush()

        elif parts[0] == "CHARGE_INTERRUPTED":
            driver_id = parts[1]
            cp_id = parts[2]
            kwh = float(parts[3])
            cost = float(parts[4])
            reason = parts[5] if len(parts) > 5 else "motivo desconocido"
            
            log_message(f"Central: Carga interrumpida en {cp_id}: {kwh:.2f} kWh, {cost:.2f}€ - {reason}")
            
            with CHARGING_START_LOCK:
                CHARGING_START_TIMES.pop(cp_id, None)

            ticket = f"CHARGE_INTERRUPTED#{driver_id}#{cp_id}#{kwh:.2f}#{cost:.2f}#{reason}"
            producer.send("respuestas_central", ticket)
            producer.flush()


# ---------------------------
# Kafka - Drivers
# ---------------------------
# Escucha peticiones de drivers y delega al CP correspondiente
def handle_driver(broker_ip, broker_port):
    consumer = KafkaConsumer(
        "peticiones_conductores",
        bootstrap_servers=f"{broker_ip}:{broker_port}",
        value_deserializer=lambda v: v.decode("utf-8"),
        group_id="central"
    )

    producer = KafkaProducer(
        bootstrap_servers=f"{broker_ip}:{broker_port}",
        value_serializer=lambda v: v.encode("utf-8")
    )

    log_message("Central: Escuchando peticiones de drivers")
    
    for msg in consumer:
        if SHUTDOWN_FLAG:
            break
            
        request = msg.value
        parts = request.split("#")
        msg_type = parts[0]
        driver_id = parts[1]
        cp_id = parts[2]

        if msg_type == "REQUEST":
            duration = int(parts[3])
            cp = get_charging_point(cp_id)
            
            log_message(f"Central: Petición de {driver_id} para {cp_id} ({duration}s)")
            
            if cp and cp["status"] == "ACTIVE":
                update_charging_point(cp_id, "BUSY", driver_id)
                with CHARGING_START_LOCK:
                    CHARGING_START_TIMES[cp_id] = time.strftime("%H:%M:%S")

                charge_request = f"START_CHARGE#{driver_id}#{cp_id}#{duration}"
                producer.send("peticiones_carga", charge_request)
                producer.flush()
                log_message(f"Central: Petición aceptada y enviada a {cp_id}")
                
                response = f"ACCEPTED#{driver_id}#{cp_id}"
                producer.send("respuestas_central", response)
                producer.flush()
            else:
                log_message(f"Central: Petición rechazada - {cp_id} no disponible")
                response = f"REJECTED#{driver_id}#{cp_id}"
                producer.send("respuestas_central", response)
                producer.flush()

        elif msg_type == "RELEASE":
            update_charging_point(cp_id, "ACTIVE", "")
            response = f"RELEASED#{driver_id}#{cp_id}"
            producer.send("respuestas_central", response)
            producer.flush()


# ---------------------------
# Servidor Central
# ---------------------------
def args():
    central_port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    broker_ip    = sys.argv[2]      if len(sys.argv) > 2 else 'localhost'
    broker_port  = int(sys.argv[3]) if len(sys.argv) > 3 else 9092
    return central_port, broker_ip, broker_port


def reset_charging_points():
    db = load_db()
    for cp in db["charging_points"]:
        cp["status"] = "INACTIVE"
        cp["driver"] = ""
        cp["kwh_consumed"] = 0
        cp["money_consumed"] = 0
    save_db(db)


def cp_authentication(cp_id, username, password):
    creds = load_credentials()
    stored = creds.get(cp_id)
    if stored and stored.get("username") == username and stored.get("password") == password:
        return True
    return False


# Maneja las conexiones de los monitores en un hilo separado
def handle_monitor_connection(conn, addr):
    log_message(f"Central: Conexión de Monitor desde {addr}")
    cp_id = None
    
    try:
        while not SHUTDOWN_FLAG:
            try:
                conn.settimeout(1.0)  # Timeout para poder revisar SHUTDOWN_FLAG
                data = conn.recv(1024)
            except socket.timeout:
                continue
            except Exception as e:
                break
                
            if not data:
                break
                
            msg = data.decode()
            parts = msg.split("#")
            msg_type = parts[0]

            if msg_type == "REQUEST_CONFIG":
                cp_id = parts[1]
                cp = get_charging_point(cp_id)
                
                if cp:
                    response = f"CONFIG_OK#{cp['address']}#{cp['price']}#{cp['status']}"
                    conn.sendall(response.encode())
                    log_message(f"Central: Config enviada a Monitor CP {cp_id}")
                else:
                    conn.sendall(b"CONFIG_NOT_FOUND")
                    log_message(f"Central: CP {cp_id} no encontrado en BD")
                continue

            if len(parts) < 5:
                continue

            cp_id = parts[1]
            cp_address = parts[2]
            cp_price = parts[3]
            cp_status = parts[4]
            username = parts[5] if len(parts) > 5 else ""
            password = parts[6] if len(parts) > 6 else ""

            if msg_type == "AUTH":
                source_ip = addr[0] if addr else "unknown"
                auth_ok = cp_authentication(cp_id, username, password)

                if auth_ok:
                    # Generate per-CP symmetric key
                    key = Fernet.generate_key()
                    fernet = Fernet(key)
                    with CP_KEYS_LOCK:
                        CP_KEYS[cp_id] = fernet

                    response = f"ACCEPTED#{key.decode()}"
                    conn.sendall(response.encode())
                    update_charging_point(cp_id, cp_status)

                    with CONNECTIONS_LOCK:
                        ACTIVE_CONNECTIONS[cp_id] = conn

                    log_message(f"Central: CP autenticado {cp_id}")
                    audit("AUTH_SUCCESS", source_ip, f"cp_id={cp_id} user={username}")
                else:
                    # CP may not have credentials yet (first registration path)
                    cp_exists = any(cp["id"] == cp_id for cp in list_charging_points())
                    addr_taken = any(cp["address"] == cp_address for cp in list_charging_points())

                    if cp_exists or addr_taken:
                        conn.sendall(b"REJECTED")
                        log_message(f"Central: CP {cp_id} rechazado (credenciales inválidas)")
                        audit("AUTH_FAIL", source_ip, f"cp_id={cp_id} user={username}")
                    else:
                        # New CP — accept without credentials (will register via Registry)
                        key = Fernet.generate_key()
                        fernet = Fernet(key)
                        with CP_KEYS_LOCK:
                            CP_KEYS[cp_id] = fernet

                        response = f"ACCEPTED#{key.decode()}"
                        conn.sendall(response.encode())
                        add_charging_point(cp_id, cp_address, cp_price, cp_status)

                        with CONNECTIONS_LOCK:
                            ACTIVE_CONNECTIONS[cp_id] = conn

                        log_message(f"Central: CP nuevo registrado {cp_id}")
                        audit("AUTH_NEW_CP", source_ip, f"cp_id={cp_id}")

            elif msg_type == "CHANGE":
                cp_exists = any(cp["id"] == cp_id for cp in list_charging_points())
                if cp_exists:
                    cp = get_charging_point(cp_id)
                    if not cp:
                        continue
                    # Never let the Monitor overwrite BROKEN — only STOP/RESUME commands do that
                    if cp["status"] == "BROKEN":
                        continue
                    # Never let the Monitor reset BUSY to ACTIVE — only CHARGE_END/INTERRUPTED do that
                    if cp["status"] == "BUSY" and cp_status == "ACTIVE":
                        continue

                    current_driver = cp.get("driver", "")
                    current_kwh = cp.get("kwh_consumed", 0)
                    current_cost = cp.get("money_consumed", 0)

                    update_charging_point(cp_id, cp_status, current_driver, current_kwh, current_cost)
                    log_message(f"Central: Estado actualizado {cp_id} -> {cp_status}")
                    
    except Exception as e:
        log_message(f"Central: Error con Monitor: {e}")

    finally:
        if cp_id:
            with CONNECTIONS_LOCK:
                if cp_id in ACTIVE_CONNECTIONS:
                    del ACTIVE_CONNECTIONS[cp_id]
            # Mark INACTIVE so no new charges are accepted while Monitor is down
            cp = get_charging_point(cp_id)
            if cp:
                update_charging_point(
                    cp_id, "INACTIVE",
                    cp.get("driver", ""),
                    cp.get("kwh_consumed", 0),
                    cp.get("money_consumed", 0)
                )
            log_message(f"Central: CP {cp_id} desconectado → INACTIVE")
        conn.close()


def main(central_port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((CENTRAL_IP, central_port))
        server.listen()
        server.settimeout(1.0)  # Timeout para permitir shutdown
        log_message(f"Central: Servidor escuchando en {CENTRAL_IP}:{central_port}")

        while not SHUTDOWN_FLAG:
            try:
                conn, addr = server.accept()
                threading.Thread(
                    target=handle_monitor_connection,
                    args=(conn, addr),
                    daemon=True
                ).start()

            except socket.timeout:
                continue

            except Exception as e:
                if not SHUTDOWN_FLAG:
                    log_message(f"Central: Error aceptando conexión: {e}")


# Manejador de señal para Ctrl+C
def signal_handler(sig, frame):
    global SHUTDOWN_FLAG
    print("\n[Central] Señal de interrupción recibida. Cerrando sistema...")
    SHUTDOWN_FLAG = True


# Endpoint para recibir alertas de EV_W -> {"cp_id": "ALC1", "alert_type": "ALERT|CANCEL", "reason": "..."}
@app.route('/weather/alert', methods=['POST'])
def weather_alert():
    try:
        data = request.json
        cp_id = data.get("cp_id")
        alert_type = data.get("alert_type")
        reason = data.get("reason", "")
        
        if not cp_id or not alert_type:
            return jsonify({"status": "ERROR", "message": "Faltan datos"}), 400
        
        cp = get_charging_point(cp_id)
        if not cp:
            return jsonify({"status": "ERROR", "message": "CP no encontrado"}), 404
        
        if alert_type == "ALERT":
            log_message(f"Central: Alerta climática en {cp_id} - {reason}")
            audit("WEATHER_ALERT", "EV_W", f"cp_id={cp_id} reason={reason}")

            if cp["status"] == "BUSY":
                # Let the current charge finish, then stop
                PENDING_WEATHER_STOP.add(cp_id)
                log_message(f"Central: {cp_id} está BUSY — se detendrá al terminar la carga")
                return jsonify({"status": "SUCCESS", "action": "STOP_PENDING"}), 200
            else:
                if stop_charging_point(cp_id):
                    log_message(f"Central: {cp_id} detenido por alerta climática")
                    return jsonify({"status": "SUCCESS", "action": "CP_STOPPED"}), 200
                else:
                    return jsonify({"status": "ERROR", "message": "No se pudo detener CP"}), 500

        elif alert_type == "CANCEL":
            log_message(f"Central: Alerta cancelada en {cp_id} - {reason}")
            audit("WEATHER_CANCEL", "EV_W", f"cp_id={cp_id}")
            PENDING_WEATHER_STOP.discard(cp_id)

            if resume_charging_point(cp_id):
                log_message(f"Central: {cp_id} reanudado tras normalización")
                return jsonify({"status": "SUCCESS", "action": "CP_RESUMED"}), 200
            else:
                return jsonify({"status": "ERROR", "message": "No se pudo reanudar CP"}), 500
        
        return jsonify({"status": "SUCCESS"}), 200
        
    except Exception as e:
        log_message(f"Central: Error procesando alerta climática: {e}")
        return jsonify({"status": "ERROR", "message": str(e)}), 500
    

# GET /api/charging_points
# Devuelve todos los puntos de carga con su estado actual
@app.route('/api/charging_points', methods=['GET'])
def get_all_charging_points():
    try:
        cps = list_charging_points()
        
        # Añadir info de conexión
        with CONNECTIONS_LOCK:
            for cp in cps:
                cp['connected'] = cp['id'] in ACTIVE_CONNECTIONS
        
        return jsonify({
            "status": "SUCCESS",
            "data": cps,
            "count": len(cps)
        }), 200
        
    except Exception as e:
        log_message(f"Central API: Error obteniendo CPs: {e}")
        return jsonify({"status": "ERROR", "message": str(e)}), 500


# GET /api/charging_points/<cp_id>
# Devuelve detalle de un CP específico
@app.route('/api/charging_points/<cp_id>', methods=['GET'])
def get_charging_point_detail(cp_id):
    try:
        cp = get_charging_point(cp_id)
        
        if not cp:
            return jsonify({"status": "ERROR", "message": "CP no encontrado"}), 404
        
        # Añadir info de conexión
        with CONNECTIONS_LOCK:
            cp['connected'] = cp_id in ACTIVE_CONNECTIONS
        
        return jsonify({
            "status": "SUCCESS",
            "data": cp
        }), 200
        
    except Exception as e:
        log_message(f"Central API: Error obteniendo CP {cp_id}: {e}")
        return jsonify({"status": "ERROR", "message": str(e)}), 500


# GET /api/drivers
# Devuelve todos los conductores registrados
@app.route('/api/drivers', methods=['GET'])
def get_all_drivers():
    try:
        db = load_db()
        drivers = db.get("drivers", [])
        
        return jsonify({
            "status": "SUCCESS",
            "data": drivers,
            "count": len(drivers)
        }), 200
        
    except Exception as e:
        log_message(f"Central API: Error obteniendo drivers: {e}")
        return jsonify({"status": "ERROR", "message": str(e)}), 500


# GET /api/system/status
# Devuelve estado general del sistema
@app.route('/api/system/status', methods=['GET'])
def get_system_status():
    try:
        cps = list_charging_points()
        db = load_db()
        
        # Contar estados
        status_count = {
            "ACTIVE": 0,
            "BUSY": 0,
            "OUT_OF_ORDER": 0,
            "BROKEN": 0,
            "INACTIVE": 0
        }
        
        for cp in cps:
            status = cp.get("status", "INACTIVE")
            status_count[status] = status_count.get(status, 0) + 1
        
        with CONNECTIONS_LOCK:
            connected_cps = len(ACTIVE_CONNECTIONS)
        
        return jsonify({
            "status": "SUCCESS",
            "data": {
                "total_cps": len(cps),
                "connected_cps": connected_cps,
                "status_breakdown": status_count,
                "total_drivers": len(db.get("drivers", [])),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            }
        }), 200
        
    except Exception as e:
        log_message(f"Central API: Error obteniendo estado del sistema: {e}")
        return jsonify({"status": "ERROR", "message": str(e)}), 500


# GET /api/messages
# Devuelve los mensajes del sistema (últimos 50)
@app.route('/api/messages', methods=['GET'])
def get_system_messages():
    try:
        with MESSAGE_LOCK:
            # Devolver copia de los últimos 50 mensajes
            recent_messages = MESSAGE_BUFFER[-50:] if len(MESSAGE_BUFFER) > 50 else MESSAGE_BUFFER.copy()
        
        return jsonify({
            "status": "SUCCESS",
            "data": recent_messages,
            "count": len(recent_messages)
        }), 200
        
    except Exception as e:
        return jsonify({"status": "ERROR", "message": str(e)}), 500


# GET /api/health
# Verifica que el API está funcionando
@app.route('/api/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "SUCCESS",
        "message": "API Central funcionando correctamente",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
    }), 200


# Ejecuta el servidor Flask para el API REST
def run_api_server(port=8000):
    import logging
    
    # Desactivar logs de Flask/Werkzeug
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)             # Solo mostrar errores críticos
    
    log_message(f"Central: API REST iniciada en puerto {port}")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    # Configurar manejador de señales
    signal.signal(signal.SIGINT, signal_handler)
    
    central_port, broker_ip, broker_port = args()

    audit("SYSTEM_START", "central", f"port={central_port} broker={broker_ip}:{broker_port}")
    reset_charging_points()

    threading.Thread(target=create_panel, daemon=True).start()
    
    threading.Thread(target=handle_driver, args=(broker_ip, broker_port), daemon=True).start()
    
    threading.Thread(target=listen_cp_consumption, args=(broker_ip, broker_port), daemon=True).start()
    
    threading.Thread(target=main, args=(central_port,), daemon=True).start()

    threading.Thread(target=run_api_server, args=(8000,), daemon=True).start()
    
    time.sleep(2)
    
    clear_screen()
    print("\n" + "="*60)
    print("  EV CHARGING CENTRAL - SISTEMA INICIALIZADO")
    print("="*60)
    print("  Panel de monitorización activo")
    print("  Servidor de conexiones activo")
    print("  Sistema de mensajería Kafka activo")
    print("="*60)
    print("\n  Iniciando menú de control en 2 segundos...\n")
    time.sleep(2)
    
    try:
        control_menu_loop()
    except KeyboardInterrupt:
        print("\n[Central] Cerrando sistema...")
    finally:
        SHUTDOWN_FLAG = True
        time.sleep(1)
        print("[Central] Sistema cerrado correctamente.")