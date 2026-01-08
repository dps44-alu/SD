import sys
import socket
import time
import threading
import os
import select

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


# Limpiar pantalla de forma multiplataforma
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


# Obtener representación visual del estado
def get_status_display(status):
    status_map = {
        "ACTIVE": ("DISPONIBLE", "verde"),
        "BUSY": ("CARGANDO", "azul"),
        "OUT_OF_ORDER": ("FUERA DE SERVICIO", "naranja"),
        "BROKEN": ("AVERIADO", "rojo"),
        "INACTIVE": ("INACTIVO", "gris")
    }
    return status_map.get(status, ("DESCONOCIDO", "negro"))


# Mostrar pantalla de monitorización actualizada continuamente
def display_monitor_screen():
    global CP_ID, CP_ADDRESS, CP_PRICE, CP_STATUS, CURRENT_DRIVER, CHARGING_INFO, PAUSED
    
    while RUNNING:
        if not PAUSED:
            clear_screen()
            
            status_text, color_text = get_status_display(CP_STATUS)
            
            print(f"{'='*70}")
            print(f"  MONITOR CP - SISTEMA DE MONITORIZACIÓN EN TIEMPO REAL")
            print(f"{'='*70}")
            print(f"  ID del Punto de Carga: {CP_ID}")
            print(f"  Dirección: {CP_ADDRESS}")
            print(f"  Precio: {CP_PRICE}€/kWh")
            print(f"{'='*70}")
            print(f"  Estado: {status_text} ({color_text})")
            print(f"{'='*70}")
            
            if CP_STATUS == "BUSY" and CURRENT_DRIVER:
                print(f"\n  CARGA EN PROGRESO")
                print(f"  {'-'*66}")
                print(f"    Conductor: {CURRENT_DRIVER}")
                print(f"    Consumo actual: {CHARGING_INFO['kwh']:.2f} kWh")
                print(f"    Importe acumulado: {CHARGING_INFO['cost']:.2f}€")
                print(f"  {'-'*66}")
            elif CP_STATUS == "ACTIVE":
                print(f"\n  Punto de carga listo para recibir solicitudes")
            elif CP_STATUS == "OUT_OF_ORDER":
                print(f"\n  Punto de carga fuera de servicio temporalmente")
            elif CP_STATUS == "BROKEN":
                print(f"\n  Punto de carga averiado - detenido por Central")
                print(f"  Requiere comando RESUME para volver a operar")
            elif CP_STATUS == "INACTIVE":
                print(f"\n  ⸻ Punto de carga inactivo")
            
            print(f"\n{'='*70}")
            print(f"  CONTROLES:")
            print(f"  - Presiona '1' + ENTER para solicitar carga manual")
            print(f"  - Presiona '2' + ENTER para ver estado detallado")
            print(f"  - Presiona '3' + ENTER para re-registrar en Registry") 
            print(f"  - Presiona '0' + ENTER para salir")
            print(f"{'='*70}")
            print(f"\n  Actualización automática cada 1 segundo...")
            print(f"  (La pantalla se actualiza en tiempo real)")
        
        time.sleep(1)


