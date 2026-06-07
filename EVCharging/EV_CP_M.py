import sys
import socket
import time
import threading
import os
import select
import json

import requests
import urllib3


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


CP_STATUS = None
CP_ADDRESS = None
CP_PRICE = None
CP_ID = None
CURRENT_DRIVER = None
CHARGING_INFO = {"kwh": 0, "cost": 0}
RUNNING = True
PAUSED = False
CP_USERNAME = None
CP_PASSWORD = None
ENCRYPTION_KEY = None

MESSAGE_BUFFER = []
MESSAGE_LOCK = threading.Lock()

REGISTRY_URL = "https://localhost:5001"
RECONNECT_EVENT = threading.Event()
RECONNECT_GEN = 0
KEY_REVOKED_FLAG = False
CENTRAL_CONN = None


def log_message(msg):
    with MESSAGE_LOCK:
        MESSAGE_BUFFER.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
        if len(MESSAGE_BUFFER) > 20:
            MESSAGE_BUFFER.pop(0)


# Limpiar pantalla de forma multiplataforma
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


# Obtener representación visual del estado
def get_status_display(status):
    status_map = {
        "ACTIVE": ("DISPONIBLE", "verde"),
        "BUSY": ("CARGANDO", "verde"),
        "OUT_OF_ORDER": ("FUERA DE SERVICIO", "naranja"),
        "BROKEN": ("AVERIADO", "rojo"),
        "INACTIVE": ("INACTIVO", "gris")
    }
    return status_map.get(status, ("DESCONOCIDO", "negro"))


# Mostrar pantalla de monitorización actualizada continuamente
def display_monitor_screen():
    last_state = None

    while RUNNING:
        if PAUSED:
            time.sleep(0.5)
            continue

        with MESSAGE_LOCK:
            msgs = list(MESSAGE_BUFFER)

        current_state = (
            CP_STATUS, CURRENT_DRIVER,
            CHARGING_INFO['kwh'], CHARGING_INFO['cost'],
            tuple(msgs)
        )

        if current_state != last_state:
            last_state = current_state
            clear_screen()

            status_text, color_text = get_status_display(CP_STATUS)

            print(f"{'='*70}")
            print(f"  MONITOR CP - {CP_ID}")
            print(f"{'='*70}")
            print(f"  Dirección : {CP_ADDRESS}")
            print(f"  Precio    : {CP_PRICE}€/kWh")
            print(f"  Estado    : {status_text} ({color_text})")
            print(f"{'='*70}")

            if CP_STATUS == "BUSY" and CURRENT_DRIVER:
                print(f"\n  CARGA EN PROGRESO")
                print(f"  {'-'*66}")
                print(f"    Conductor         : {CURRENT_DRIVER}")
                print(f"    Consumo actual    : {CHARGING_INFO['kwh']:.2f} kWh")
                print(f"    Importe acumulado : {CHARGING_INFO['cost']:.2f}€")
                print(f"  {'-'*66}")
            elif CP_STATUS == "ACTIVE":
                print(f"\n  Punto de carga listo para recibir solicitudes")
            elif CP_STATUS == "OUT_OF_ORDER":
                print(f"\n  Punto de carga fuera de servicio temporalmente")
            elif CP_STATUS == "BROKEN":
                print(f"\n  Punto de carga averiado - detenido por Central")
                print(f"  Requiere comando RESUME para volver a operar")
            elif CP_STATUS == "INACTIVE":
                print(f"\n  Punto de carga inactivo")

            if msgs:
                print(f"\n{'─'*70}")
                print(f"  MENSAJES DEL SISTEMA")
                print(f"{'─'*70}")
                for m in msgs[-6:]:
                    print(f"  {m}")

            if KEY_REVOKED_FLAG:
                print(f"\n  {'!'*66}")
                print(f"  AVISO: Clave revocada por Central.")
                print(f"  Mensajes Kafka no son comprensibles. Usa opcion 3 para re-autenticarte.")
                print(f"  {'!'*66}")

            print(f"\n{'='*70}")
            print(f"  1: carga manual  |  2: re-registrar  |  3: re-autenticar  |  0: salir")
            print(f"{'='*70}")

        time.sleep(0.5)


