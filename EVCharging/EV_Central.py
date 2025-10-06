import sys
import socket 
import json
import threading
import tkinter as tk
from kafka import KafkaProducer, KafkaConsumer


CENTRAL_IP = "localhost"
DB_FILE = "db.json"


# ---------------------------
# Funciones DB
# ---------------------------
def load_db():
    try:
        with open(DB_FILE, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {"charging_points": [], "drivers": []}

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=4)

def update_charging_point(cp_id, new_status, driver_id=""):
    db = load_db()
    for cp in db["charging_points"]:
        if cp["id"] == cp_id:
            cp["status"] = new_status
            cp["driver"] = driver_id
            break
    save_db(db)

def add_charging_point(cp_id, address, price, status):
    db = load_db()
    db["charging_points"].append({"id": cp_id, "address": address, "price": price, "status": status})
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
    "BUSY": "green",
    "BROKEN": "red",
    "INACTIVE": "grey"
}


labels = {}  # diccionario {cp_id: label}

def create_panel():
    root = tk.Tk()
    root.title("SD EV Charging Solution - Monitorization Panel")

    rows, cols = 2, 3
    cps = list_charging_points()

    for i, cp in enumerate(cps):
        r, c = i // cols, i % cols

        text = f"{cp['id']}\n{cp['address']}\n{cp['price']}€/KWh\n{cp.get('driver','')}"
        color = status_colors.get(cp["status"], "grey")

        label = tk.Label(root, text=text, bg=color, fg="white",
                         font=("Arial", 12), width=20, height=6,
                         relief="raised", borderwidth=2)
        label.grid(row=r, column=c, padx=5, pady=5, sticky="nsew")

        labels[cp["id"]] = label

    root.after(2000, refresh_panel, root)
    root.mainloop()

def refresh_panel(root):
    cps = list_charging_points()
    for cp in cps:
        label = labels.get(cp["id"])
        if label:
            text = f"{cp['id']}\n{cp['address']}\n{cp['price']}€/KWh\n{cp.get('driver','')}"
            color = status_colors.get(cp["status"], "grey")
            label.config(text=text, bg=color)
    root.after(2000, refresh_panel, root)



# ---------------------------
# Kafka Drivers
# ---------------------------
def drivers_kafka_listener(broker_ip, broker_port):
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
        type, driver_id, cp_id = parts

        if type == "REQUEST":
            available = False
            cps = list_charging_points()
            for cp in cps:
                if cp["id"] == cp_id and cp["status"] == "ACTIVE":
                    available = True
                    update_charging_point(cp_id, "BUSY", driver_id)
                    break

            if available:
                response = f"ACCEPTED#{driver_id}#{cp_id}"
            else:
                response = f"REJECTED#{driver_id}#{cp_id}"

        elif type == "RELEASE":
            update_charging_point(cp_id, "ACTIVE")
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
        cp["status"] = "INACTIVE"   # todos empiezan en gris
    save_db(db)


def cp_authentication(conn, cp_id, cp_address, cp_price, cp_status):
    for cp in list_charging_points():
        if cp["id"] == cp_id:
            return True
    
    return False


def main(central_port):
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
                            update_charging_point(cp_id, cp_status)
                            print(f"[Central] Estado actualizado: {cp_id} → {cp_status}")


if __name__ == "__main__":
    central_port, broker_ip, broker_port = args()

    reset_charging_points()

    threading.Thread(target=create_panel, daemon=True).start()

    threading.Thread(target=drivers_kafka_listener, args=(broker_ip, broker_port), daemon=True).start()

    main(central_port)
