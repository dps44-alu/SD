import sys
import time
import requests
import threading
import json
import os


BASE_URL = "https://api.openweathermap.org/data/2.5/weather"
API_KEY_FILE = "ev_w_config.json"

# Configuración (se establece en main antes de arrancar hilos)
API_KEY = None
CENTRAL_API_URL = None

# Almacén de localizaciones y estados
LOCATIONS = {}          # {cp_id: city_name}
ALERT_STATUS = {}       # {cp_id: bool} - True si hay alerta activa

# Sistema de mensajes
MESSAGE_BUFFER = []
MESSAGE_LOCK = threading.Lock()
MENU_REFRESH_EVENT = threading.Event()


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
            MESSAGE_BUFFER.clear()
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
    print(f"  CONFIGURACIÓN API KEY — OPENWEATHER")
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
        pass  # silencioso: no saturar el log con errores de red


def notify_central_alert(cp_id, alert_type):
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


def monitor_weather():
    log_message("Iniciando monitorización de clima (cada 4 segundos)")
    while True:
        for cp_id, city in list(LOCATIONS.items()):
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
    print(f"  2. Eliminar localización")
    print(f"  3. Ver estado actual")
    print(f"  4. Cambiar API key")
    print(f"  0. Salir")
    print(f"{'='*60}")


def menu_loop():
    global API_KEY

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
                        log_message(f"Cambiando ciudad de {cp_id}: {old_city} → {city}")
                        if ALERT_STATUS.get(cp_id, False):
                            log_message(f"Cancelando alerta previa de {cp_id} ({old_city})")
                            notify_central_alert(cp_id, "CANCEL")
                        ALERT_STATUS[cp_id] = False

                    LOCATIONS[cp_id] = city
                    if cp_id not in ALERT_STATUS:
                        ALERT_STATUS[cp_id] = False

                    log_message(f"{cp_id} configurado para monitorizar {city}")
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
                continue

            elif option == "4":
                clear_screen()
                display_pending_messages()
                print(f"\n  API key actual: {'*'*(len(API_KEY)-4) + API_KEY[-4:] if API_KEY else '(vacía)'}")
                new_key = input("  Nueva API key (ENTER para cancelar): ").strip()
                if new_key:
                    API_KEY = new_key
                    save_api_key(new_key)
                    log_message("API key actualizada y guardada")
                else:
                    log_message("Cambio de API key cancelado")
                time.sleep(1)

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


def check_central_api(url):
    """Verifica que la URL apunta a la API REST de Central (no al puerto TCP)."""
    try:
        r = requests.get(f"{url}/api/health", timeout=3)
        data = r.json()
        if data.get("status") == "SUCCESS":
            print(f"[EV_W] API Central verificada correctamente en {url}")
            return True
        print(f"[EV_W] Respuesta inesperada del servidor en {url}: {data}")
        return False
    except (requests.exceptions.JSONDecodeError, ValueError):
        print(f"\n[EV_W] ERROR: El servidor en {url} no devuelve JSON.")
        print(f"[EV_W]  → Probablemente estás usando el puerto TCP de Central (normalmente 5000).")
        print(f"[EV_W]  → EV_W debe apuntar al puerto de la API REST (por defecto: 8000).")
        print(f"[EV_W]  → Usa: python3 EV_W.py <IP_CENTRAL> 8000")
        return False
    except requests.exceptions.Timeout:
        print(f"\n[EV_W] ERROR: El servidor en {url} no respondió (timeout).")
        print(f"[EV_W]  → Si usaste el puerto TCP (5000), cámbialo al de la API REST (8000).")
        print(f"[EV_W]  → Usa: python3 EV_W.py <IP_CENTRAL> 8000")
        return False
    except requests.exceptions.ConnectionError:
        print(f"\n[EV_W] ERROR: No se pudo conectar a {url}.")
        print(f"[EV_W]  → Asegúrate de que EV_Central está corriendo antes de lanzar EV_W.")
        print(f"[EV_W]  → Puerto correcto del API REST: 8000 (ej: python3 EV_W.py localhost 8000)")
        return False
    except Exception as e:
        print(f"\n[EV_W] AVISO: No se pudo verificar el API Central en {url}: {e}")
        print(f"[EV_W]  → Puerto del API REST de Central: 8000")
        return False


if __name__ == "__main__":
    central_ip, central_port = args()

    CENTRAL_API_URL = f"http://{central_ip}:{central_port}"

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

    threading.Thread(target=monitor_weather, daemon=True).start()

    time.sleep(1)

    try:
        menu_loop()
    except KeyboardInterrupt:
        print("\n[EV_W] Interrumpido por usuario")