# Envía la configuración al Engine
def send_config_to_engine(engine_ip, engine_port, cp_id):
    global CP_PRICE, CP_ADDRESS
    
    max_retries = 10
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                client.settimeout(2)
                client.connect((engine_ip, engine_port))
                
                key_part = ENCRYPTION_KEY if ENCRYPTION_KEY else ""
                msg = f"SET_CONFIG#{cp_id}#{CP_PRICE}#{CP_ADDRESS}#{key_part}"
                client.sendall(msg.encode())
                
                response = client.recv(1024).decode()
                
                if response == "CONFIG_OK":
                    print(f"[Monitor] Configuración enviada correctamente al Engine")
                    return True
                    
        except Exception as e:
            retry_count += 1
            print(f"[Monitor] Intento {retry_count}/{max_retries} enviando config a Engine: {e}")
            time.sleep(1)
    
    print("[Monitor] No se pudo enviar la configuración al Engine")
    return False


# Se conecta y autentica con central
def connect_central(central_ip, central_port, cp_id):
    global CP_PRICE, CP_ADDRESS, CP_STATUS, ENCRYPTION_KEY

    central_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    central_conn.connect((central_ip, central_port))
    print(f"[Monitor] Conectado a Central {central_ip}:{central_port}")

    username = CP_USERNAME or ""
    password = CP_PASSWORD or ""
    msg = f"AUTH#{cp_id}#{CP_ADDRESS}#{CP_PRICE}#{CP_STATUS}#{username}#{password}"
    central_conn.sendall(msg.encode())
    print(f"[Monitor] Enviando AUTH a Central (user={username})")

    response = central_conn.recv(1024).decode()

    if response.startswith("ACCEPTED"):
        parts = response.split("#")
        if len(parts) == 2:
            ENCRYPTION_KEY = parts[1]
            print(f"[Monitor] Autenticado. Clave de cifrado recibida.")
            log_message("Autenticado en Central. Clave de cifrado recibida.")
        else:
            print(f"[Monitor] Autenticado (sin clave de cifrado).")
            log_message("Autenticado en Central.")
    else:
        print("[Monitor] Conexión rechazada por Central (credenciales inválidas).")
        central_conn.close()
        return None

    return central_conn


# Escucha comandos de Central (STOP, RESUME) y los reenvía al Engine
def listen_central_commands(central_conn, engine_ip, engine_port, cp_id):
    global CP_STATUS, RUNNING, KEY_REVOKED_FLAG
    
    print(f"[Monitor] Iniciando escucha de comandos de Central para CP {cp_id}...")
    
    while RUNNING:
        try:
            central_conn.settimeout(1.0)
            data = central_conn.recv(1024)
            
            if not data:
                if RUNNING:
                    log_message("Conexión con Central cerrada")
                    RECONNECT_EVENT.set()
                break
                
            msg = data.decode()
            parts = msg.split("#")

            if parts[0] == "KEY_REVOKED" and len(parts) > 1 and parts[1] == cp_id:
                KEY_REVOKED_FLAG = True
                log_message("AVISO: Clave revocada por Central. Usa opcion 3 para re-autenticarte.")
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as eng:
                        eng.settimeout(2)
                        eng.connect((engine_ip, engine_port))
                        eng.sendall(f"KEY_REVOKED#{cp_id}".encode())
                except Exception:
                    pass
                continue

            if len(parts) >= 3 and parts[0] == "COMMAND":
                cmd_cp_id = parts[1]
                command = parts[2]
                
                if cmd_cp_id == cp_id:
                    log_message(f"Comando recibido de Central: {command}")

                    try:
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as engine_client:
                            engine_client.settimeout(3)
                            engine_client.connect((engine_ip, engine_port))
                            engine_client.sendall(command.encode())

                            response = engine_client.recv(1024).decode()
                            central_conn.sendall(response.encode())

                            if command == "STOP":
                                CP_STATUS = "BROKEN"
                                log_message(f"CP {cp_id} detenido por Central → BROKEN")
                            elif command == "RESUME":
                                CP_STATUS = "ACTIVE"
                                log_message(f"CP {cp_id} reanudado por Central → ACTIVE")

                    except Exception as e:
                        log_message(f"Error reenviando comando al Engine: {e}")
                        central_conn.sendall(b"ERROR")
                        
        except socket.timeout:
            continue
        except Exception as e:
            if RUNNING:
                log_message(f"Error escuchando comandos de Central: {e}")
                RECONNECT_EVENT.set()
            break


