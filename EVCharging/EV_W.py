import time
import requests
import threading
import json
import os


# Configuración OpenWeather
API_KEY = "b62e1bb5d7f9aab843efc4fe2d3b5640"                        # https://openweathermap.org/
BASE_URL = "https://api.openweathermap.org/data/2.5/weather"

# Configuración Central API
CENTRAL_API_URL = "http://localhost:8000"

# Almacén de localizaciones y estados
LOCATIONS = {}          # {cp_id: city_name}
ALERT_STATUS = {}       # {cp_id: bool} - True si hay alerta activa

# Sistema de mensajes 
MESSAGE_BUFFER = []
MESSAGE_LOCK = threading.Lock()
MENU_REFRESH_EVENT = threading.Event()


# Añade un mensaje al buffer para mostrar de forma ordenada
def log_message(message):
    with MESSAGE_LOCK:
        MESSAGE_BUFFER.append(f"[{time.strftime('%H:%M:%S')}] {message}")
    MENU_REFRESH_EVENT.set()


# Limpiar pantalla de forma multiplataforma
def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


# Muestra todos los mensajes pendientes
def display_pending_messages():
    with MESSAGE_LOCK:
        if MESSAGE_BUFFER:
            print("\n" + "="*60)
            print("  MENSAJES DEL SISTEMA")
            print("="*60)
            for msg in MESSAGE_BUFFER:
                print(f"  {msg}")
            print("="*60)
            MESSAGE_BUFFER.clear()
            return True
    return False


# Carga las localizaciones desde un archivo -> CP_ID,CIUDAD
def load_locations_from_file(filename="locations.txt"):
    global LOCATIONS

    try:
        with open(filename, "r") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split(",")
                    if len(parts) == 2:
                        cp_id, city = parts
                        LOCATIONS[cp_id.strip()] = city.strip()
                        ALERT_STATUS[cp_id.strip()] = False
        log_message(f"Localizaciones cargadas: {list(LOCATIONS.keys())}")
    except FileNotFoundError:
        log_message(f"Archivo {filename} no encontrado. Usar menú para añadir localizaciones.")


