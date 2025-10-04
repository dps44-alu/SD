import sys
import socket 
import json
import threading
import tkinter as tk


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

def update_charging_point(cp_id, new_status):
    db = load_db()
    for cp in db["charging_points"]:
        if cp["id"] == cp_id:
            cp["status"] = new_status
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


def create_panel():
    root = tk.Tk()
    root.title("SD EV Charging Solution - Monitorization Panel")

    labels = []  # guardamos los labels para poder actualizarlos

    def refresh():
        cps = list_charging_points()
        for i, cp in enumerate(cps):
            r = i // 3
            c = i % 3

            text = f"{cp['id']}\n{cp['address']}\n{cp['price']}€/KWh"
            color = status_colors.get(cp["status"], "white")  # si no se reconoce el estado = blanco

            if i < len(labels):
                labels[i].config(text=text, bg=color)   # actualizar label existente
            else:
                # crear label nuevo
                label = tk.Label(root, text=text, bg=color, fg="white",
                                 font=("Arial", 12), width=20, height=6,
                                 relief="raised", borderwidth=2)
                label.grid(row=r, column=c, padx=5, pady=5, sticky="nsew")
                labels.append(label)

        root.after(2000, refresh)   # volver a refrescar cada 2 segundos

    refresh()
    root.mainloop()



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


def main(central_port, broker_ip, broker_port):
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

    main(central_port, broker_ip, broker_port)