# Se conecta y monitoriza el Engine, con reconexión automática si cae
def connect_engine(central_conn, engine_ip, engine_port, cp_id, gen=0):
    global CP_STATUS, CURRENT_DRIVER, CHARGING_INFO, RUNNING, RECONNECT_GEN

    while RUNNING and gen == RECONNECT_GEN:
        last_driver = ""
        last_charging_info = {"kwh": 0, "cost": 0}

        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                client.connect((engine_ip, engine_port))
                log_message(f"Conectado a Engine {engine_ip}:{engine_port}")

                # Re-enviar configuración al Engine (necesario tras reinicio)
                send_config_to_engine(engine_ip, engine_port, cp_id)

                while RUNNING and gen == RECONNECT_GEN:
                    try:
                        msg = f"STATUS#{cp_id}"
                        client.sendall(msg.encode())
                        response = client.recv(1024).decode()

                        parts = response.split("#")
                        new_status = parts[0]

                        if len(parts) >= 4:
                            new_driver = parts[1] if parts[1] != "None" else None
                            try:
                                new_kwh = float(parts[2])
                                new_cost = float(parts[3])

                                if (new_driver != last_driver or
                                        new_kwh != last_charging_info["kwh"] or
                                        new_cost != last_charging_info["cost"]):

                                    if new_driver and new_driver != last_driver:
                                        log_message(f"Carga iniciada: conductor {new_driver}")
                                    elif not new_driver and last_driver:
                                        log_message(f"Carga finalizada. Conductor {last_driver}")

                                    CURRENT_DRIVER = new_driver
                                    CHARGING_INFO["kwh"] = new_kwh
                                    CHARGING_INFO["cost"] = new_cost
                                    last_driver = new_driver
                                    last_charging_info = {"kwh": new_kwh, "cost": new_cost}
                            except Exception:
                                pass
                        else:
                            CURRENT_DRIVER = None
                            CHARGING_INFO = {"kwh": 0, "cost": 0}
                            last_driver = ""
                            last_charging_info = {"kwh": 0, "cost": 0}

                        if new_status and new_status != CP_STATUS:
                            log_message(f"Estado: {CP_STATUS} → {new_status}")
                            CP_STATUS = new_status
                            try:
                                central_conn.sendall(f"CHANGE#{cp_id}#None#None#{new_status}".encode())
                            except Exception:
                                if RUNNING and gen == RECONNECT_GEN:
                                    RECONNECT_EVENT.set()

                        time.sleep(1)

                    except Exception as e:
                        log_message(f"Engine caído: {e}")
                        break

                # Bucle interno terminado → Engine caído
                if RUNNING and gen == RECONNECT_GEN and CP_STATUS != "OUT_OF_ORDER":
                    log_message("Engine KO → notificando OUT_OF_ORDER a Central")
                    CP_STATUS = "OUT_OF_ORDER"
                    try:
                        central_conn.sendall(f"CHANGE#{cp_id}#None#None#OUT_OF_ORDER".encode())
                        log_message("OUT_OF_ORDER notificado a Central")
                    except Exception:
                        RECONNECT_EVENT.set()

        except Exception as e:
            # No se pudo conectar al Engine
            if RUNNING and gen == RECONNECT_GEN:
                if CP_STATUS != "OUT_OF_ORDER":
                    log_message(f"Engine no disponible: {e}")
                    CP_STATUS = "OUT_OF_ORDER"
                    try:
                        central_conn.sendall(f"CHANGE#{cp_id}#None#None#OUT_OF_ORDER".encode())
                    except Exception:
                        RECONNECT_EVENT.set()

        # Esperar antes de reintentar conexión al Engine
        if RUNNING and gen == RECONNECT_GEN:
            log_message("Reintentando conexión al Engine en 3s...")
            time.sleep(3)


