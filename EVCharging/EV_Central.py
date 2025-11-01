import sys
import socket 
import json
import threading
import time
import tkinter as tk
from kafka import KafkaProducer, KafkaConsumer


CENTRAL_IP = "localhost"
DB_FILE = "db.json"
LABELS = {}
DB_LOCK = threading.Lock()  # Lock para acceso seguro a la BD


# ---------------------------
# Funciones DB
# ---------------------------
def load_db():
    with DB_LOCK:
        try:
            with open(DB_FILE, "r") as f:
                content = f.read()
                if not content.strip():  # Si el archivo está vacío
                    return {"charging_points": [], "drivers": []}
                return json.loads(content)
        except FileNotFoundError:
            return {"charging_points": [], "drivers": []}
        except json.JSONDecodeError:
            print("[Central] ⚠️ Error leyendo BD, retornando BD vacía")
            return {"charging_points": [], "drivers": []}


def save_db(data):
    with DB_LOCK:
        with open(DB_FILE, "w") as f:
            json.dump(data, f, indent=4)


def update_charging_point(cp_id, new_status, driver_id="", kwh_consumed=0, money_consumed=0):
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
    cps = list_charging_points()
    for cp in cps:
        label = LABELS.get(cp["id"])
        if label:
            if cp["status"] == "BUSY":
                text = f"{cp['id']}\n{cp['address']}\n{cp['price']}€/kWh\n{cp['driver']}\n{cp['kwh_consumed']} kWh\n{cp['money_consumed']}€"
            else:
                text = f"{cp['id']}\n{cp['address']}\n{cp['price']}€/kWh\n{cp['driver']}"

            color = status_colors.get(cp["status"], "grey")
            label.config(text=text, bg=color)
    
    root.after(500, refresh_panel, root)


# ---------------------------
# Kafka - Escuchar consumo de CPs
# ---------------------------
def listen_cp_consumption(broker_ip, broker_port):
    """Escucha las actualizaciones de consumo que envían los CPs"""
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
    
    print("[Central] Escuchando actualizaciones de consumo de CPs...")
    
    for msg in consumer:
        consumption = msg.value
        print(f"[Central] Actualización recibida: {consumption}")
        parts = consumption.split("#")
        
        if parts[0] == "CONSUMPTION":
            driver_id = parts[1]
            cp_id = parts[2]
            kwh = float(parts[3])
            cost = float(parts[4])
            
            # Actualizar BD
            update_charging_point(cp_id, "BUSY", driver_id, kwh, cost)
            
            # Reenviar al driver
            producer.send("respuestas_central", consumption)
            producer.flush()
            print(f"[Central] Consumo reenviado al driver: {kwh:.2f} kWh, {cost:.2f}€")
            
        elif parts[0] == "CHARGE_END":
            driver_id = parts[1]
            cp_id = parts[2]
            kwh = float(parts[3])
            cost = float(parts[4])
            
            print(f"[Central] Carga finalizada en {cp_id}: {kwh:.2f} kWh, {cost:.2f}€")

            update_charging_point(cp_id, "ACTIVE")
            
            # Enviar ticket final al driver
            ticket = f"TICKET#{driver_id}#{cp_id}#{kwh:.2f}#{cost:.2f}"
            producer.send("respuestas_central", ticket)
            producer.flush()


# ---------------------------
# Kafka - Drivers
# ---------------------------
def handle_driver(broker_ip, broker_port):
    """Escucha peticiones de drivers y delega al CP correspondiente"""
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

    print("[Central] Escuchando peticiones de drivers...")
    
    for msg in consumer:
        request = msg.value
        print(f"[Central] Petición recibida: {request}")
        parts = request.split("#")
        msg_type = parts[0]
        driver_id = parts[1]
        cp_id = parts[2]

        if msg_type == "REQUEST":
            duration = int(parts[3])
            cp = get_charging_point(cp_id)
            
            if cp and cp["status"] == "ACTIVE":
                # Marcar como BUSY
                update_charging_point(cp_id, "BUSY", driver_id)
                
                # Enviar petición al CP Engine para que inicie la carga
                charge_request = f"START_CHARGE#{driver_id}#{cp_id}#{duration}"
                producer.send("peticiones_carga", charge_request)
                producer.flush()
                print(f"[Central] Petición enviada al CP {cp_id}")
                
                # Confirmar al driver
                response = f"ACCEPTED#{driver_id}#{cp_id}"
                producer.send("respuestas_central", response)
                producer.flush()
            else:
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


