import sys
import time
import requests
import threading
import json
import os


BASE_URL = "https://api.openweathermap.org/data/2.5/weather"
API_KEY_FILE = "ev_w_config.json"

# Configuración base antes de arrancar hilos
API_KEY = None
CENTRAL_API_URL = None

# Almacén de localizaciones y estados
LOCATIONS = {}          # {cp_id: city_name}
ALERT_STATUS = {}       # True si hay alerta activa : {cp_id: bool}

# Sistema de mensajes
MESSAGE_BUFFER = []                     # Acumula líneas generadas por hilos en segundo plano
MESSAGE_LOCK = threading.Lock()         # Protege el acceso concurrente al buffer
MENU_REFRESH_EVENT = threading.Event()  # Señala al menú que hay mensajes nuevos para mostrar


# Notificar al hilo del menú para que redibuje en cuanto pueda
def log_message(message):
    with MESSAGE_LOCK:
        MESSAGE_BUFFER.append(f"[{time.strftime('%H:%M:%S')}] {message}")

    MENU_REFRESH_EVENT.set()


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def display_pending_messages():
    with MESSAGE_LOCK:
        if MESSAGE_BUFFER:
            print("\n" + "=" * 60)
            print("  MENSAJES DEL SISTEMA")
            print("=" * 60)
            for msg in MESSAGE_BUFFER:
                print(f"  {msg}")
            print("=" * 60)
            MESSAGE_BUFFER.clear()              # Vaciar el buffer tras mostrarlo para que no se repitan
            return True
        
    return False


# --- Persistencia de API key ---
def load_api_key():
    try:
        with open(API_KEY_FILE, "r") as f:
            data = json.load(f)
            return data.get("api_key", "").strip()
        
    except FileNotFoundError:
        return ""


def save_api_key(key):
    with open(API_KEY_FILE, "w") as f:
        json.dump({"api_key": key}, f)


def prompt_api_key():
    print(f"\n{'='*60}")
    print(f"  CONFIGURACIÓN API KEY - OPENWEATHER")
    print(f"{'='*60}")
    print(f"  No se encontró una API key configurada.")
    print(f"  Regístrate gratis en https://openweathermap.org/")
    print(f"{'='*60}")
    key = input("  Introduce tu API key: ").strip()
    if key:
        save_api_key(key)
        print(f"  API key guardada en {API_KEY_FILE}")

    return key


# --- Localizaciones ---
def load_locations_from_file(filename="locations.txt"):
    global LOCATIONS
    try:
        with open(filename, "r") as f:
            for line in f:
                line = line.strip()                         # Ignorar líneas vacías y comentarios
                if line and not line.startswith("#"):
                    parts = line.split(",")
                    # Formato esperado por línea: <CP_ID>,<ciudad>
                    if len(parts) == 2:
                        cp_id, city = parts
                        LOCATIONS[cp_id.strip()] = city.strip()
                        ALERT_STATUS[cp_id.strip()] = False

        log_message(f"Localizaciones cargadas: {list(LOCATIONS.keys())}")

    except FileNotFoundError:
        log_message(f"Archivo {filename} no encontrado. Usar menú para añadir localizaciones.")


# --- OpenWeather ---
def get_temperature(city):
    try:
        params = {"q": city, "appid": API_KEY, "units": "metric"}
        response = requests.get(BASE_URL, params=params, timeout=5)
        if response.status_code == 200:
            return response.json()["main"]["temp"]
        
        else:
            log_message(f"Error consultando {city}: HTTP {response.status_code}")
            return None
        
    except Exception as e:
        log_message(f"Error obteniendo temperatura de {city}: {e}")
        return None


# --- Notificaciones a Central ---
def push_weather_to_central(cp_id, city, temp, alert):
    try:
        payload = {"cp_id": cp_id, "city": city, "temp": temp, "alert": alert}
        requests.post(f"{CENTRAL_API_URL}/weather/data", json=payload, timeout=2)

    except Exception:
        pass            # silencioso para no saturar el log con errores de red


def notify_central_alert(cp_id, alert_type):
    # alert_type="ALERT"    ->  temp < 0°C          ->  Central pone el CP en OUT_OF_ORDER
    # alert_type="CANCEL"   ->  temp vuelve a ≥ 0°C ->  Central restaura el CP a ACTIVE
    try:
        payload = {
            "cp_id": cp_id,
            "alert_type": alert_type,
            "reason": "Temperatura bajo 0°C" if alert_type == "ALERT" else "Temperatura normalizada"
        }
        response = requests.post(f"{CENTRAL_API_URL}/weather/alert", json=payload, timeout=3)
        if response.status_code == 200:
            log_message(f"{alert_type} enviada correctamente para {cp_id}")
            return True
        
        else:
            log_message(f"Error enviando {alert_type} para {cp_id}: HTTP {response.status_code}")
            return False
        
    except Exception as e:
        log_message(f"Error comunicando con Central: {e}")
        return False