# Obtiene la configuración completa desde Central
def get_config_from_central(central_ip, central_port, cp_id):
    global CP_PRICE, CP_ADDRESS, CP_STATUS
    
    max_retries = 10
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                client.settimeout(3)
                client.connect((central_ip, central_port))
                
                msg = f"REQUEST_CONFIG#{cp_id}"
                client.sendall(msg.encode())
                
                response = client.recv(1024).decode()
                parts = response.split("#")
                
                if parts[0] == "CONFIG_OK" and len(parts) == 4:
                    CP_ADDRESS = parts[1]
                    CP_PRICE = float(parts[2])
                    CP_STATUS = parts[3]
                    
                    print(f"[Monitor] Configuración obtenida de Central:")
                    print(f"          ID: {cp_id}")
                    print(f"          Dirección: {CP_ADDRESS}")
                    print(f"          Precio: {CP_PRICE}€/kWh")
                    print(f"          Estado: {CP_STATUS}")
                    return True
                elif parts[0] == "CONFIG_NOT_FOUND":
                    print(f"[Monitor] El CP {cp_id} no existe en la base de datos")
                    return False
                    
        except Exception as e:
            retry_count += 1
            print(f"[Monitor] Intento {retry_count}/{max_retries} falló: {e}")
            time.sleep(1)
    
    print("[Monitor] No se pudo obtener la configuración de Central")
    return False


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
                
                msg = f"SET_CONFIG#{cp_id}#{CP_PRICE}#{CP_ADDRESS}"
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
    global CP_PRICE, CP_ADDRESS, CP_STATUS
    
    central_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    central_conn.connect((central_ip, central_port))
    print(f"[Monitor] Conectado a Central {central_ip}:{central_port}")

    msg = f"AUTH#{cp_id}#{CP_ADDRESS}#{CP_PRICE}#{CP_STATUS}"
    central_conn.sendall(msg.encode())
    print(f"[Monitor] Enviando AUTH a Central:")
    print(f"          ID: {cp_id}")
    print(f"          Dirección: {CP_ADDRESS}")
    print(f"          Precio: {CP_PRICE}€/kWh")
    print(f"          Estado: {CP_STATUS}")

    response = central_conn.recv(1024).decode()
    print(f"[Monitor] Respuesta de Central: {response}")

    if response != "ACCEPTED":
        print("[Monitor] Conexión rechazada por Central. Cerrando...")
        central_conn.close()
        exit(1)

    return central_conn


# Escucha comandos de Central (STOP, RESUME) y los reenvía al Engine
def listen_central_commands(central_conn, engine_ip, engine_port, cp_id):
    global CP_STATUS, RUNNING
    
    print(f"[Monitor] Iniciando escucha de comandos de Central para CP {cp_id}...")
    
    while RUNNING:
        try:
            central_conn.settimeout(1.0)
            data = central_conn.recv(1024)
            
            if not data:
                print(f"[Monitor] Conexión con Central cerrada")
                break
                
            msg = data.decode()
            parts = msg.split("#")
            
            if len(parts) >= 3 and parts[0] == "COMMAND":
                cmd_cp_id = parts[1]
                command = parts[2]
                
                if cmd_cp_id == cp_id:
                    print(f"\n[Monitor] Comando recibido de Central: {command}")
                    
                    # Reenviar comando al Engine
                    try:
                        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as engine_client:
                            engine_client.settimeout(3)
                            engine_client.connect((engine_ip, engine_port))
                            engine_client.sendall(command.encode())
                            
                            # Esperar respuesta del Engine
                            response = engine_client.recv(1024).decode()
                            print(f"[Monitor] Respuesta del Engine: {response}")
                            
                            # Confirmar a Central
                            central_conn.sendall(response.encode())
                            
                            # CORRECCIÓN: Actualizar estado según comando
                            if command == "STOP":
                                CP_STATUS = "BROKEN"  # Cambiar a BROKEN en lugar de OUT_OF_ORDER
                                print(f"[Monitor] CP {cp_id} detenido - estado: BROKEN (Averiado)")
                            elif command == "RESUME":
                                CP_STATUS = "ACTIVE"
                                print(f"[Monitor] CP {cp_id} reanudado - estado: ACTIVE")
                                
                    except Exception as e:
                        print(f"[Monitor] Error reenviando comando al Engine: {e}")
                        central_conn.sendall(b"ERROR")
                        
        except socket.timeout:
            continue
        except Exception as e:
            if RUNNING:
                print(f"[Monitor] Error escuchando comandos de Central: {e}")
            break


