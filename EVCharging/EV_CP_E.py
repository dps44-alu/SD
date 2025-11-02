import sys
import time
import socket
import threading
from kafka import KafkaProducer


ENGINE_IP = "0.0.0.0"
ENGINE_PORT = 6000      
CP_STATUS = "ACTIVE"
CP_PRICE = None
CP_ADDRESS = None
CP_ID = None
CURRENT_DRIVER = None
CHARGING_ACTIVE = False
CONFIG_RECEIVED = False
CURRENT_KWH = 0.0
CURRENT_COST = 0.0
STOP_CHARGE = False                 # Flag para detener carga en progreso
MANUALLY_STOPPED = False            # Flag para indicar que fue detenido por comando de Central
CHARGE_LOCK = threading.Lock()      # Lock para sincronizar operaciones de carga


def args():
    return sys.argv[1], int(sys.argv[2])


def simulate_failure():
    global CP_STATUS, MANUALLY_STOPPED
    # Solo permitir simulación de fallo si no está manualmente detenido
    if not MANUALLY_STOPPED:
        CP_STATUS = "OUT_OF_ORDER"
        print("[Engine] Estado cambiado manualmente a OUT_OF_ORDER (durante 3s)")
        time.sleep(3)
        CP_STATUS = "ACTIVE"
        print("\n[Engine] Estado restaurado automáticamente a ACTIVE")


def listen_keyboard():
    while True:
        input("[Engine] Pulsa ENTER para simular KO temporal (3s)\n")
        threading.Thread(target=simulate_failure, daemon=True).start()


def handle_charging(producer, driver_id, cp_id, duration):
    global CHARGING_ACTIVE, CP_STATUS, CP_PRICE, CURRENT_DRIVER, CURRENT_KWH, CURRENT_COST, STOP_CHARGE, MANUALLY_STOPPED
    
    with CHARGE_LOCK:
        CHARGING_ACTIVE = True
        CURRENT_DRIVER = driver_id
        STOP_CHARGE = False  # Resetear flag al inicio
    
    total_kwh = 0
    total_cost = 0
    
    print(f"[Engine] Iniciando carga para {driver_id} durante {duration}s a {CP_PRICE}€/kWh")
    
    # Solo cambiar a BUSY si no está manualmente detenido
    if not MANUALLY_STOPPED:
        CP_STATUS = "BUSY"
    
    charge_interrupted = False
    interruption_reason = ""
    
    for i in range(duration):
        # Verificar condiciones de parada
        with CHARGE_LOCK:
            if STOP_CHARGE:
                charge_interrupted = True
                interruption_reason = "comando STOP de Central"
                print(f"[Engine] Carga interrumpida por {interruption_reason}")
                break
        
        if not CHARGING_ACTIVE:
            charge_interrupted = True
            interruption_reason = "interrupción externa"
            print(f"[Engine] Carga interrumpida por {interruption_reason}")
            break
            
        # CORRECCIÓN: Verificar tanto OUT_OF_ORDER como BROKEN
        if CP_STATUS in ["OUT_OF_ORDER", "BROKEN"] and not MANUALLY_STOPPED:
            # Solo si es por avería temporal, no por comando STOP
            charge_interrupted = True
            interruption_reason = "avería del CP"
            print(f"[Engine] Carga interrumpida por {interruption_reason}")
            break
            
        time.sleep(1)
        total_kwh += 1
        total_cost = total_kwh * CP_PRICE
        
        CURRENT_KWH = total_kwh
        CURRENT_COST = total_cost
        
        consumption_msg = f"CONSUMPTION#{driver_id}#{cp_id}#{total_kwh:.2f}#{total_cost:.2f}"
        producer.send("consumo_cps", consumption_msg)
        producer.flush()
        print(f"[Engine] Consumo: {total_kwh:.2f} kWh, {total_cost:.2f}€")
    
    # Limpiar variables de carga
    with CHARGE_LOCK:
        CHARGING_ACTIVE = False
        STOP_CHARGE = False
    
    CURRENT_DRIVER = None
    CURRENT_KWH = 0.0
    CURRENT_COST = 0.0
    
    # Solo volver a ACTIVE si no fue detenido manualmente por comando STOP
    if not MANUALLY_STOPPED and CP_STATUS not in ["OUT_OF_ORDER", "BROKEN"]:
        CP_STATUS = "ACTIVE"
    elif MANUALLY_STOPPED:
        # CORRECCIÓN: Asegurar que permanece en BROKEN si fue detenido manualmente
        CP_STATUS = "BROKEN"
        print(f"[Engine] CP permanece en BROKEN por comando de Central")
    
    # Enviar mensaje de finalización
    if charge_interrupted:
        end_msg = f"CHARGE_INTERRUPTED#{driver_id}#{cp_id}#{total_kwh:.2f}#{total_cost:.2f}#{interruption_reason}"
        print(f"[Engine] Carga interrumpida. Consumo parcial: {total_kwh:.2f} kWh, {total_cost:.2f}€")
    else:
        end_msg = f"CHARGE_END#{driver_id}#{cp_id}#{total_kwh:.2f}#{total_cost:.2f}"
        print(f"[Engine] Carga finalizada. Total: {total_kwh:.2f} kWh, {total_cost:.2f}€")
    
    producer.send("consumo_cps", end_msg)
    producer.flush()