# Consulta inmediata y puntual al añadir o cambiar una localización, se ejecuta en un hilo aparte para no bloquear el menú
def check_temperature_now(cp_id):
    if cp_id not in LOCATIONS:
        return
    
    city = LOCATIONS[cp_id]
    log_message(f"Chequeando temperatura actual de {city}...")
    time.sleep(1)
    temp = get_temperature(city)
    if temp is not None:
        log_message(f"{cp_id} ({city}): {temp:.1f}°C")
        push_weather_to_central(cp_id, city, temp, ALERT_STATUS[cp_id])
        if temp < 0 and not ALERT_STATUS[cp_id]:
            log_message(f"ALERTA: {cp_id} temperatura crítica ({temp:.1f}°C)")
            if notify_central_alert(cp_id, "ALERT"):
                ALERT_STATUS[cp_id] = True

        elif temp >= 0 and ALERT_STATUS[cp_id]:
            log_message(f"NORMALIZADO: {cp_id} temperatura restaurada ({temp:.1f}°C)")
            if notify_central_alert(cp_id, "CANCEL"):
                ALERT_STATUS[cp_id] = False


# Consulta OpenWeather cada 4 segundos para cada CP registrado y actualiza Central con temperatura y alertas
def monitor_weather():
    log_message("Iniciando monitorización de clima (cada 4 segundos)")
    while True:
        for cp_id, city in list(LOCATIONS.items()):
            # list() para iterar sobre una copia
            temp = get_temperature(city)
            if temp is not None:
                log_message(f"{cp_id} ({city}): {temp:.1f}°C")
                push_weather_to_central(cp_id, city, temp, ALERT_STATUS[cp_id])
                if temp < 0 and not ALERT_STATUS[cp_id]:
                    log_message(f"ALERTA: {cp_id} temperatura crítica ({temp:.1f}°C)")
                    if notify_central_alert(cp_id, "ALERT"):
                        ALERT_STATUS[cp_id] = True

                elif temp >= 0 and ALERT_STATUS[cp_id]:
                    log_message(f"NORMALIZADO: {cp_id} temperatura restaurada ({temp:.1f}°C)")
                    if notify_central_alert(cp_id, "CANCEL"):
                        ALERT_STATUS[cp_id] = False

        time.sleep(4)


# --- Menú ---
def show_menu():
    clear_screen()
    has_messages = display_pending_messages()
    if has_messages:
        print()

    print(f"{'='*60}")
    print(f"  EV_W - WEATHER CONTROL OFFICE")
    print(f"  Central: {CENTRAL_API_URL}")
    print(f"  API Key: {'*'*(len(API_KEY)-4) + API_KEY[-4:] if API_KEY else '(no configurada)'}")
    print(f"{'='*60}")
    print(f"  Localizaciones monitorizadas:")
    if LOCATIONS:
        for cp_id, city in LOCATIONS.items():
            status = "ALERTA" if ALERT_STATUS.get(cp_id, False) else "OK"
            print(f"    {cp_id}: {city} - {status}")

    else:
        print(f"    (ninguna)")

    print(f"{'='*60}")
    print(f"  1. Añadir / cambiar localización")
    print(f"  2. Ver estado actual")
    print(f"  0. Salir")
    print(f"{'='*60}")


