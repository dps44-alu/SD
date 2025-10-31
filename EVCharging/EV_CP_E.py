import sys
import time
import socket
import threading
from kafka import KafkaProducer


ENGINE_IP = "0.0.0.0"
ENGINE_PORT = 6000      
CP_STATUS = "ACTIVE"
CP_PRICE = 0.5                  # Precio definido en el Engine
CP_ADDRESS = "c/Alicante 1"     # Dirección definida en el Engine
CP_ID = None
CURRENT_DRIVER = None
CHARGING_ACTIVE = False


# ---------------------------
# Engine CP
# ---------------------------
# Lee argumentos
def args():
    return sys.argv[1], int(sys.argv[2])


# Simula un fallo temporal
def simulate_failure():
    global CP_STATUS
    CP_STATUS = "OUT_OF_ORDER"
    print("[Engine] Estado cambiado manualmente a OUT_OF_ORDER (durante 3s)")
    time.sleep(3)
    CP_STATUS = "ACTIVE"
    print("\n[Engine] Estado restaurado automáticamente a ACTIVE")


# Escucha el teclado para simular un fallo temporal
def listen_keyboard():
    while True:
        input("Pulsa ENTER para simular KO temporal (3s): ")
        threading.Thread(target=simulate_failure, daemon=True).start()


# Maneja el proceso de carga y envío de consumo
def handle_charging(producer, driver_id, cp_id, duration):
    global CHARGING_ACTIVE, CP_STATUS, CP_PRICE
    
    CHARGING_ACTIVE = True
    total_kwh = 0
    total_cost = 0
    
    print(f"[Engine] Iniciando carga para {driver_id} durante {duration}s a {CP_PRICE}€/kWh")
    
    for i in range(duration):
        if CP_STATUS != "ACTIVE" or not CHARGING_ACTIVE:
            print(f"[Engine] Carga interrumpida. Estado: {CP_STATUS}")
            break
            
        time.sleep(1)
        total_kwh += 1
        total_cost = total_kwh * CP_PRICE
        
        # Enviar actualización de consumo a Central (para el panel)
        consumption_msg = f"CONSUMPTION#{driver_id}#{cp_id}#{total_kwh:.2f}#{total_cost:.2f}"
        producer.send("consumo_cps", consumption_msg)
        producer.flush()
        print(f"[Engine] Consumo: {total_kwh:.2f} kWh, {total_cost:.2f}€")
    
    CHARGING_ACTIVE = False
    
    # Notificar fin de carga
    end_msg = f"CHARGE_END#{driver_id}#{cp_id}#{total_kwh:.2f}#{total_cost:.2f}"
    producer.send("consumo_cps", end_msg)
    producer.flush()
    print(f"[Engine] Carga finalizada. Total: {total_kwh:.2f} kWh, {total_cost:.2f}€")


# Maneja la conexión con el monitor
def handle_monitor(conn, addr):
    global CP_ID, CP_PRICE, CP_ADDRESS, CP_STATUS
    
    print(f"[Engine] Conexión desde {addr}")

    while True:
        try:
            data = conn.recv(1024)
            if not data:
                break
            
            msg = data.decode()
            parts = msg.split("#")
            msg_type = parts[0]

            if msg_type == "STATUS":
                cp_id = parts[1]
                print(f"[Engine] Enviando estado a {cp_id}: {CP_STATUS}")
                conn.sendall(CP_STATUS.encode())
                
            elif msg_type == "REQUEST_CONFIG":
                # Monitor solicita toda la configuración del CP
                cp_id = parts[1]
                CP_ID = cp_id
                # Responder con toda la configuración: OK#precio#dirección#estado
                response = f"OK#{CP_PRICE}#{CP_ADDRESS}#{CP_STATUS}"
                conn.sendall(response.encode())
                print(f"[Engine] Configuración enviada al Monitor:")
                print(f"         ID: {CP_ID}")
                print(f"         Dirección: {CP_ADDRESS}")
                print(f"         Precio: {CP_PRICE}€/kWh")
                print(f"         Estado: {CP_STATUS}")
                
        except Exception as e:
            print(f"[Engine] Error: {e}")
            break

    conn.close()


# Escucha peticiones de carga desde Kafka
def listen_charge_requests(producer, broker_ip, broker_port):
    from kafka import KafkaConsumer
    
    # Esperar a que se configure el CP_ID
    while CP_ID is None:
        time.sleep(0.5)
    
    consumer = KafkaConsumer(
        "peticiones_carga",
        bootstrap_servers=f"{broker_ip}:{broker_port}",
        value_deserializer=lambda v: v.decode("utf-8"),
        group_id=f"engine-{CP_ID}"
    )
    
    print(f"[Engine] Escuchando peticiones de carga para {CP_ID}...")
    
    for msg in consumer:
        request = msg.value
        print(f"[Engine] Petición recibida: {request}")
        parts = request.split("#")
        
        if parts[0] == "START_CHARGE":
            driver_id = parts[1]
            cp_id = parts[2]
            duration = int(parts[3])
            
            if cp_id == CP_ID and CP_STATUS == "ACTIVE":
                global CURRENT_DRIVER
                CURRENT_DRIVER = driver_id
                
                # Confirmar inicio de carga
                confirm_msg = f"CHARGE_STARTED#{driver_id}#{cp_id}"
                producer.send("respuestas_engine", confirm_msg)
                producer.flush()
                
                # Iniciar proceso de carga en un hilo separado
                threading.Thread(
                    target=handle_charging,
                    args=(producer, driver_id, cp_id, duration),
                    daemon=True
                ).start()


# Abre el socket y comienza a escuchar
def main(broker_ip, broker_port):
    # Inicializar Kafka Producer
    producer = KafkaProducer(
        bootstrap_servers=f"{broker_ip}:{broker_port}",
        value_serializer=lambda v: v.encode("utf-8")
    )
    
    print(f"[Engine] Iniciado con configuración:")
    print(f"         Dirección: {CP_ADDRESS}")
    print(f"         Precio: {CP_PRICE}€/kWh")
    print(f"         Estado inicial: {CP_STATUS}")
    
    # Hilo para escuchar teclado
    threading.Thread(target=listen_keyboard, daemon=True).start()
    
    # Hilo para escuchar peticiones de carga (esperará a que se configure CP_ID)
    threading.Thread(
        target=listen_charge_requests, 
        args=(producer, broker_ip, broker_port), 
        daemon=True
    ).start()

    # Servidor socket para Monitor
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((ENGINE_IP, ENGINE_PORT))
        server.listen()
        print(f"[Engine] Escuchando en {ENGINE_IP}:{ENGINE_PORT}")

        while True:
            conn, addr = server.accept()
            threading.Thread(target=handle_monitor, args=(conn, addr), daemon=True).start()


# Inicia el programa
if __name__ == "__main__":
    broker_ip, broker_port = args()
    main(broker_ip, broker_port)