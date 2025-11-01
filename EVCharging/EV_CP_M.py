import sys
import socket
import time
import threading
import os


CP_STATUS = None
CP_ADDRESS = None
CP_PRICE = None
CP_ID = None
CURRENT_DRIVER = None
CHARGING_INFO = {"kwh": 0, "cost": 0}
RUNNING = True
PAUSED = False  # Flag para pausar la actualización de pantalla


def clear_screen():
    """Limpiar pantalla de forma multiplataforma"""
    os.system('cls' if os.name == 'nt' else 'clear')


def get_status_display(status):
    """Obtener representación visual del estado"""
    status_map = {
        "ACTIVE": ("🟢", "DISPONIBLE", "verde"),
        "BUSY": ("🔵", "CARGANDO", "azul"),
        "OUT_OF_ORDER": ("🟠", "FUERA DE SERVICIO", "naranja"),
        "BROKEN": ("🔴", "AVERIADO", "rojo"),
        "INACTIVE": ("⚪", "INACTIVO", "gris")
    }
    return status_map.get(status, ("⚫", "DESCONOCIDO", "negro"))


def display_monitor_screen():
    """Mostrar pantalla de monitorización actualizada continuamente"""
    global CP_ID, CP_ADDRESS, CP_PRICE, CP_STATUS, CURRENT_DRIVER, CHARGING_INFO, PAUSED
    
    while RUNNING:
        # Solo actualizar si no está pausada
        if not PAUSED:
            clear_screen()
            
            icon, status_text, color_text = get_status_display(CP_STATUS)
            
            print(f"{'='*70}")
            print(f"  MONITOR CP - SISTEMA DE MONITORIZACIÓN EN TIEMPO REAL")
            print(f"{'='*70}")
            print(f"  ID del Punto de Carga: {CP_ID}")
            print(f"  Dirección: {CP_ADDRESS}")
            print(f"  Precio: {CP_PRICE}€/kWh")
            print(f"{'='*70}")
            print(f"  Estado: {icon} {status_text} ({color_text})")
            print(f"{'='*70}")
            
            # Mostrar información de carga si está activo
            if CP_STATUS == "BUSY" and CURRENT_DRIVER:
                print(f"\n  📊 CARGA EN PROGRESO")
                print(f"  {'-'*66}")
                print(f"    Conductor: {CURRENT_DRIVER}")
                print(f"    Consumo actual: {CHARGING_INFO['kwh']:.2f} kWh")
                print(f"    Importe acumulado: {CHARGING_INFO['cost']:.2f}€")
                print(f"  {'-'*66}")
            elif CP_STATUS == "ACTIVE":
                print(f"\n  ✅ Punto de carga listo para recibir solicitudes")
            elif CP_STATUS == "OUT_OF_ORDER":
                print(f"\n  ⚠️  Punto de carga fuera de servicio temporalmente")
            elif CP_STATUS == "BROKEN":
                print(f"\n  ❌ Punto de carga averiado - requiere atención")
            elif CP_STATUS == "INACTIVE":
                print(f"\n  ⏸️  Punto de carga inactivo")
            
            print(f"\n{'='*70}")
            print(f"  CONTROLES:")
            print(f"  - Presiona '1' + ENTER para solicitar carga manual")
            print(f"  - Presiona '2' + ENTER para ver estado detallado")
            print(f"  - Presiona '0' + ENTER para salir")
            print(f"{'='*70}")
            print(f"\n  Actualización automática cada 1 segundo...")
            print(f"  (La pantalla se actualiza en tiempo real)")
        
        time.sleep(1)


def get_config_from_central(central_ip, central_port, cp_id):
    """Obtiene la configuración completa desde Central"""
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


def send_config_to_engine(engine_ip, engine_port, cp_id):
    """Envía la configuración al Engine"""
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


def connect_central(central_ip, central_port, cp_id):
    """Se conecta y autentica con central"""
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