# Cierra la conexión actual con Central para forzar re-autenticación
def trigger_reauth():
    global KEY_REVOKED_FLAG, CENTRAL_CONN
    KEY_REVOKED_FLAG = False
    log_message("Re-autenticación iniciada por usuario...")
    if CENTRAL_CONN:
        try:
            CENTRAL_CONN.shutdown(socket.SHUT_RDWR)
            CENTRAL_CONN.close()
        except Exception:
            pass
    RECONNECT_EVENT.set()
    print("\n[Monitor] Re-autenticación en curso. Observa el panel para ver el resultado.")




# Maneja la entrada del usuario de forma no bloqueante
def handle_user_input(engine_ip, engine_port):
    global RUNNING, CP_ID, PAUSED, CP_USERNAME, CP_PASSWORD

    while RUNNING:
        try:
            user_input = input()

            if user_input.strip() == "1":
                PAUSED = True
                request_manual_charge(engine_ip, engine_port)
                PAUSED = False
            elif user_input.strip() == "2":
                PAUSED = True
                success, username, password = show_registration_menu(CP_ID)
                if success:
                    CP_USERNAME = username
                    CP_PASSWORD = password
                    log_message("Re-registro completado. Usa opción 3 para re-autenticarte con Central.")
                PAUSED = False
            elif user_input.strip() == "3":
                trigger_reauth()
            elif user_input.strip() == "0":
                print(f"\n[Monitor] Cerrando Monitor...")
                RUNNING = False
                break

        except KeyboardInterrupt:
            print(f"\n\n[Monitor] Interrupción detectada. Cerrando...")
            RUNNING = False
            break
        except:
            pass


# Solicita una carga manual al Engine
def request_manual_charge(engine_ip, engine_port):
    global CP_ID, CP_STATUS
    
    clear_screen()
    print(f"\n{'─'*70}")
    print(f"  SOLICITAR CARGA MANUAL")
    print(f"{'─'*70}")
    
    # Verificar tanto BROKEN como OUT_OF_ORDER
    if CP_STATUS not in ["ACTIVE"]:
        print(f"  El CP no está disponible (Estado: {CP_STATUS})")
        if CP_STATUS == "BROKEN":
            print(f"  El CP fue detenido por Central - requiere comando RESUME")
        print(f"  No se puede iniciar una carga manual")
        input("\n  Presiona ENTER para continuar...")
        return
    
    # Solicitar ID del conductor
    driver_id = input("\n  ID del conductor: ").strip()
    
    if not driver_id:
        print("  ID de conductor vacío. Operación cancelada.")
        input("\n  Presiona ENTER para continuar...")
        return
    
    # Solicitar duración
    duration_input = input("  Duración de la carga en segundos [10]: ").strip()
    
    if not duration_input:
        duration = 10
    else:
        try:
            duration = int(duration_input)
            if duration <= 0:
                print("  Duración inválida, usando 10 segundos")
                duration = 10
        except ValueError:
            print("  Duración inválida, usando 10 segundos")
            duration = 10
    
    print(f"\n  Solicitando carga manual:")
    print(f"     Conductor: {driver_id}")
    print(f"     Duración: {duration} segundos")
    print(f"     Enviando al Engine...")
    
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(3)
            client.connect((engine_ip, engine_port))
            
            msg = f"MANUAL_CHARGE#{CP_ID}#{driver_id}#{duration}"
            client.sendall(msg.encode())
            
            response = client.recv(1024).decode()
            
            if response == "CHARGE_ACCEPTED":
                print(f"  Solicitud aceptada")
                print(f"  La carga comenzará en unos momentos...")
                print(f"  El conductor {driver_id} verá la carga en su aplicación")
                time.sleep(2)
            else:
                print(f"  Solicitud rechazada: {response}")
                log_message(f"Carga manual rechazada: {response}")
                input("\n  Presiona ENTER para continuar...")
    except Exception as e:
        print(f"  Error al comunicarse con el Engine: {e}")
        input("\n  Presiona ENTER para continuar...")




