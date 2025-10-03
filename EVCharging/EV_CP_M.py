import sys
import socket
import time
import threading


CP_STATUS = "ACTIVE"
CP_ADDRESS = "c/Alicante 3"
CP_PRICE = "0.5"


def args():
    return sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4]), sys.argv[5]


def connect_central(central_ip, central_port, cp_id):
    central_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    central_conn.connect((central_ip, central_port))
    print(f"[Monitor] Conectado a Central {central_ip}:{central_port}")

    # Enviar AUTH al central con estado inicial
    msg = f"AUTH_{cp_id}_{CP_ADDRESS}_{CP_PRICE}_{CP_STATUS}"
    central_conn.sendall(msg.encode())

    # Esperar respuesta de Central
    response = central_conn.recv(1024).decode()
    print(f"[Monitor] Respuesta de Central: {response}")

    if response != "ACCEPTED":
        print("[Monitor] Conexión rechazada por Central. Cerrando...")
        central_conn.close()
        exit(1)

    return central_conn


def connect_engine(central_conn, engine_ip, engine_port, cp_id):
    global CP_STATUS

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.connect((engine_ip, engine_port))
        print(f"[Monitor] Conectado a Engine {engine_ip}:{engine_port}")

        while True:
            try:
                msg = f"STATUS_{cp_id}"
                client.sendall(msg.encode())
                new_status = client.recv(1024).decode()
                print(f"[Monitor] Estado recibido de Engine: {new_status}")

                if new_status and new_status != CP_STATUS:
                    print(f"[Monitor] Cambio detectado: {CP_STATUS} → {new_status}")
                    CP_STATUS = new_status

                    # Notificar a Central
                    msg = f"CHANGE_{cp_id}_{new_status}"
                    central_conn.sendall(msg.encode())

                time.sleep(1)
            except Exception as e:
                print(f"[Monitor] Error con Engine: {e}")
                break


def main(engine_ip, engine_port, central_ip, central_port, cp_id):
    central_conn = connect_central(central_ip, central_port, cp_id)

    # Crear hilo para monitorizar Engine
    threading.Thread(target=connect_engine, args=(central_conn, engine_ip, engine_port, cp_id), daemon=True).start()

    # Mantener CP_M vivo
    while True:
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            break


if __name__ == "__main__":
    engine_ip, engine_port, central_ip, central_port, cp_id = args()
    main(engine_ip, engine_port, central_ip, central_port, cp_id)