def handle_monitor(conn, addr, producer):
    global CP_ID, CP_PRICE, CP_ADDRESS, CP_STATUS, CONFIG_RECEIVED, CURRENT_DRIVER, CURRENT_KWH, CURRENT_COST, STOP_CHARGE, CHARGING_ACTIVE, MANUALLY_STOPPED
    last_status = ""

    while True:
        try:
            data = conn.recv(1024)
            if not data:
                break
            
            msg = data.decode()
            parts = msg.split("#")
            msg_type = parts[0]

            if msg_type == "STATUS":
                driver_str = CURRENT_DRIVER if CURRENT_DRIVER else "None"
                status_response = f"{CP_STATUS}#{driver_str}#{CURRENT_KWH:.2f}#{CURRENT_COST:.2f}"
                
                if last_status != status_response:
                    last_status = status_response
                    print(f"[Engine] Enviando estado al Monitor: {status_response}")
                
                conn.sendall(status_response.encode())
                
            elif msg_type == "SET_CONFIG":
                print(f"[Engine] Conexión desde {addr}")
                cp_id = parts[1]
                price = float(parts[2])
                address = parts[3]
                
                CP_ID = cp_id
                CP_PRICE = price
                CP_ADDRESS = address
                CONFIG_RECEIVED = True
                
                print(f"[Engine] Configuración recibida del Monitor:")
                print(f"         ID: {CP_ID}")
                print(f"         Dirección: {CP_ADDRESS}")
                print(f"         Precio: {CP_PRICE}€/kWh")
                print(f"         Estado: {CP_STATUS}")
                
                conn.sendall(b"CONFIG_OK")
                
            elif msg_type == "MANUAL_CHARGE":
                cp_id = parts[1]
                driver_id = parts[2]
                duration = int(parts[3])
                
                # Verificar que no está manualmente detenido
                if cp_id == CP_ID and CP_STATUS == "ACTIVE" and not CHARGING_ACTIVE and not MANUALLY_STOPPED:
                    print(f"[Engine] Carga manual aceptada:")
                    print(f"         Conductor: {driver_id}")
                    print(f"         Duración: {duration}s")
                    conn.sendall(b"CHARGE_ACCEPTED")
                    
                    accept_msg = f"ACCEPTED#{driver_id}#{cp_id}"
                    producer.send("respuestas_central", accept_msg)
                    producer.flush()
                    
                    threading.Thread(
                        target=handle_charging,
                        args=(producer, driver_id, cp_id, duration),
                        daemon=True
                    ).start()
                else:
                    if MANUALLY_STOPPED:
                        reason = "CP detenido por comando de Central (BROKEN)"
                    else:
                        reason = "CP ocupado o no disponible"
                    print(f"[Engine] Carga manual rechazada: {reason}")
                    conn.sendall(reason.encode())
            
            elif msg_type == "STOP":
                print(f"[Engine] Comando STOP recibido de Central")
                
                # Activar flag de parada manual
                MANUALLY_STOPPED = True
                
                # Si hay carga en progreso, activar flag para detenerla
                with CHARGE_LOCK:
                    if CHARGING_ACTIVE:
                        print(f"[Engine] Deteniendo carga en progreso para {CURRENT_DRIVER}...")
                        STOP_CHARGE = True
                
                # CORRECCIÓN: Cambiar estado a BROKEN (no OUT_OF_ORDER)
                CP_STATUS = "BROKEN"
                print(f"[Engine] Estado cambiado a BROKEN (Averiado)")
                print(f"[Engine] CP detenido manualmente - no aceptará nuevas cargas hasta RESUME")
                conn.sendall(b"STOP_OK")
            
            elif msg_type == "RESUME":
                print(f"[Engine] Comando RESUME recibido de Central")
                
                # Desactivar flag de parada manual
                MANUALLY_STOPPED = False
                
                # Limpiar flag de detención de carga
                with CHARGE_LOCK:
                    STOP_CHARGE = False
                
                # Cambiar estado a ACTIVE
                CP_STATUS = "ACTIVE"
                print(f"[Engine] Estado cambiado a ACTIVE")
                print(f"[Engine] CP reanudado - listo para aceptar cargas")
                conn.sendall(b"RESUME_OK")
                
        except Exception as e:
            print(f"[Engine] Error: {e}")
            break

    conn.close()


def listen_charge_requests(producer, broker_ip, broker_port):
    from kafka import KafkaConsumer
    
    print("[Engine] Esperando configuración del Monitor...")
    while not CONFIG_RECEIVED or CP_ID is None:
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
            
            # Verificar que no está manualmente detenido
            if cp_id == CP_ID and CP_STATUS == "ACTIVE" and not CHARGING_ACTIVE and not MANUALLY_STOPPED:
                confirm_msg = f"CHARGE_STARTED#{driver_id}#{cp_id}"
                producer.send("respuestas_engine", confirm_msg)
                producer.flush()
                
                threading.Thread(
                    target=handle_charging,
                    args=(producer, driver_id, cp_id, duration),
                    daemon=True
                ).start()
            else:
                if MANUALLY_STOPPED:
                    print(f"[Engine] Petición rechazada: CP detenido manualmente por Central (BROKEN)")
                else:
                    print(f"[Engine] Petición rechazada: CP no disponible o ya en uso")


def main(broker_ip, broker_port):
    producer = KafkaProducer(
        bootstrap_servers=f"{broker_ip}:{broker_port}",
        value_serializer=lambda v: v.encode("utf-8")
    )

    threading.Thread(target=listen_keyboard, daemon=True).start()
    
    print(f"[Engine] Iniciado. Escuchando en {ENGINE_IP}:{ENGINE_PORT}")
    print(f"         Estado inicial: {CP_STATUS}")
    
    threading.Thread(
        target=listen_charge_requests, 
        args=(producer, broker_ip, broker_port), 
        daemon=True
    ).start()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((ENGINE_IP, ENGINE_PORT))
        server.listen()

        while True:
            conn, addr = server.accept()
            threading.Thread(
                target=handle_monitor, 
                args=(conn, addr, producer), 
                daemon=True
            ).start()


if __name__ == "__main__":
    broker_ip, broker_port = args()
    main(broker_ip, broker_port)