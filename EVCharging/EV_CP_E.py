import sys
import time
import socket
import threading
import os
from kafka import KafkaProducer
from cryptography.fernet import Fernet


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
STOP_CHARGE = False
MANUALLY_STOPPED = False
CHARGE_LOCK = threading.Lock()
FERNET = None
KEY_REVOKED_FLAG = False
LAST_CHARGE_END = None

ENGINE_MESSAGES = []
ENGINE_MESSAGES_LOCK = threading.Lock()


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def engine_log(msg):
    with ENGINE_MESSAGES_LOCK:
        ENGINE_MESSAGES.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        if len(ENGINE_MESSAGES) > 15:
            ENGINE_MESSAGES.pop(0)


def display_engine_screen():
    last_state = None
    while True:
        with ENGINE_MESSAGES_LOCK:
            msgs = list(ENGINE_MESSAGES)

        current_state = (
            CP_STATUS, CP_ID, CHARGING_ACTIVE,
            CURRENT_DRIVER, CURRENT_KWH, CURRENT_COST,
            tuple(msgs), KEY_REVOKED_FLAG
        )

        if current_state != last_state:
            last_state = current_state
            clear_screen()

            cp_label = CP_ID or "Sin configurar"
            print(f"{'='*60}")
            print(f"  ENGINE - {cp_label}")
            print(f"{'='*60}")
            print(f"  Estado : {CP_STATUS}")
            if CHARGING_ACTIVE and CURRENT_DRIVER:
                print(f"  Carga  : {CURRENT_DRIVER} | {CURRENT_KWH:.2f} kWh | {CURRENT_COST:.2f}€")
            else:
                print(f"  Carga  : Sin carga activa")
            print(f"{'─'*60}")

            if msgs:
                print(f"  MENSAJES:")
                for m in msgs[-10:]:
                    print(f"  {m}")
            else:
                print(f"  (sin mensajes)")

            if KEY_REVOKED_FLAG:
                print(f"{'!'*60}")
                print(f"  AVISO: CLAVE REVOCADA POR CENTRAL")
                print(f"  Mensajes Kafka no cifrados. Re-autenticate desde el Monitor.")
                print(f"{'!'*60}")

            print(f"{'='*60}")
            print(f"  >>> Pulsa ENTER para simular fallo temporal (3s) <<<")
            print(f"{'='*60}")

        time.sleep(0.5)


def args():
    broker_ip   = sys.argv[1] if len(sys.argv) > 1 else 'localhost'
    broker_port = int(sys.argv[2]) if len(sys.argv) > 2 else 9092
    engine_port = int(sys.argv[3]) if len(sys.argv) > 3 else 6000
    return broker_ip, broker_port, engine_port


def kafka_send(producer, topic, message):
    """Send message encrypted if key is available, else plain."""
    if FERNET and CP_ID:
        token = FERNET.encrypt(message.encode()).decode()
        payload = f"{CP_ID}#{token}"
    else:
        payload = message
    producer.send(topic, payload)
    producer.flush()


def simulate_failure():
    global CP_STATUS, MANUALLY_STOPPED
    if not MANUALLY_STOPPED:
        CP_STATUS = "OUT_OF_ORDER"
        engine_log("Fallo simulado → OUT_OF_ORDER (3s)")
        time.sleep(3)
        CP_STATUS = "ACTIVE"
        engine_log("Recuperado automáticamente → ACTIVE")


def listen_keyboard():
    while True:
        input()
        if not MANUALLY_STOPPED:
            threading.Thread(target=simulate_failure, daemon=True).start()
        else:
            engine_log("ENTER ignorado — CP detenido por Central (BROKEN)")


