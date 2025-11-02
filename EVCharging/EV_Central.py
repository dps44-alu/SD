import sys
import socket 
import json
import threading
import time
import tkinter as tk
from kafka import KafkaProducer, KafkaConsumer
import os
import signal


CENTRAL_IP = "localhost"
DB_FILE = "db.json"
LABELS = {}
DB_LOCK = threading.Lock()
ACTIVE_CONNECTIONS = {}
CONNECTIONS_LOCK = threading.Lock()
MESSAGE_BUFFER = []
MESSAGE_LOCK = threading.Lock()
IN_MENU = False
SHUTDOWN_FLAG = False
MENU_REFRESH_EVENT = threading.Event()  # Evento para controlar refresco del menú


# ---------------------------
# Sistema de mensajes
# ---------------------------
# Añade un mensaje al buffer para mostrar de forma ordenada
def log_message(message):
    with MESSAGE_LOCK:
        MESSAGE_BUFFER.append(f"[{time.strftime('%H:%M:%S')}] {message}")
    # Señalar que hay mensajes nuevos
    MENU_REFRESH_EVENT.set()


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
    return db["charging_points"]


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
            conn.settimeout(5)  # Timeout de 5 segundos
            
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
                # Simplemente refrescar para mostrar mensajes
                continue
                
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
    "ACTIVE": "green",
    "OUT_OF_ORDER": "orange",
    "BUSY": "blue",
    "BROKEN": "red",
    "INACTIVE": "grey"
}


def create_panel():
    global LABELS

    root = tk.Tk()
    root.title("SD EV Charging Solution - Monitorization Panel")

    rows, cols = 2, 3
    cps = list_charging_points()

    for i, cp in enumerate(cps):
        r, c = i // cols, i % cols
        
        if cp["status"] == "BUSY":
            text = f"{cp['id']}\n{cp['address']}\n{cp['price']}€/kWh\n{cp['driver']}\n{cp['kwh_consumed']} kWh\n{cp['money_consumed']}€"
        elif cp["status"] in ["OUT_OF_ORDER", "BROKEN"]:
            text = f"{cp['id']}\n{cp['address']}\n{cp['price']}€/kWh\nFuera de Servicio"
        else:
            text = f"{cp['id']}\n{cp['address']}\n{cp['price']}€/kWh\n{cp['driver']}"
        
        color = status_colors.get(cp["status"], "grey")

        label = tk.Label(root, text=text, bg=color, fg="white",
                         font=("Arial", 12), width=20, height=8,
                         relief="raised", borderwidth=2)
        label.grid(row=r, column=c, padx=5, pady=5, sticky="nsew")

        LABELS[cp["id"]] = label

    root.after(500, refresh_panel, root)
    root.mainloop()


def refresh_panel(root):
    if SHUTDOWN_FLAG:
        root.quit()
        return
        
    cps = list_charging_points()
    for cp in cps:
        label = LABELS.get(cp["id"])
        if label:
            if cp["status"] == "BUSY":
                text = f"{cp['id']}\n{cp['address']}\n{cp['price']}€/kWh\n{cp['driver']}\n{cp['kwh_consumed']} kWh\n{cp['money_consumed']}€"
            elif cp["status"] in ["OUT_OF_ORDER", "BROKEN"]:
                text = f"{cp['id']}\n{cp['address']}\n{cp['price']}€/kWh\nFuera de Servicio"
            else:
                text = f"{cp['id']}\n{cp['address']}\n{cp['price']}€/kWh\n{cp['driver']}"

            color = status_colors.get(cp["status"], "grey")
            label.config(text=text, bg=color)
    
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
            
        consumption = msg.value
        parts = consumption.split("#")
        
        if parts[0] == "CONSUMPTION":
            driver_id = parts[1]
            cp_id = parts[2]
            kwh = float(parts[3])
            cost = float(parts[4])
            
            # Solo actualizar si NO está en estado BROKEN
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

            # Solo cambiar a ACTIVE si NO está en estado BROKEN
            cp = get_charging_point(cp_id)
            if cp and cp["status"] != "BROKEN":
                update_charging_point(cp_id, "ACTIVE")
            
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
            
            # El estado ya fue actualizado por el comando STOP a BROKEN, mantenerlo
            # Solo enviar el ticket parcial al conductor
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
    return int(sys.argv[1]), sys.argv[2], int(sys.argv[3])


