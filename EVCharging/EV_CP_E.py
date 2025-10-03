import sys
import socket
import threading


ENGINE_IP = "0.0.0.0"
ENGINE_PORT = 6000
CP_STATUS = "ACTIVE"


def args():
    return sys.argv[1], int(sys.argv[2])


def handle_client(conn, addr):
    print(f"[Engine] Conexión desde {addr}")

    while True:
        try:
            data = conn.recv(1024)
            if not data:
                break
            
            msg = data.decode()
            type, cp_id = msg.split("_") 

            print(f"[Engine] Recibido de {cp_id}: {msg}")

            if type == "STATUS":
                print(f"[Engine] Enviando estado a {cp_id}: {CP_STATUS}")
                conn.sendall(CP_STATUS.encode())
        except:
            break

    conn.close()


def main(broker_ip, broker_port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((ENGINE_IP, ENGINE_PORT))
        server.listen()
        print(f"[Engine] Escuchando en {ENGINE_IP}:{ENGINE_PORT}")

        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    broker_ip, broker_port = args()
    main(broker_ip, broker_port)
