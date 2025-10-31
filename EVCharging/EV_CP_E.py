import sys
import time
import socket
import threading


ENGINE_IP = "0.0.0.0"   # Misma IP que Monitor
ENGINE_PORT = 6000      
CP_STATUS = "ACTIVE"


# ---------------------------
# Engine CP
# ---------------------------
# Lee argumentos
def args ():
    return sys.argv[1], int(sys.argv[2])


# Simula un fallo temporal
def simulate_failure ():
    global CP_STATUS
    CP_STATUS = "OUT_OF_ORDER"
    print("[Engine] Estado cambiado manualmente a OUT_OF_ORDER (durante 3s)")
    time.sleep(3)
    CP_STATUS = "ACTIVE"
    print("\n[Engine] Estado restaurado automáticamente a ACTIVE")


# Escucha el teclado para simular un fallo temporal
def listen_keyboard ():
    while True:
        input("Pulsa ENTER para simular KO temporal (3s): ")
        threading.Thread(target = simulate_failure, daemon = True).start()


# Maneja la conexión con el monitor y le manda actualizaciones de estado
def handle_monitor (conn, addr):
    print(f"[Engine] Conexión desde {addr}")

    while True:
        try:
            data = conn.recv(1024)
            if not data:
                break
            
            msg = data.decode()
            type, cp_id = msg.split("#")    # STATUS#<cp_id>

            print(f"[Engine] Recibido de {cp_id}: {msg}")       

            if type == "STATUS":
                print(f"[Engine] Enviando estado a {cp_id}: {CP_STATUS}")
                conn.sendall(CP_STATUS.encode())
        except:
            break

    conn.close()


# Abre el socket y comienza a escuchar
def main (broker_ip, broker_port):

    threading.Thread(target = listen_keyboard, daemon = True).start()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((ENGINE_IP, ENGINE_PORT))
        server.listen()
        print(f"[Engine] Escuchando en {ENGINE_IP}:{ENGINE_PORT}")

        while True:
            conn, addr = server.accept()
            threading.Thread(target = handle_monitor, args = (conn, addr), daemon = True).start()


# Inicia el programa
if __name__ == "__main__":
    broker_ip, broker_port = args()
    main(broker_ip, broker_port)