def handle_monitor_connection(conn, addr):
    """Maneja las conexiones de los monitores en un hilo separado"""
    print(f"[Central] Conexión de Monitor desde {addr}")
    try:
        while True:
            data = conn.recv(1024)
            if not data:
                break
            msg = data.decode()
            print(f"[Central] Mensaje de Monitor: {msg}")

            parts = msg.split("#")
            msg_type = parts[0]

            # Manejar solicitud de configuración del Monitor
            if msg_type == "REQUEST_CONFIG":
                cp_id = parts[1]
                cp = get_charging_point(cp_id)
                
                if cp:
                    # Enviar configuración: CONFIG_OK#address#price#status
                    response = f"CONFIG_OK#{cp['address']}#{cp['price']}#{cp['status']}"
                    conn.sendall(response.encode())
                    print(f"[Central] Configuración enviada al Monitor para CP {cp_id}:")
                    print(f"          Dirección: {cp['address']}")
                    print(f"          Precio: {cp['price']}€/kWh")
                    print(f"          Estado: {cp['status']}")
                else:
                    # CP no encontrado en BD
                    conn.sendall(b"CONFIG_NOT_FOUND")
                    print(f"[Central] ⚠️ CP {cp_id} no encontrado en la base de datos")
                continue

            # Resto de mensajes (AUTH, CHANGE) requieren 5 partes
            if len(parts) < 5:
                continue
                
            cp_id = parts[1]
            cp_address = parts[2]
            cp_price = parts[3]
            cp_status = parts[4]

            if msg_type == "AUTH":
                if cp_authentication(conn, cp_id, cp_address, cp_price, cp_status):
                    print(f"[Central] CP autenticado: {cp_id} con precio {cp_price}€/kWh")
                    conn.sendall(b"ACCEPTED")
                    update_charging_point(cp_id, cp_status)
                else:
                    registered = False
                    for cp in list_charging_points():
                        if cp["address"] == cp_address:
                            registered = True
                            break 

                    if registered:  
                        print(f"[Central] CP denegado por dirección repetida: {cp_id}")
                        conn.sendall(b"REJECTED")
                    else:
                        print(f"[Central] CP registrado: {cp_id} con precio {cp_price}€/kWh")
                        conn.sendall(b"ACCEPTED")
                        add_charging_point(cp_id, cp_address, cp_price, cp_status)

            elif msg_type == "CHANGE":
                if cp_authentication(conn, cp_id, cp_address, cp_price, cp_status):
                    db = load_db()
                    current_driver = ""
                    for cp in db["charging_points"]:
                        if cp["id"] == cp_id:
                            current_driver = cp.get("driver", "")
                            break
                    
                    update_charging_point(cp_id, cp_status, current_driver)
                    print(f"[Central] Estado actualizado: {cp_id} → {cp_status}")
    except Exception as e:
        print(f"[Central] Error en conexión con Monitor: {e}")
    finally:
        conn.close()


def main(central_port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((CENTRAL_IP, central_port))
        server.listen()
        print(f"[Central] Esperando conexiones en {CENTRAL_IP}:{central_port}")

        while True:
            conn, addr = server.accept()
            # Crear un hilo para cada conexión de Monitor
            threading.Thread(
                target=handle_monitor_connection,
                args=(conn, addr),
                daemon=True
            ).start()


# Inicia el programa
if __name__ == "__main__":
    central_port, broker_ip, broker_port = args()

    reset_charging_points()

    threading.Thread(target=create_panel, daemon=True).start()
    
    # Escuchar peticiones de drivers
    threading.Thread(target=handle_driver, args=(broker_ip, broker_port), daemon=True).start()
    
    # Escuchar actualizaciones de consumo de los CPs
    threading.Thread(target=listen_cp_consumption, args=(broker_ip, broker_port), daemon=True).start()

    main(central_port)