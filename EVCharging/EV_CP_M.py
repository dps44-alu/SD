import sys
import socket
import time
import threading


CP_STATUS = None    # Ahora se obtiene del Engine
CP_ADDRESS = None   # Ahora se obtiene del Engine
CP_PRICE = None     # Ahora se obtiene del Engine


# ---------------------------
# Monitor CP
# ---------------------------
# Lee argumentos
def args():
    return sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4]), sys.argv[5]


# Obtiene toda la configuración del Engine
def get_config_from_engine(engine_ip, engine_port, cp_id):
    global CP_PRICE, CP_ADDRESS, CP_STATUS
    
    max_retries = 10
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                client.settimeout(2)
                client.connect((engine_ip, engine_port))
                
                # Solicitar configuración completa al Engine
                msg = f"REQUEST_CONFIG#{cp_id}"
                client.sendall(msg.encode())
                
                response = client.recv(1024).decode()
                parts = response.split("#")
                
                if parts[0] == "OK" and len(parts) == 4:
                    CP_PRICE = float(parts[1])
                    CP_ADDRESS = parts[2]
                    CP_STATUS = parts[3]
                    print(f"[Monitor] Configuración obtenida del Engine:")
                    print(f"          Dirección: {CP_ADDRESS}")
                    print(f"          Precio: {CP_PRICE}€/kWh")
                    print(f"          Estado: {CP_STATUS}")
                    return True
                    
        except Exception as e:
            retry_count += 1
            print(f"[Monitor] Intento {retry_count}/{max_retries} falló: {e}")
            time.sleep(1)
    
    print("[Monitor] No se pudo obtener la configuración del Engine")
    return False


# Se conecta y autentica con central
def connect_central(central_ip, central_port, cp_id):
    global CP_PRICE, CP_ADDRESS, CP_STATUS
    
    central_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    central_conn.connect((central_ip, central_port))
    print(f"[Monitor] Conectado a Central {central_ip}:{central_port}")

    # Enviar AUTH al central con toda la configuración obtenida del Engine
    msg = f"AUTH#{cp_id}#{CP_ADDRESS}#{CP_PRICE}#{CP_STATUS}"
    central_conn.sendall(msg.encode())
    print(f"[Monitor] Enviando AUTH a Central:")
    print(f"          ID: {cp_id}")
    print(f"          Dirección: {CP_ADDRESS}")
    print(f"          Precio: {CP_PRICE}€/kWh")
    print(f"          Estado: {CP_STATUS}")

    # Esperar respuesta de Central
    response = central_conn.recv(1024).decode()
    print(f"[Monitor] Respuesta de Central: {response}")

    if response != "ACCEPTED":
        print("[Monitor] Conexión rechazada por Central. Cerrando...")
        central_conn.close()
        exit(1)

    return central_conn


# Se conecta y monitoriza el Engine
def connect_engine(central_conn, engine_ip, engine_port, cp_id):
    global CP_STATUS

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        # Se conecta al Engine
        client.connect((engine_ip, engine_port))
        print(f"[Monitor] Conectado a Engine {engine_ip}:{engine_port}")

        while True:
            try:
                # Pregunta el estado al Engine
                msg = f"STATUS#{cp_id}"
                client.sendall(msg.encode())
                new_status = client.recv(1024).decode()
                print(f"[Monitor] Estado recibido de Engine: {new_status}")

                # Si ha cambiado, notifica a Central
                if new_status and new_status != CP_STATUS:
                    print(f"[Monitor] Cambio detectado: {CP_STATUS} → {new_status}")
                    CP_STATUS = new_status

                    # Notifica a Central
                    msg = f"CHANGE#{cp_id}#None#None#{new_status}"
                    central_conn.sendall(msg.encode())

                time.sleep(1)

            except Exception as e:
                print(f"[Monitor] Error con Engine: {e}")
                break


# Inicia la conexión con Central y el Engine
def main(engine_ip, engine_port, central_ip, central_port, cp_id):
    # Primero obtener toda la configuración del Engine
    print(f"[Monitor] Solicitando configuración al Engine...")
    if not get_config_from_engine(engine_ip, engine_port, cp_id):
        print("[Monitor] Error crítico: no se pudo obtener la configuración del Engine")
        return
    
    # Luego conectar con Central enviando toda la configuración obtenida
    central_conn = connect_central(central_ip, central_port, cp_id)

    # Crear hilo para monitorizar Engine
    threading.Thread(
        target=connect_engine, 
        args=(central_conn, engine_ip, engine_port, cp_id), 
        daemon=True
    ).start()

    # Mantener CP_M vivo
    while True:
        try:
            time.sleep(1)
        except KeyboardInterrupt:
            break


# Inicia el programa
if __name__ == "__main__":
    engine_ip, engine_port, central_ip, central_port, cp_id = args()
    main(engine_ip, engine_port, central_ip, central_port, cp_id)