def save_local_credentials(cp_id, username, password):
    data = {"username": username, "password": password,
            "address": CP_ADDRESS, "price": CP_PRICE}
    try:
        with open(f"creds_{cp_id}.json", "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"[Monitor] Aviso: no se pudieron guardar credenciales: {e}")


def load_local_credentials(cp_id):
    try:
        with open(f"creds_{cp_id}.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


# Registra el CP en EV_Registry vía API REST
# Retorna (success, username, password)
def register_with_registry(registry_url, cp_id, address, price):
    try:
        print(f"[Monitor] Registrando CP {cp_id} en Registry...")

        response = requests.post(
            f"{registry_url}/register",
            json={"id": cp_id, "address": address, "price": price},
            verify=False,
            timeout=5
        )

        if response.status_code == 201:
            data = response.json()
            username = data['username']
            password = data['password']
            print(f"[Monitor] CP registrado exitosamente")
            print(f"          Username: {username}")
            return True, username, password

        elif response.status_code == 409:
            print(f"[Monitor] CP ya registrado. Borrando entrada anterior y re-registrando...")
            requests.delete(
                f"{registry_url}/register/{cp_id}",
                verify=False,
                timeout=5
            )
            return register_with_registry(registry_url, cp_id, address, price)

        else:
            print(f"[Monitor] Error en registro: {response.json()}")
            return False, None, None

    except Exception as e:
        print(f"[Monitor] Error conectando con Registry: {e}")
        return False, None, None
    

# Solicita datos de registro y registra el CP en Registry
def show_registration_menu(cp_id):
    global CP_ADDRESS, CP_PRICE

    while True:
        clear_screen()
        print(f"{'='*70}")
        print(f"  REGISTRO EN REGISTRY — CP {cp_id}")
        print(f"{'='*70}")
        CP_ADDRESS = input("  Dirección del CP: ").strip()
        try:
            CP_PRICE = float(input("  Precio (€/kWh): ").strip())
        except ValueError:
            print("  Precio inválido.")
            input("  Presiona ENTER para continuar...")
            continue

        success, username, password = register_with_registry(
            REGISTRY_URL, cp_id, CP_ADDRESS, CP_PRICE
        )
        if success:
            save_local_credentials(cp_id, username, password)
            return True, username, password
        print("\n  Error en el registro. Inténtalo de nuevo.")
        input("\n  Presiona ENTER para continuar...")


# Intenta reconectar con Central cuando la conexión se pierde
def reconnect_loop(engine_ip, engine_port, central_ip, central_port, cp_id):
    global RECONNECT_GEN, RUNNING, CENTRAL_CONN

    while RUNNING:
        if not RECONNECT_EVENT.wait(timeout=1.0):
            continue
        RECONNECT_EVENT.clear()
        if not RUNNING:
            break

        log_message("Central desconectada — reintentando conexión en 5s...")
        time.sleep(5)

        while RUNNING:
            try:
                new_conn = connect_central(central_ip, central_port, cp_id)
                if new_conn is None:
                    log_message("Reconexión fallida: autenticación rechazada. Reintentando en 5s...")
                    time.sleep(5)
                    continue
                CENTRAL_CONN = new_conn
                RECONNECT_GEN += 1
                gen = RECONNECT_GEN

                threading.Thread(
                    target=listen_central_commands,
                    args=(new_conn, engine_ip, engine_port, cp_id),
                    daemon=True
                ).start()
                threading.Thread(
                    target=connect_engine,
                    args=(new_conn, engine_ip, engine_port, cp_id, gen),
                    daemon=True
                ).start()

                log_message("Reconectado con Central")
                break

            except Exception as e:
                log_message(f"Reconexión fallida: {e}. Reintentando en 5s...")
                time.sleep(5)


# Función principal
def main(engine_ip, engine_port, central_ip, central_port, cp_id, registry_ip, registry_port):
    global CP_ID, RUNNING, CP_USERNAME, CP_PASSWORD, REGISTRY_URL, CENTRAL_CONN, CP_ADDRESS, CP_PRICE

    CP_ID = cp_id
    REGISTRY_URL = f"https://{registry_ip}:{registry_port}"

    print(f"[Monitor] Iniciando Monitor para CP: {cp_id}")

    creds = load_local_credentials(cp_id)
    if creds:
        CP_USERNAME = creds["username"]
        CP_PASSWORD = creds["password"]
        CP_ADDRESS  = creds.get("address", "")
        CP_PRICE    = creds.get("price", 0.0)
        print(f"[Monitor] Credenciales locales encontradas. Omitiendo registro.")
    else:
        print(f"\n[Monitor] CP {cp_id} no registrado. Introduce los datos de registro:")
        success, username, password = show_registration_menu(cp_id)
        CP_USERNAME = username
        CP_PASSWORD = password

    print(f"[Monitor] Enviando configuración al Engine...")
    if not send_config_to_engine(engine_ip, engine_port, cp_id):
        print("[Monitor] Error crítico: no se pudo configurar el Engine")
        return

    print(f"[Monitor] Autenticándose con Central...")
    central_conn = connect_central(central_ip, central_port, cp_id)
    CENTRAL_CONN = central_conn

    if central_conn is None:
        if creds:
            try:
                os.remove(f"creds_{cp_id}.json")
            except Exception:
                pass
            print(f"[Monitor] Credenciales almacenadas rechazadas por Central.")
            print(f"[Monitor] Archivo de credenciales eliminado. Reinicia para re-registrarte.")
        else:
            print(f"[Monitor] Autenticación rechazada por Central.")
            print(f"[Monitor] Verifica que las credenciales son correctas y que el CP está registrado.")
        return

    # Hilo de reconexión automática a Central
    threading.Thread(
        target=reconnect_loop,
        args=(engine_ip, engine_port, central_ip, central_port, cp_id),
        daemon=True
    ).start()

    # Iniciar hilo para escuchar comandos de Central
    threading.Thread(
        target=listen_central_commands,
        args=(central_conn, engine_ip, engine_port, cp_id),
        daemon=True
    ).start()

    # Iniciar hilo para monitorizar el Engine (gen=0 inicial)
    threading.Thread(
        target=connect_engine,
        args=(central_conn, engine_ip, engine_port, cp_id, 0),
        daemon=True
    ).start()

    print(f"[Monitor] Sistema completamente inicializado para CP: {cp_id}")
    print(f"[Monitor] Iniciando pantalla de monitorización en tiempo real...")
    time.sleep(2)

    threading.Thread(target=display_monitor_screen, daemon=True).start()

    handle_user_input(engine_ip, engine_port)

    RUNNING = False
    central_conn.close()
    print(f"  Monitor {cp_id} finalizado correctamente.\n")


# Leer argumentos de línea de comandos
def args():
    engine_ip     = sys.argv[1] if len(sys.argv) > 1 else 'localhost'
    engine_port   = int(sys.argv[2]) if len(sys.argv) > 2 else 6000
    central_ip    = sys.argv[3] if len(sys.argv) > 3 else 'localhost'
    central_port  = int(sys.argv[4]) if len(sys.argv) > 4 else 5000
    cp_id         = sys.argv[5] if len(sys.argv) > 5 else 'ALC1'
    registry_ip   = sys.argv[6] if len(sys.argv) > 6 else 'localhost'
    registry_port = int(sys.argv[7]) if len(sys.argv) > 7 else 5001
    return engine_ip, engine_port, central_ip, central_port, cp_id, registry_ip, registry_port


if __name__ == "__main__":
    engine_ip, engine_port, central_ip, central_port, cp_id, registry_ip, registry_port = args()
    main(engine_ip, engine_port, central_ip, central_port, cp_id, registry_ip, registry_port)