# Obtiene la temperatura actual de una ciudad desde OpenWeather API
def get_temperature(city):
    try:
        params = {
            "q": city,
            "appid": API_KEY,
            "units": "metric"
        }
        response = requests.get(BASE_URL, params=params, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            temp = data["main"]["temp"]
            return temp
        else:
            log_message(f"Error consultando {city}: HTTP {response.status_code}")
            return None
    except Exception as e:
        log_message(f"Error obteniendo temperatura de {city}: {e}")
        return None


# Notifica a Central sobre una alerta o cancelación -> alert_type: "ALERT" o "CANCEL"
def notify_central_alert(cp_id, alert_type):
    try:
        endpoint = f"{CENTRAL_API_URL}/weather/alert"
        payload = {
            "cp_id": cp_id,
            "alert_type": alert_type,
            "reason": "Temperatura bajo 0°C" if alert_type == "ALERT" else "Temperatura normalizada"
        }
        response = requests.post(endpoint, json=payload, timeout=3)
        
        if response.status_code == 200:
            log_message(f"{alert_type} enviada correctamente para {cp_id}")
            return True
        else:
            log_message(f"Error enviando {alert_type} para {cp_id}: HTTP {response.status_code}")
            return False
    except Exception as e:
        log_message(f"Error comunicando con Central: {e}")
        return False


# Monitoriza el clima cada 4 segundos según el enunciado
def monitor_weather():
    log_message("Iniciando monitorización de clima (cada 4 segundos)")
    
    while True:
        for cp_id, city in LOCATIONS.items():
            temp = get_temperature(city)
            
            if temp is not None:
                # Usar log_message en lugar de print
                log_message(f"{cp_id} ({city}): {temp:.1f}°C")
                
                # Lógica de alertas según enunciado
                if temp < 0 and not ALERT_STATUS[cp_id]:
                    log_message(f"⚠️  ALERTA: {cp_id} temperatura crítica ({temp:.1f}°C)")
                    if notify_central_alert(cp_id, "ALERT"):
                        ALERT_STATUS[cp_id] = True
                        
                elif temp >= 0 and ALERT_STATUS[cp_id]:
                    log_message(f"✓ NORMALIZADO: {cp_id} temperatura restaurada ({temp:.1f}°C)")
                    if notify_central_alert(cp_id, "CANCEL"):
                        ALERT_STATUS[cp_id] = False
        
        time.sleep(4)


# Muestra el menú de control
def show_menu():
    clear_screen()
    
    # Mostrar mensajes pendientes ANTES del menú
    has_messages = display_pending_messages()
    
    if has_messages:
        print()  # Línea en blanco después de mensajes
    
    print(f"{'='*60}")
    print(f"  EV_W - WEATHER CONTROL OFFICE")
    print(f"{'='*60}")
    print(f"  Localizaciones monitorizadas:")
    if LOCATIONS:
        for cp_id, city in LOCATIONS.items():
            status = "ALERTA" if ALERT_STATUS.get(cp_id, False) else "🟢 OK"
            print(f"    {cp_id}: {city} - {status}")
    else:
        print(f"    (ninguna)")
    print(f"{'='*60}")
    print(f"  1. Añadir localización")
    print(f"  2. Eliminar localización")
    print(f"  3. Ver estado actual")
    print(f"  4. Actualizar (refrescar mensajes)")
    print(f"  0. Salir")
    print(f"{'='*60}")


# Chequea inmediatamente la temperatura de un CP específico
def check_temperature_now(cp_id):
    if cp_id not in LOCATIONS:
        return
    
    city = LOCATIONS[cp_id]
    log_message(f"Chequeando temperatura actual de {city}...")
    
    # Esperar 1 segundo para que el mensaje se vea
    time.sleep(1)
    
    temp = get_temperature(city)
    
    if temp is not None:
        log_message(f"{cp_id} ({city}): {temp:.1f}°C")
        
        # Aplicar lógica de alertas inmediatamente
        if temp < 0 and not ALERT_STATUS[cp_id]:
            log_message(f"ALERTA: {cp_id} temperatura crítica ({temp:.1f}°C)")
            if notify_central_alert(cp_id, "ALERT"):
                ALERT_STATUS[cp_id] = True
                
        elif temp >= 0 and ALERT_STATUS[cp_id]:
            log_message(f"NORMALIZADO: {cp_id} temperatura restaurada ({temp:.1f}°C)")
            if notify_central_alert(cp_id, "CANCEL"):
                ALERT_STATUS[cp_id] = False


# Bucle principal del menú
def menu_loop(): 
    # Thread para monitorear mensajes nuevos
    def monitor_messages():
        while True:
            if MENU_REFRESH_EVENT.wait(timeout=2):
                MENU_REFRESH_EVENT.clear()
    
    threading.Thread(target=monitor_messages, daemon=True).start()
    
    while True:
        try:
            show_menu()
            
            print("\n  Selecciona opción: ", end='', flush=True)
            option = input().strip()
            
            if option == "1":
                clear_screen()
                display_pending_messages()
                
                # Mostrar CPs existentes
                if LOCATIONS:
                    print("\n  CPs ya registrados:")
                    for cp_id, city in LOCATIONS.items():
                        print(f"    - {cp_id}: {city}")
                    print("\n  (Si usas un CP existente, se actualizará su ciudad)")
                
                cp_id = input("\n  ID del CP: ").strip()
                city = input("  Ciudad: ").strip()
                
                if cp_id and city:
                    # CAMBIO: Si es un CP existente con ciudad diferente, resetear alerta
                    if cp_id in LOCATIONS and LOCATIONS[cp_id] != city:
                        old_city = LOCATIONS[cp_id]
                        log_message(f"Cambiando ciudad de {cp_id}: {old_city} → {city}")
                        
                        # Si había alerta activa en la ciudad anterior, cancelarla
                        if ALERT_STATUS.get(cp_id, False):
                            log_message(f"Cancelando alerta previa de {cp_id} ({old_city})")
                            notify_central_alert(cp_id, "CANCEL")
                        
                        # Resetear estado de alerta para forzar nueva evaluación
                        ALERT_STATUS[cp_id] = False
                    
                    LOCATIONS[cp_id] = city
                    
                    # Si es nuevo CP, inicializar sin alerta
                    if cp_id not in ALERT_STATUS:
                        ALERT_STATUS[cp_id] = False
                    
                    log_message(f"{cp_id} configurado para monitorizar {city}")
                    
                    # CAMBIO: Forzar chequeo inmediato de temperatura
                    threading.Thread(target=check_temperature_now, args=(cp_id,), daemon=True).start()
                else:
                    log_message("Datos incompletos, operación cancelada")
                
                time.sleep(1)
            
            elif option == "2":
                clear_screen()
                display_pending_messages()
                
                if not LOCATIONS:
                    print("\n  No hay localizaciones para eliminar")
                    input("\n  Presiona ENTER para continuar...")
                    continue
                
                print("\n  Localizaciones actuales:")
                for cp_id, city in LOCATIONS.items():
                    print(f"    - {cp_id}: {city}")
                
                cp_id = input("\n  ID del CP a eliminar: ").strip()
                
                if cp_id in LOCATIONS:
                    city = LOCATIONS[cp_id]
                    
                    # CAMBIO: Si había alerta activa, cancelarla antes de eliminar
                    if ALERT_STATUS.get(cp_id, False):
                        log_message(f"Cancelando alerta de {cp_id} antes de eliminar")
                        notify_central_alert(cp_id, "CANCEL")
                    
                    del LOCATIONS[cp_id]
                    del ALERT_STATUS[cp_id]
                    log_message(f"{cp_id} ({city}) eliminado")
                else:
                    log_message(f"CP '{cp_id}' no encontrado")
                
                time.sleep(1)
            
            elif option == "3":
                # Simplemente refrescar para mostrar estado actual
                continue
            
            elif option == "4":
                # Simplemente refrescar para mostrar mensajes
                continue
                
            elif option == "0":
                clear_screen()
                print("\n[EV_W] Cerrando Weather Control Office...")
                break
                
            elif option:  # Solo mostrar error si se ingresó algo
                log_message("Opción inválida")
                time.sleep(1)
                
        except KeyboardInterrupt:
            clear_screen()
            print("\n[EV_W] Interrumpido por usuario")
            break
        except Exception as e:
            log_message(f"Error: {e}")
            time.sleep(1)


if __name__ == "__main__":
    # Cargar localizaciones desde archivo (opcional)
    load_locations_from_file()
    
    # Iniciar monitorización en segundo plano
    threading.Thread(target=monitor_weather, daemon=True).start()
    
    # Pequeña pausa para ver mensaje inicial
    time.sleep(1)
    
    # Mostrar menú interactivo
    try:
        menu_loop()
    except KeyboardInterrupt:
        print("\n[EV_W] Interrumpido por usuario")