# Se conecta y monitoriza el Engine
def connect_engine(central_conn, engine_ip, engine_port, cp_id):
    global CP_STATUS, CURRENT_DRIVER, CHARGING_INFO, RUNNING
    last_driver = ""
    last_charging_info = {"kwh": 0, "cost": 0}

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.connect((engine_ip, engine_port))
        print(f"[Monitor] Conectado a Engine {engine_ip}:{engine_port}")

        while RUNNING:
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
                            
                            CURRENT_DRIVER = new_driver
                            CHARGING_INFO["kwh"] = new_kwh
                            CHARGING_INFO["cost"] = new_cost
                            
                            last_driver = new_driver
                            last_charging_info = {"kwh": new_kwh, "cost": new_cost}
                            
                    except:
                        pass
                else:
                    CURRENT_DRIVER = None
                    CHARGING_INFO = {"kwh": 0, "cost": 0}
                    last_driver = ""
                    last_charging_info = {"kwh": 0, "cost": 0}

                if new_status and new_status != CP_STATUS:
                    print(f"[Monitor] Cambio detectado: {CP_STATUS} -> {new_status}")
                    print(f"          Notificando a Central...")
                    CP_STATUS = new_status

                    msg = f"CHANGE#{cp_id}#None#None#{new_status}"
                    central_conn.sendall(msg.encode())

                time.sleep(1)

            except Exception as e:
                print(f"[Monitor] Error con Engine: {e}")
                break


def register_cp_manually():
    """Permite re-registrar el CP manualmente"""
    global CP_ID, CP_ADDRESS, CP_PRICE
    
    clear_screen()
    print(f"\n{'─'*70}")
    print(f"  RE-REGISTRO EN REGISTRY")
    print(f"{'─'*70}")
    print(f"  CP ID: {CP_ID}")
    print(f"  Dirección: {CP_ADDRESS}")
    print(f"  Precio: {CP_PRICE}€/kWh")
    print(f"{'─'*70}")
    
    confirm = input("\n  ¿Deseas re-registrar este CP? (s/n): ").strip().lower()
    
    if confirm == 's':
        registry_url = "https://localhost:5001"
        success, username, password = register_with_registry(
            registry_url, CP_ID, CP_ADDRESS, CP_PRICE
        )
        
        if success:
            print("\n  ✓ CP registrado correctamente")
            if username:
                print(f"  Credenciales recibidas: {username}")
        else:
            print("\n  ✗ Error en el registro")
    else:
        print("  Operación cancelada")
    
    input("\n  Presiona ENTER para continuar...")


# Maneja la entrada del usuario de forma no bloqueante
def handle_user_input(engine_ip, engine_port):
    global RUNNING, CP_ID, PAUSED
    
    while RUNNING:
        try:
            user_input = input()
            
            if user_input.strip() == "1":
                PAUSED = True
                request_manual_charge(engine_ip, engine_port)
                PAUSED = False
            elif user_input.strip() == "2":
                PAUSED = True
                show_detailed_status(engine_ip, engine_port)
                PAUSED = False
            elif user_input.strip() == "3":  
                PAUSED = True
                register_cp_manually()
                PAUSED = False
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
            else:
                print(f"  Solicitud rechazada: {response}")
    except Exception as e:
        print(f"  Error al comunicarse con el Engine: {e}")
    
    time.sleep(2)


# Muestra el estado detallado con actualización en tiempo real
def show_detailed_status(engine_ip, engine_port):
    global CP_ID, CP_ADDRESS, CP_PRICE, CP_STATUS, CURRENT_DRIVER, CHARGING_INFO, PAUSED
    
    import select
    import sys
    
    print("\n  Presiona ENTER para volver al menú principal...")
    print("  (La pantalla se actualizará automáticamente mientras tanto)\n")
    time.sleep(1)
    
    running = True
    
    while running and PAUSED:
        clear_screen()
        print(f"\n{'='*70}")
        print(f"  ESTADO DETALLADO - CP {CP_ID}")
        print(f"{'='*70}")
        print(f"  ID: {CP_ID}")
        print(f"  Dirección: {CP_ADDRESS}")
        print(f"  Precio: {CP_PRICE}€/kWh")
        
        status_text, color_text = get_status_display(CP_STATUS)
        print(f"  Estado actual: {status_text} ({color_text})")
        
        if CURRENT_DRIVER:
            print(f"\n  CARGA ACTIVA:")
            print(f"  {'-'*66}")
            print(f"     Conductor: {CURRENT_DRIVER}")
            print(f"     Consumo actual: {CHARGING_INFO['kwh']:.2f} kWh")
            print(f"     Importe acumulado: {CHARGING_INFO['cost']:.2f}€")
            print(f"  {'-'*66}")
        else:
            print(f"\n  Sin carga activa")
        
        print(f"\n  CONEXIÓN ENGINE:")
        print(f"  {'-'*66}")
        print(f"     IP: {engine_ip}")
        print(f"     Puerto: {engine_port}")
        
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                client.settimeout(2)
                client.connect((engine_ip, engine_port))
                print(f"     Estado: CONEXIÓN ACTIVA")
        except Exception as e:
            print(f"     Estado: ERROR DE CONEXIÓN")
        
        print(f"  {'-'*66}")
        print(f"{'='*70}")
        print(f"\n  Esta pantalla se actualiza cada segundo")
        print(f"  Presiona ENTER para volver al menú principal")
        print(f"{'='*70}\n")
        
        i, o, e = select.select([sys.stdin], [], [], 0)
        if i:
            line = sys.stdin.readline()
            running = False
        
        if running:
            time.sleep(1)