def handle_charging(producer, driver_id, cp_id, duration):
    global CHARGING_ACTIVE, CP_STATUS, CP_PRICE, CURRENT_DRIVER, CURRENT_KWH, CURRENT_COST, STOP_CHARGE, MANUALLY_STOPPED, LAST_CHARGE_END

    with CHARGE_LOCK:
        CHARGING_ACTIVE = True
        CURRENT_DRIVER = driver_id
        STOP_CHARGE = False
        LAST_CHARGE_END = None          # Nueva carga: descartar CHARGE_END anterior
    
    total_kwh = 0
    total_cost = 0
    
    engine_log(f"Iniciando carga: {driver_id} | {duration}s | {CP_PRICE}€/kWh")
    
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
                engine_log(f"Carga interrumpida: {interruption_reason}")
                break

        if not CHARGING_ACTIVE:
            charge_interrupted = True
            interruption_reason = "interrupción externa"
            engine_log(f"Carga interrumpida: {interruption_reason}")
            break

        if CP_STATUS in ["OUT_OF_ORDER", "BROKEN"] and not MANUALLY_STOPPED:
            charge_interrupted = True
            interruption_reason = "avería del CP"
            engine_log(f"Carga interrumpida: {interruption_reason}")
            break
            
        time.sleep(1)
        total_kwh += 1
        total_cost = total_kwh * CP_PRICE
        
        CURRENT_KWH = total_kwh
        CURRENT_COST = total_cost
        
        consumption_msg = f"CONSUMPTION#{driver_id}#{cp_id}#{total_kwh:.2f}#{total_cost:.2f}"
        kafka_send(producer, "consumo_cps", consumption_msg)
        engine_log(f"Consumo: {total_kwh:.2f} kWh | {total_cost:.2f}€")
    
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
        # Asegurar que permanece en BROKEN si fue detenido manualmente
        CP_STATUS = "BROKEN"
        engine_log("CP permanece en BROKEN por comando de Central")

    if charge_interrupted:
        end_msg = f"CHARGE_INTERRUPTED#{driver_id}#{cp_id}#{total_kwh:.2f}#{total_cost:.2f}#{interruption_reason}"
        engine_log(f"Carga interrumpida. Parcial: {total_kwh:.2f} kWh | {total_cost:.2f}€")
    else:
        end_msg = f"CHARGE_END#{driver_id}#{cp_id}#{total_kwh:.2f}#{total_cost:.2f}"
        engine_log(f"Carga finalizada. Total: {total_kwh:.2f} kWh | {total_cost:.2f}€")
    
    kafka_send(producer, "consumo_cps", end_msg)
    LAST_CHARGE_END = end_msg          # Guardar por si Central reinicia y necesita re-recibirlo