def reset_charging_points():
    db = load_db()
    for cp in db["charging_points"]:
        cp["status"] = "INACTIVE"
        cp["driver"] = ""
        cp["kwh_consumed"] = 0
        cp["money_consumed"] = 0
    save_db(db)


def cp_authentication(conn, cp_id, cp_address, cp_price, cp_status):
    for cp in list_charging_points():
        if cp["id"] == cp_id:
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

            if msg_type == "AUTH":
                if cp_authentication(conn, cp_id, cp_address, cp_price, cp_status):
                    log_message(f"Central: CP autenticado {cp_id}")
                    conn.sendall(b"ACCEPTED")
                    update_charging_point(cp_id, cp_status)
                    
                    with CONNECTIONS_LOCK:
                        ACTIVE_CONNECTIONS[cp_id] = conn
                else:
                    registered = False
                    for cp in list_charging_points():
                        if cp["address"] == cp_address:
                            registered = True
                            break 

                    if registered:  
                        log_message(f"Central: CP {cp_id} denegado (dirección repetida)")
                        conn.sendall(b"REJECTED")
                    else:
                        log_message(f"Central: CP registrado {cp_id}")
                        conn.sendall(b"ACCEPTED")
                        add_charging_point(cp_id, cp_address, cp_price, cp_status)
                        
                        with CONNECTIONS_LOCK:
                            ACTIVE_CONNECTIONS[cp_id] = conn

            elif msg_type == "CHANGE":
                if cp_authentication(conn, cp_id, cp_address, cp_price, cp_status):
                    # No actualizar si el estado en BD es BROKEN (esto previene que el Monitor sobreescriba el estado BROKEN)
                    cp = get_charging_point(cp_id)
                    if cp and cp["status"] == "BROKEN":
                        # Ignorar cambios de estado cuando está BROKEN
                        log_message(f"Central: Cambio de estado ignorado para {cp_id} (CP en BROKEN)")
                        continue
                    
                    db = load_db()
                    current_driver = ""
                    current_kwh = 0
                    current_cost = 0
                    
                    for cp in db["charging_points"]:
                        if cp["id"] == cp_id:
                            current_driver = cp.get("driver", "")
                            current_kwh = cp.get("kwh_consumed", 0)
                            current_cost = cp.get("money_consumed", 0)
                            break
                    
                    # Mantener el driver si el estado cambia a OUT_OF_ORDER desde BUSY
                    if cp_status == "OUT_OF_ORDER" and current_driver:
                        update_charging_point(cp_id, cp_status, current_driver, current_kwh, current_cost)
                    else:
                        update_charging_point(cp_id, cp_status, current_driver, current_kwh, current_cost)
                    
                    log_message(f"Central: Estado actualizado {cp_id} -> {cp_status}")
                    
    except Exception as e:
        log_message(f"Central: Error con Monitor: {e}")
    finally:
        if cp_id:
            with CONNECTIONS_LOCK:
                if cp_id in ACTIVE_CONNECTIONS:
                    del ACTIVE_CONNECTIONS[cp_id]
                    log_message(f"Central: Conexión eliminada CP {cp_id}")
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


if __name__ == "__main__":
    # Configurar manejador de señales
    signal.signal(signal.SIGINT, signal_handler)
    
    central_port, broker_ip, broker_port = args()

    reset_charging_points()

    threading.Thread(target=create_panel, daemon=True).start()
    
    threading.Thread(target=handle_driver, args=(broker_ip, broker_port), daemon=True).start()
    
    threading.Thread(target=listen_cp_consumption, args=(broker_ip, broker_port), daemon=True).start()
    
    threading.Thread(target=main, args=(central_port,), daemon=True).start()
    
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