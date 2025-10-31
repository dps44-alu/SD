import sys
import socket 
import json
import threading
import time
import tkinter as tk
from kafka import KafkaProducer, KafkaConsumer


CENTRAL_IP = "localhost"
DB_FILE = "db.json"
LABELS = {}                         # Diccionario de etiquetas Tkinter
ACTIVE_CONSUMPTION_THREADS = {}     # Hilos de consumo activos


# ---------------------------
# Funciones DB
# ---------------------------
# Carga y guarda la base de datos de CPs
def load_db ():
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
        
    except FileNotFoundError:
        return {"charging_points": [], "drivers": []}


# Guarda la base de datos de CPs
def save_db (data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)


# Actualiza la información de un CP
def update_charging_point (cp_id, new_status, driver_id = "", kwh_consumed = 0, money_consumed = 0):
    db = load_db()
    for cp in db["charging_points"]:
        if cp["id"] == cp_id:
            cp["status"] = new_status
            cp["driver"] = driver_id
            cp["kwh_consumed"] = kwh_consumed
            cp["money_consumed"] = money_consumed
            break

    save_db(db)


# Devuelve un CP
def get_charging_point (cp_id):
    db = load_db()
    for cp in db["charging_points"]:
        if cp["id"] == cp_id:
            return cp
        
    return None


# Añade un nuevo CP
def add_charging_point (cp_id, address, price, status):
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


# Devuelve todos los CPs
def list_charging_points ():
    db = load_db()
    return db["charging_points"]



# ---------------------------
# Panel Tkinter
# ---------------------------
# Colores de estado
status_colors = {
    "ACTIVE": "green",
    "OUT_OF_ORDER": "orange",
    "BUSY": "blue",
    "BROKEN": "red",
    "INACTIVE": "grey"
}


# Crea el panel de monitorización
def create_panel ():
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

        label = tk.Label(root, text = text, bg = color, fg = "white",
                         font = ("Arial", 12), width = 20, height = 8,
                         relief = "raised", borderwidth = 2)
        label.grid(row = r, column = c, padx = 5, pady = 5, sticky = "nsew")

        LABELS[cp["id"]] = label

    root.after(500, refresh_panel, root)
    root.mainloop()


# Refresca el panel periódicamente
def refresh_panel (root):
    cps = list_charging_points()
    for cp in cps:
        label = LABELS.get(cp["id"])
        if label:
            if cp["status"] == "BUSY":
                text = f"{cp['id']}\n{cp['address']}\n{cp['price']}€/kWh\n{cp['driver']}\n{cp['kwh_consumed']} kWh\n{cp['money_consumed']}€"
            else:
                text = f"{cp['id']}\n{cp['address']}\n{cp['price']}€/kWh\n{cp['driver']}"

            color = status_colors.get(cp["status"], "grey")
            label.config(text = text, bg = color)
    
    root.after(500, refresh_panel, root)


# Calcula y envía actualizaciones de consumo cada segundo
def consumption_updater (producer, driver_id, cp_id, duration = 5):
    global ACTIVE_CONSUMPTION_THREADS

    cp = get_charging_point(cp_id)
    if not cp:
        return
    
    price = float(cp["price"])
    total_kwh = 0
    total_cost = 0
    
    for i in range(duration):
        time.sleep(1)
        total_kwh += 1
        total_cost += price

        # Actualiza el consumo en la base de datos
        update_charging_point(cp_id, "BUSY", driver_id, total_kwh, total_cost)
        
        # Envia la actualización al conductor
        consumption_msg = f"CONSUMPTION#{driver_id}#{cp_id}#{total_kwh:.2f}#{total_cost:.2f}"
        producer.send("respuestas_central", consumption_msg)
        producer.flush()
        print(f"[Central] Enviando consumo a {driver_id}: {total_kwh:.2f} kWh, {total_cost:.2f}€")
    
    # Limpia el hilo del diccionario cuando termina
    if cp_id in ACTIVE_CONSUMPTION_THREADS:
        del ACTIVE_CONSUMPTION_THREADS[cp_id]



# ---------------------------
# Kafka Drivers
# ---------------------------
# Escucha las peticiones de los conductores
def handle_driver (broker_ip, broker_port):
    global ACTIVE_CONSUMPTION_THREADS

    consumer = KafkaConsumer(
        "peticiones_conductores",
        bootstrap_servers = f"{broker_ip}:{broker_port}",
        value_deserializer = lambda v: v.decode("utf-8"),
        group_id = "central"
    )

    producer = KafkaProducer(
        bootstrap_servers = f"{broker_ip}:{broker_port}",
        value_serializer = lambda v: v.encode("utf-8")
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
            available = False
            cps = list_charging_points()
            for cp in cps:
                if cp["id"] == cp_id and cp["status"] == "ACTIVE":
                    available = True
                    update_charging_point(cp_id, "BUSY", driver_id)
                    
                    # Iniciar hilo para enviar actualizaciones de consumo
                    consumption_thread = threading.Thread(
                        target = consumption_updater,
                        args = (producer, driver_id, cp_id, duration),
                        daemon = True
                    )

                    ACTIVE_CONSUMPTION_THREADS[cp_id] = consumption_thread
                    consumption_thread.start()
                    break

            if available:
                response = f"ACCEPTED#{driver_id}#{cp_id}"
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
# Lee argumentos
def args ():
    return int(sys.argv[1]), sys.argv[2], int(sys.argv[3])


# Resetea el estado de todos los CPs a INACTIVE al iniciar Central
def reset_charging_points ():
    db = load_db()
    for cp in db["charging_points"]:
        cp["status"] = "INACTIVE"
        cp["driver"] = ""
        cp["kwh_consumed"] = 0
    save_db(db)


# Autentica un CP
def cp_authentication (conn, cp_id, cp_address, cp_price, cp_status):
    for cp in list_charging_points():
        if cp["id"] == cp_id:
            return True
    
    return False


# Servidor principal de Central
def main (central_port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((CENTRAL_IP, central_port))
        server.listen()
        print(f"[Central] Esperando conexiones en {CENTRAL_IP}:{central_port}")

        while True:
            conn, addr = server.accept()
            with conn:
                print(f"[Central] Conexión recibida de {addr}")
                while True:
                    data = conn.recv(1024)
                    if not data:
                        break
                    msg = data.decode()
                    print(f"[Central] Mensaje: {msg}")

                    type, cp_id, cp_address, cp_price, cp_status = msg.split("#") 

                    if type == "AUTH":
                        if cp_authentication(conn, cp_id, cp_address, cp_price, cp_status):
                            print(f"[Central] CP autenticado: {cp_id}")
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
                                print(f"[Central] CP registrado: {cp_id}")
                                conn.sendall(b"ACCEPTED")
                                add_charging_point(cp_id, cp_address, cp_price, cp_status)

                    elif type == "CHANGE":
                        if cp_authentication(conn, cp_id, cp_address, cp_price, cp_status):
                            db = load_db()
                            current_driver = ""
                            for cp in db["charging_points"]:
                                if cp["id"] == cp_id:
                                    current_driver = cp.get("driver", "")
                                    break
                            
                            update_charging_point(cp_id, cp_status, current_driver)
                            print(f"[Central] Estado actualizado: {cp_id} → {cp_status}")


# Inicia el programa
if __name__ == "__main__":
    central_port, broker_ip, broker_port = args()

    reset_charging_points()

    threading.Thread(target = create_panel, daemon = True).start()

    threading.Thread(target = handle_driver, args = (broker_ip, broker_port), daemon = True).start()

    main(central_port)