def handle_monitor(conn, addr, producer):
    global CP_ID, CP_PRICE, CP_ADDRESS, CP_STATUS, CONFIG_RECEIVED, CURRENT_DRIVER, CURRENT_KWH, CURRENT_COST, STOP_CHARGE, CHARGING_ACTIVE, MANUALLY_STOPPED, FERNET, LAST_CHARGE_END, KEY_REVOKED_FLAG
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
                    engine_log(f"Estado enviado al Monitor: {status_response}")

                conn.sendall(status_response.encode())

            elif msg_type == "SET_CONFIG":
                cp_id = parts[1]
                price = float(parts[2])
                address = parts[3]
                enc_key = parts[4] if len(parts) > 4 and parts[4] else None

                CP_ID = cp_id
                CP_PRICE = price
                CP_ADDRESS = address

                if enc_key:
                    FERNET = Fernet(enc_key.encode())
                    KEY_REVOKED_FLAG = False
                    engine_log("Clave de cifrado configurada")
                else:
                    FERNET = None

                CONFIG_RECEIVED = True
                engine_log(f"Config recibida: {CP_ID} | {CP_ADDRESS} | {CP_PRICE}€/kWh")
                conn.sendall(b"CONFIG_OK")

                # Si Central reinició durante una carga y perdió el CHARGE_END,
                # reenviarlo con la nueva clave para que el Driver reciba su ticket
                if LAST_CHARGE_END:
                    engine_log("Re-enviando CHARGE_END con nueva clave (recuperación)")
                    kafka_send(producer, "consumo_cps", LAST_CHARGE_END)

            elif msg_type == "KEY_REVOKED":
                KEY_REVOKED_FLAG = True
                engine_log("AVISO: Clave revocada por Central — re-autenticate desde el Monitor")
                conn.sendall(b"OK")

            elif msg_type == "MANUAL_CHARGE":
                cp_id = parts[1]
                driver_id = parts[2]
                duration = int(parts[3])

                # Verificar que no está manualmente detenido
                if cp_id == CP_ID and CP_STATUS == "ACTIVE" and not CHARGING_ACTIVE and not MANUALLY_STOPPED:
                    engine_log(f"Carga manual aceptada: {driver_id} | {duration}s")
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
                    engine_log(f"Carga manual rechazada: {reason}")
                    conn.sendall(reason.encode())

            elif msg_type == "STOP":
                MANUALLY_STOPPED = True

                with CHARGE_LOCK:
                    if CHARGING_ACTIVE:
                        engine_log(f"Deteniendo carga en progreso para {CURRENT_DRIVER}")
                        STOP_CHARGE = True

                CP_STATUS = "BROKEN"
                engine_log("Comando STOP recibido → BROKEN")
                conn.sendall(b"STOP_OK")

            elif msg_type == "RESUME":
                MANUALLY_STOPPED = False

                with CHARGE_LOCK:
                    STOP_CHARGE = False

                CP_STATUS = "ACTIVE"
                engine_log("Comando RESUME recibido → ACTIVE")
                conn.sendall(b"RESUME_OK")

        except Exception as e:
            engine_log(f"Error: {e}")
            break

    conn.close()


def listen_charge_requests(producer, broker_ip, broker_port):
    from kafka import KafkaConsumer
    
    engine_log("Esperando configuración del Monitor...")
    while not CONFIG_RECEIVED or CP_ID is None:
        time.sleep(0.5)

    consumer = KafkaConsumer(
        bootstrap_servers=f"{broker_ip}:{broker_port}",
        value_deserializer=lambda v: v.decode("utf-8"),
        group_id=f"engine-{CP_ID}",
        auto_offset_reset='latest'
    )
    consumer.subscribe(["peticiones_carga"])

    # Descartar mensajes anteriores al arranque (ej. START_CHARGE de sesión anterior)
    while not consumer.assignment():
        consumer.poll(timeout_ms=100)
    consumer.seek_to_end()

    engine_log(f"Escuchando peticiones de carga para {CP_ID}")

    for msg in consumer:
        request = msg.value
        engine_log(f"Petición recibida: {request}")
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
                    engine_log("Petición rechazada: CP detenido manualmente (BROKEN)")
                else:
                    engine_log("Petición rechazada: CP no disponible o ya en uso")


def main(broker_ip, broker_port, engine_port):
    producer = KafkaProducer(
        bootstrap_servers=f"{broker_ip}:{broker_port}",
        value_serializer=lambda v: v.encode("utf-8")
    )

    threading.Thread(target=listen_keyboard, daemon=True).start()
    threading.Thread(target=display_engine_screen, daemon=True).start()

    engine_log(f"Iniciado. Escuchando en {ENGINE_IP}:{engine_port} | Estado: {CP_STATUS}")

    threading.Thread(
        target=listen_charge_requests,
        args=(producer, broker_ip, broker_port),
        daemon=True
    ).start()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((ENGINE_IP, engine_port))
        server.listen()

        while True:
            conn, addr = server.accept()
            threading.Thread(
                target=handle_monitor, 
                args=(conn, addr, producer), 
                daemon=True
            ).start()


if __name__ == "__main__":
    broker_ip, broker_port, engine_port = args()
    main(broker_ip, broker_port, engine_port)