def connect_engine(central_conn, engine_ip, engine_port, cp_id):
    """Se conecta y monitoriza el Engine"""
    global CP_STATUS, CURRENT_DRIVER, CHARGING_INFO, RUNNING
    last_status = ""
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
                
                # Actualizar información de carga
                if len(parts) >= 4:
                    new_driver = parts[1] if parts[1] != "None" else None
                    try:
                        new_kwh = float(parts[2])
                        new_cost = float(parts[3])
                        
                        # Solo actualizar si hay cambios
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

                # Si ha cambiado el estado, notificar a Central
                if new_status and new_status != CP_STATUS:
                    print(f"[Monitor] Cambio detectado: {CP_STATUS} -> {new_status}")
                    print(f"          Notificando a Central...")
                    CP_STATUS = new_status
                    last_status = new_status

                    msg = f"CHANGE#{cp_id}#None#None#{new_status}"
                    central_conn.sendall(msg.encode())

                time.sleep(1)

            except Exception as e:
                print(f"[Monitor] Error con Engine: {e}")
                break


def handle_user_input(engine_ip, engine_port):
    """Maneja la entrada del usuario de forma no bloqueante"""
    global RUNNING, CP_ID, PAUSED
    
    while RUNNING:
        try:
            user_input = input()
            
            if user_input.strip() == "1":
                PAUSED = True  # Pausar actualización de pantalla
                request_manual_charge(engine_ip, engine_port)
                PAUSED = False  # Reanudar actualización
            elif user_input.strip() == "2":
                PAUSED = True  # Pausar actualización de pantalla
                show_detailed_status(engine_ip, engine_port)
                PAUSED = False  # Reanudar actualización
            elif user_input.strip() == "0":
                print(f"\n[Monitor] 👋 Cerrando Monitor...")
                RUNNING = False
                break
                
        except KeyboardInterrupt:
            print(f"\n\n[Monitor] ⚠️ Interrupción detectada. Cerrando...")
            RUNNING = False
            break
        except:
            pass


def request_manual_charge(engine_ip, engine_port):
    """Solicita una carga manual al Engine"""
    global CP_ID, CP_STATUS
    
    clear_screen()
    print(f"\n{'─'*70}")
    print(f"  SOLICITAR CARGA MANUAL")
    print(f"{'─'*70}")
    
    if CP_STATUS != "ACTIVE":
        print(f"  ⚠️  El CP no está disponible (Estado: {CP_STATUS})")
        print(f"  No se puede iniciar una carga manual")
        input("\n  Presiona ENTER para continuar...")
        return
    
    # Solicitar ID del conductor
    driver_id = input("\n  ID del conductor: ").strip()
    
    if not driver_id:
        print("  ❌ ID de conductor vacío. Operación cancelada.")
        input("\n  Presiona ENTER para continuar...")
        return
    
    # Solicitar duración
    duration = input("  Duración de la carga en segundos [7]: ").strip()
    
    if not duration:
        duration = 7
    else:
        try:
            duration = int(duration)
        except ValueError:
            print("  ❌ Duración inválida, usando 7 segundos")
            duration = 7
    
    print(f"\n  ⚡ Solicitando carga manual:")
    print(f"     Conductor: {driver_id}")
    print(f"     Duración: {duration} segundos")
    print(f"     Enviando al Engine...")
    
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
            client.settimeout(3)
            client.connect((engine_ip, engine_port))
            
            # Enviar con driver_id real
            msg = f"MANUAL_CHARGE#{CP_ID}#{driver_id}#{duration}"
            client.sendall(msg.encode())
            
            response = client.recv(1024).decode()
            
            if response == "CHARGE_ACCEPTED":
                print(f"  ✅ Solicitud aceptada")
                print(f"  La carga comenzará en unos momentos...")
                print(f"  El conductor {driver_id} verá la carga en su aplicación")
            else:
                print(f"  ❌ Solicitud rechazada: {response}")
    except Exception as e:
        print(f"  ❌ Error al comunicarse con el Engine: {e}")
    
    time.sleep(2)