def register_with_registry(registry_url, cp_id, address, price):
    """
    Registra el CP en EV_Registry vía API REST
    Retorna (success, username, password)
    """
    try:
        print(f"[Monitor] Registrando CP {cp_id} en Registry...")
        
        response = requests.post(
            f"{registry_url}/register",
            json={
                "id": cp_id,
                "address": address,
                "price": price
            },
            verify=False,  # Ignorar certificado SSL autofirmado
            timeout=5
        )
        
        if response.status_code == 201:
            data = response.json()
            print(f"[Monitor] CP registrado exitosamente")
            print(f"          Username: {data['username']}")
            print(f"          Password: {data['password']}")
            return True, data['username'], data['password']
        elif response.status_code == 409:
            print(f"[Monitor] CP ya estaba registrado")
            return True, None, None
        else:
            print(f"[Monitor] Error en registro: {response.json()}")
            return False, None, None
            
    except Exception as e:
        print(f"[Monitor] Error conectando con Registry: {e}")
        return False, None, None
    

# Función principal
def main(engine_ip, engine_port, central_ip, central_port, cp_id):
    global CP_ID, RUNNING
    CP_ID = cp_id
    
    # Intentar registro en Registry primero
    registry_url = "https://localhost:5001"  # URL del Registry
    print(f"[Monitor] Intentando registro en Registry...")
    
    # Obtener config de Central primero para tener address y price
    print(f"[Monitor] Solicitando configuración a Central para CP: {cp_id}")
    if not get_config_from_central(central_ip, central_port, cp_id):
        # Si no existe en Central, solicitar datos para registro
        print(f"\n[Monitor] CP no encontrado en sistema. Iniciando proceso de registro...")
        CP_ADDRESS = input("  Dirección del CP: ").strip()
        CP_PRICE = float(input("  Precio (€/kWh): ").strip())
        
        # Registrar en Registry
        success, username, password = register_with_registry(
            registry_url, cp_id, CP_ADDRESS, CP_PRICE
        )
        
        if not success:
            print("[Monitor] Error crítico: no se pudo registrar en Registry")
            return
        
        print(f"[Monitor] Esperando 2 segundos para que Registry actualice la BD...")
        time.sleep(2)
        
        # Reintentar obtener config
        if not get_config_from_central(central_ip, central_port, cp_id):
            print("[Monitor] Error: aún no se puede obtener configuración")
            return
    
    print(f"[Monitor] Enviando configuración al Engine...")
    if not send_config_to_engine(engine_ip, engine_port, cp_id):
        print("[Monitor] Error crítico: no se pudo configurar el Engine")
        return
    
    print(f"[Monitor] Autenticándose con Central...")
    central_conn = connect_central(central_ip, central_port, cp_id)

    # Iniciar hilo para escuchar comandos de Central
    threading.Thread(
        target=listen_central_commands,
        args=(central_conn, engine_ip, engine_port, cp_id),
        daemon=True
    ).start()

    # Iniciar hilo para monitorizar el Engine
    threading.Thread(
        target=connect_engine, 
        args=(central_conn, engine_ip, engine_port, cp_id), 
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
    return sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4]), sys.argv[5]


if __name__ == "__main__":
    engine_ip, engine_port, central_ip, central_port, cp_id = args()
    main(engine_ip, engine_port, central_ip, central_port, cp_id)