def menu_loop():
    global API_KEY

    def monitor_messages():
        # Hilo que manteniene activo el sistema de eventos sin ocupar el hilo del menú
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
                if LOCATIONS:
                    print("\n  CPs ya registrados:")
                    for cp_id, city in LOCATIONS.items():
                        print(f"    - {cp_id}: {city}")

                    print("\n  (Si usas un CP existente, se actualizará su ciudad)")

                cp_id = input("\n  ID del CP: ").strip()
                city = input("  Ciudad: ").strip()

                if cp_id and city:
                    if cp_id in LOCATIONS and LOCATIONS[cp_id] != city:
                        old_city = LOCATIONS[cp_id]
                        log_message(f"Cambiando ciudad de {cp_id}: {old_city} -> {city}")
                        # Si había alerta activa para la ciudad anterior, cancelarla en Central antes de reasignar la localización
                        if ALERT_STATUS.get(cp_id, False):
                            log_message(f"Cancelando alerta previa de {cp_id} ({old_city})")
                            notify_central_alert(cp_id, "CANCEL")

                        ALERT_STATUS[cp_id] = False

                    LOCATIONS[cp_id] = city
                    if cp_id not in ALERT_STATUS:
                        ALERT_STATUS[cp_id] = False

                    log_message(f"{cp_id} configurado para monitorizar {city}")
                    threading.Thread(target=check_temperature_now, args=(cp_id,), daemon=True).start()  # Lanza consulta en hilo aparte para no bloquear el menú

                else:
                    log_message("Datos incompletos, operación cancelada")

                time.sleep(1)

            elif option == "2":
                continue            # La opción 2 solo redibuja el menú

            elif option == "0":
                clear_screen()
                print("\n[EV_W] Cerrando Weather Control Office...")
                break

            elif option:
                log_message("Opción inválida")
                time.sleep(1)

        except KeyboardInterrupt:
            clear_screen()
            print("\n[EV_W] Interrumpido por usuario")
            break

        except Exception as e:
            log_message(f"Error: {e}")
            time.sleep(1)


def args():
    central_ip   = sys.argv[1] if len(sys.argv) > 1 else 'localhost'
    central_port = int(sys.argv[2]) if len(sys.argv) > 2 else 8000
    return central_ip, central_port


# Verifica que la URL apunta a la API REST de Central (no al puerto TCP)
def check_central_api(url):
    try:
        r = requests.get(f"{url}/api/health", timeout=3)
        data = r.json()
        if data.get("status") == "SUCCESS":
            print(f"[EV_W] API Central verificada correctamente en {url}")
            return True
        
        print(f"[EV_W] Respuesta inesperada del servidor en {url}: {data}")
        return False
    
    except (requests.exceptions.JSONDecodeError, ValueError):
        # JSONDecodeError indica casi siempre que se apuntó al puerto TCP (5000) en lugar del puerto REST (8000): el TCP devuelve bytes sin formato JSON.
        print(f"\n[EV_W] ERROR: El servidor en {url} no devuelve JSON.")
        print(f"[EV_W]  -> Probablemente estás usando el puerto TCP de Central (normalmente 5000).")
        print(f"[EV_W]  -> EV_W debe apuntar al puerto de la API REST (por defecto: 8000).")
        print(f"[EV_W]  -> Usa: python3 EV_W.py <IP_CENTRAL> 8000")
        return False
    
    except requests.exceptions.Timeout:
        print(f"\n[EV_W] ERROR: El servidor en {url} no respondió (timeout).")
        print(f"[EV_W]  -> Si usaste el puerto TCP (5000), cámbialo al de la API REST (8000).")
        print(f"[EV_W]  -> Usa: python3 EV_W.py <IP_CENTRAL> 8000")
        return False
    
    except requests.exceptions.ConnectionError:
        print(f"\n[EV_W] ERROR: No se pudo conectar a {url}.")
        print(f"[EV_W]  -> Asegúrate de que EV_Central está corriendo antes de lanzar EV_W.")
        print(f"[EV_W]  -> Puerto correcto del API REST: 8000 (ej: python3 EV_W.py localhost 8000)")
        return False
    
    except Exception as e:
        print(f"\n[EV_W] AVISO: No se pudo verificar el API Central en {url}: {e}")
        print(f"[EV_W]  -> Puerto del API REST de Central: 8000")
        return False


if __name__ == "__main__":
    central_ip, central_port = args()

    CENTRAL_API_URL = f"http://{central_ip}:{central_port}"

    # Verificar primero que la URL apunta al API REST y no al puerto TCP
    print(f"[EV_W] Conectando al API REST de Central en {CENTRAL_API_URL} ...")
    if not check_central_api(CENTRAL_API_URL):
        print("[EV_W] Cerrando. Corrige la URL del API y vuelve a intentarlo.")
        sys.exit(1)

    # Cargar API key: primero del archivo, si no hay se pide al usuario
    API_KEY = load_api_key()
    if not API_KEY:
        API_KEY = prompt_api_key()
        if not API_KEY:
            print("[EV_W] Error: se necesita una API key para arrancar. Cerrando.")
            sys.exit(1)

    load_locations_from_file()

    # Hilo que monitoriza el clima en segundo plano, termina con el proceso principal
    threading.Thread(target=monitor_weather, daemon=True).start()

    time.sleep(1)

    try:
        menu_loop()
        
    except KeyboardInterrupt:
        print("\n[EV_W] Interrumpido por usuario")