def show_detailed_status(engine_ip, engine_port):
    """Muestra el estado detallado con actualización en tiempo real"""
    global CP_ID, CP_ADDRESS, CP_PRICE, CP_STATUS, CURRENT_DRIVER, CHARGING_INFO, PAUSED
    
    # Crear evento para detectar cuando el usuario presiona ENTER
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
        
        # Mostrar estado con icono
        icon, status_text, color_text = get_status_display(CP_STATUS)
        print(f"  Estado actual: {icon} {status_text} ({color_text})")
        
        if CURRENT_DRIVER:
            print(f"\n  📊 CARGA ACTIVA:")
            print(f"  {'-'*66}")
            print(f"     Conductor: {CURRENT_DRIVER}")
            print(f"     Consumo actual: {CHARGING_INFO['kwh']:.2f} kWh")
            print(f"     Importe acumulado: {CHARGING_INFO['cost']:.2f}€")
            print(f"  {'-'*66}")
        else:
            print(f"\n  ⏸️  Sin carga activa")
        
        print(f"\n  🔗 CONEXIÓN ENGINE:")
        print(f"  {'-'*66}")
        print(f"     IP: {engine_ip}")
        print(f"     Puerto: {engine_port}")
        
        # Intentar ping al Engine
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
                client.settimeout(2)
                client.connect((engine_ip, engine_port))
                print(f"     Estado: ✅ CONEXIÓN ACTIVA")
        except Exception as e:
            print(f"     Estado: ❌ ERROR DE CONEXIÓN")
        
        print(f"  {'-'*66}")
        print(f"{'='*70}")
        print(f"\n  ℹ️  Esta pantalla se actualiza cada segundo")
        print(f"  👉 Presiona ENTER para volver al menú principal")
        print(f"{'='*70}\n")
        
        # Comprobar si hay entrada disponible (multiplataforma)
        if os.name == 'nt':  # Windows
            import msvcrt
            if msvcrt.kbhit():
                key = msvcrt.getch()
                if key == b'\r':  # ENTER en Windows
                    running = False
        else:  # Linux/Unix
            import select
            # Comprobar si hay entrada disponible sin bloquear
            i, o, e = select.select([sys.stdin], [], [], 0)
            if i:
                line = sys.stdin.readline()
                running = False
        
        if running:
            time.sleep(1)


def main(engine_ip, engine_port, central_ip, central_port, cp_id):
    """Función principal"""
    global CP_ID, RUNNING
    CP_ID = cp_id
    
    # Paso 1: Solicitar configuración a Central
    print(f"[Monitor] Solicitando configuración a Central para CP: {cp_id}")
    if not get_config_from_central(central_ip, central_port, cp_id):
        print("[Monitor] Error crítico: no se pudo obtener la configuración de Central")
        return
    
    # Paso 2: Enviar configuración al Engine
    print(f"[Monitor] Enviando configuración al Engine...")
    if not send_config_to_engine(engine_ip, engine_port, cp_id):
        print("[Monitor] Error crítico: no se pudo configurar el Engine")
        return
    
    # Paso 3: Autenticarse con Central
    print(f"[Monitor] Autenticándose con Central...")
    central_conn = connect_central(central_ip, central_port, cp_id)

    # Paso 4: Crear hilo para monitorizar Engine
    threading.Thread(
        target=connect_engine, 
        args=(central_conn, engine_ip, engine_port, cp_id), 
        daemon=True
    ).start()

    # Paso 5: Sistema inicializado
    print(f"[Monitor] Sistema completamente inicializado para CP: {cp_id}")
    print(f"[Monitor] Iniciando pantalla de monitorización en tiempo real...")
    time.sleep(2)
    
    # Paso 6: Iniciar pantalla de monitorización en hilo separado
    threading.Thread(target=display_monitor_screen, daemon=True).start()
    
    # Paso 7: Manejar entrada del usuario
    handle_user_input(engine_ip, engine_port)
    
    # Cerrar conexiones
    RUNNING = False
    central_conn.close()
    print(f"  ✅ Monitor {cp_id} finalizado correctamente.\n")


def args():
    """Leer argumentos de línea de comandos"""
    return sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4]), sys.argv[5]


if __name__ == "__main__":
    engine_ip, engine_port, central_ip, central_port, cp_id = args()
    main(engine_ip, engine_port, central_ip, central_port, cp_id)