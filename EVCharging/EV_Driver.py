import sys
import time
import threading
import requests
from kafka import KafkaProducer, KafkaConsumer


CHARGE_DURATION_FILE = 10   # Duración estándar para cargas desde archivo


class DriverTerminal:
    def __init__(self, broker_ip, broker_port, driver_id):
        self.broker_ip = broker_ip
        self.broker_port = broker_port
        self.driver_id = driver_id
        self.central_api_url = f"http://{broker_ip}:8000"   # Central y Kafka están en la misma máquina
        self.charging = False                               # True mientras hay una carga en curso
        self.current_cp = None                              # ID del CP con el que se está cargando ahora
        self.running = True
        self.manual_charge_active = False                   # Carga iniciada desde el CP (no por el Driver)
        self.last_consumption = {"kwh": 0, "cost": 0}
        self.menu_blocked = False                           # Bloquea el menú mientras se espera el resultado de una carga
        self.pending_ack = False                            # Señal para que el bucle del menú espere un ENTER antes de redibujar el menú

        # Kafka Producer
        self.producer = KafkaProducer(
            bootstrap_servers=f"{broker_ip}:{broker_port}",
            value_serializer=lambda v: v.encode("utf-8")
        )

        # Kafka Consumer
        self.consumer = KafkaConsumer(
            "respuestas_central",
            bootstrap_servers=f"{broker_ip}:{broker_port}",
            value_deserializer=lambda v: v.decode("utf-8"),
            group_id=f"driver-{driver_id}",                     # group_id único por driver_id para que varios drivers coexistan y reciba tickets pendientes
            auto_offset_reset="latest",
            consumer_timeout_ms=1000
        )

        print(f"\n{'='*60}")
        print(f"  EV DRIVER - Sistema de Carga de Vehículos Eléctricos")
        print(f"{'='*60}")
        print(f"  Driver ID:    {self.driver_id}")
        print(f"  Broker:       {self.broker_ip}:{self.broker_port}")
        print(f"{'='*60}\n")

        # Hilo para escuchar Kafka en segundo plano sin bloquear el menú
        threading.Thread(target=self.listen_kafka, daemon=True).start()

    # Limpiar pantalla 
    def clear_screen(self):
        import os
        os.system('cls' if os.name == 'nt' else 'clear')

    # Mostrar menú principal
    def show_menu(self):
        print(f"\n{'─'*60}")
        print(f"  MENÚ PRINCIPAL - Driver {self.driver_id}")
        print(f"{'─'*60}")

        if self.charging:
            print(f"  Estado: CARGANDO en {self.current_cp}")

        else:
            print(f"  Estado: DISPONIBLE")

        print(f"{'─'*60}")
        print(f"  1. Ver puntos de carga disponibles")
        print(f"  2. Solicitar carga en un punto específico")
        print(f"  3. Cargar desde archivo ")
        print(f"  0. Salir")
        print(f"{'─'*60}")

    # Mostrar lista de CPs disponibles 
    def show_available_cps(self):
        print(f"\n{'='*60}")
        print(f"  PUNTOS DE CARGA DISPONIBLES")
        print(f"{'='*60}")

        try:
            res = requests.get(f"{self.central_api_url}/api/charging_points", timeout=3)    # Consulta el API REST de Central
            cps = res.json().get("data", [])
            if not cps:
                print("  No hay puntos de carga registrados en el sistema")

            else:
                print(f"\n  {'ID':<10} {'Dirección':<20} {'Precio':<12} {'Estado'}")
                print(f"  {'-'*56}")
                for cp in sorted(cps, key=lambda x: x['id']):
                    print(f"  {cp['id']:<10} {cp['address']:<20} "
                          f"{float(cp['price']):.2f}€/kWh    {cp['status']}")
                    
        except requests.exceptions.ConnectionError:
            print(f"  No se puede conectar con Central en {self.central_api_url}")
            print(f"  Verifica que Central está activa.")

        except Exception as e:
            print(f"  Error consultando Central: {e}")

        print(f"{'='*60}\n")


    # Solicitar una carga única
    def request_single_charge(self):
        print(f"\n{'─'*60}")
        print(f"  SOLICITAR CARGA ÚNICA")
        print(f"{'─'*60}")

        if self.charging:
            print(f"  Ya hay una carga en proceso en {self.current_cp}")
            print(f"  Por favor, espera a que termine.")
            input("\n  Presiona ENTER para continuar...")
            return

        # Mostrar CPs disponibles
        try:
            res = requests.get(f"{self.central_api_url}/api/charging_points", timeout=3)
            cps = res.json().get("data", [])
            active_cps = [cp['id'] for cp in cps if cp['status'] == 'ACTIVE']
            if active_cps:
                print(f"\n  CPs disponibles: {', '.join(active_cps)}")
            
            else:
                print(f"\n  No hay puntos de carga disponibles en este momento")
        
        except Exception:
            print(f"\n  (No se pudo consultar CPs — verifica que Central está activa en {self.central_api_url})")

        cp_id = input("\n  Introduce el ID del Punto de Carga: ").strip()

        if not cp_id:
            print("  ID vacío. Operación cancelada.")
            input("\n  Presiona ENTER para continuar...")
            return

        # Solicitar duración de la carga
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

        print(f"\n  Resumen de la solicitud:")
        print(f"     Punto de carga: {cp_id}")
        print(f"     Duración: {duration} segundos")

        # Bloquear el menú para que la salida de la carga no se mezcle con el menú principal
        self.menu_blocked = True
        self.request_charge(cp_id, duration)

        # Esperar para ver la respuesta
        print("\n  Esperando respuesta del sistema...")
        time.sleep(2)

        if self.charging:
            # Espera activa hasta que el hilo Kafka ponga charging=False al recibir TICKET o CHARGE_INTERRUPTED
            while self.charging:
                time.sleep(0.5)

            time.sleep(2)
            print("\n  Carga completada")

        self.menu_blocked = False
        input("\n  Presiona ENTER para volver al menú...")


    # Cargar lista de CPs desde un archivo
    def load_from_file(self):
        print(f"\n{'─'*60}")
        print(f"  CARGAR DESDE ARCHIVO")
        print(f"{'─'*60}")

        if self.charging:
            print(f"  Ya hay una carga en proceso")
            print(f"  Por favor, espera a que termine.")
            input("\n  Presiona ENTER para continuar...")
            return

        filename = input("\n  Introduce el nombre del archivo: ").strip()

        if not filename:
            print("  Operación cancelada.")
            input("\n  Presiona ENTER para continuar...")
            return

        try:
            with open(filename, "r") as f:
                cp_ids = [line.strip() for line in f if line.strip()]   # Cada línea del archivo contiene un ID de CP

            if not cp_ids:
                print("  El archivo está vacío")
                input("\n  Presiona ENTER para continuar...")
                return

            print(f"\n  Archivo cargado correctamente")
            print(f"  {len(cp_ids)} solicitudes encontradas: {', '.join(cp_ids)}")
            print(f"  Duración estándar por carga: {CHARGE_DURATION_FILE} segundos")

            confirm = input("\n  ¿Deseas procesar todas las solicitudes? (s/n): ").strip().lower()

            if confirm == 's':
                print(f"\n  Iniciando procesamiento de solicitudes...")
                print(f"  (Este proceso puede tardar varios minutos)")
                print(f"\n{'─'*60}\n")

                self.menu_blocked = True
                self.process_cp_list(cp_ids)
                self.menu_blocked = False

                input("\n  Presiona ENTER para volver al menú...")
            
            else:
                print("  Operación cancelada")
                input("\n  Presiona ENTER para continuar...")

        except FileNotFoundError:
            print(f"  Error: No se encontró el archivo '{filename}'")
            input("\n  Presiona ENTER para continuar...")
        
        except Exception as e:
            print(f"  Error al leer el archivo: {e}")
            input("\n  Presiona ENTER para continuar...")


    # Procesar lista de CPs 
    def process_cp_list(self, cp_ids):
        for i, cp_id in enumerate(cp_ids, 1):
            print(f"  [{i}/{len(cp_ids)}] Procesando: {cp_id} (duración: {CHARGE_DURATION_FILE}s)")
            self.request_charge(cp_id, CHARGE_DURATION_FILE)

            # Esperar a que termine la carga actual antes de lanzar la siguiente
            while self.charging:
                time.sleep(0.5)

            if i < len(cp_ids):
                # Pausa entre cargas para dar tiempo al CP y a Central a liberar el estado antes de la siguiente solicitud
                print(f"  Esperando 4 segundos antes de la siguiente solicitud...")
                time.sleep(4)
                print()

        print(f"\n{'='*60}")
        print(f"  TODAS LAS SOLICITUDES COMPLETADAS")
        print(f"{'='*60}\n")


    # Enviar solicitud de carga
    def request_charge(self, cp_id, duration):
        self.charging = True
        self.current_cp = cp_id

        # Formato del mensaje Kafka: REQUEST#<driver_id>#<cp_id>#<duration>
        request = f"REQUEST#{self.driver_id}#{cp_id}#{duration}"
        print(f"  Enviando solicitud de carga a {cp_id} ({duration}s)...")
        self.producer.send("peticiones_conductores", request)
        self.producer.flush()


    # Escuchar mensajes de Kafka
    def listen_kafka(self):
        while self.running:
            try:
                messages = self.consumer.poll(timeout_ms=500)

                for _, msgs in messages.items():
                    for msg in msgs:
                        self.process_message(msg.value)

                # Confirmar si se recibieron mensajes para no generar commits vacíos
                if messages:
                    self.consumer.commit()

            except Exception as e:
                print(f"  Error en Kafka: {e}")
                time.sleep(1)


    # Procesar mensaje recibido
    def process_message(self, message):
        parts = message.split("#")

        if len(parts) < 3:
            return

        msg_type = parts[0]
        driver_id = parts[1]
        cp_id = parts[2]

        # Descartar mensajes dirigidos a otros drivers porque todos comparten el mismo tópico "respuestas_central"
        if driver_id != self.driver_id:
            return

        # Puede venir tanto de petición normal como de carga manual del CP
        if msg_type == "ACCEPTED":
            print(f"\n\n  Carga autorizada en {cp_id}")
            print(f"  Iniciando proceso de carga...")

            # Si no estábamos esperando una carga es porque fue iniciada desde el CP
            if not self.charging:
                print(f"  Esta carga fue iniciada desde el punto de recarga")
                self.charging = True
                self.current_cp = cp_id
                self.manual_charge_active = True

        elif msg_type == "REJECTED":
            print(f"  Carga RECHAZADA en {cp_id}")
            print(f"  Motivo: Punto de carga no disponible")
            self.charging = False
            self.current_cp = None

        elif msg_type == "CONSUMPTION":
            # Solo mostrar si es nuestro CP actual
            if cp_id == self.current_cp:
                kwh = float(parts[3])
                cost = float(parts[4])
                print(f"  Consumo en tiempo real: {kwh:.2f} kWh | {cost:.2f}€")

        elif msg_type == "TICKET":
            # 'not self.current_cp' por si el driver volvió a arrancar después de caer y el ticket pendiente llega por Kafka gracias al group_id
            if cp_id == self.current_cp or not self.current_cp:
                kwh = float(parts[3])
                cost = float(parts[4])
                print(f"\n{'='*60}")
                print(f"  TICKET FINAL DE CARGA")
                print(f"{'='*60}")
                print(f"  Punto de carga: {cp_id}")
                print(f"  Energía consumida: {kwh:.2f} kWh")
                print(f"  Importe total: {cost:.2f}€")
                print(f"{'='*60}\n")

                self.charging = False
                self.current_cp = None
                self.manual_charge_active = False
                # Si el menú no está bloqueado por una carga se pide ACK para que el ticket sea visible antes de que se redibuje el menú
                if not self.menu_blocked:
                    self.pending_ack = True

        elif msg_type == "CENTRAL_DOWN":
            if cp_id == self.current_cp or not self.current_cp:
                print(f"\n{'!'*60}")
                print(f"  AVISO: Central se ha desconectado")
                print(f"  La carga en {cp_id} continúa en el Engine.")
                print(f"  Recibirás el ticket cuando Central vuelva a estar activa.")
                print(f"{'!'*60}\n")

        elif msg_type == "CHARGE_INTERRUPTED":
            # Manejar carga interrumpida
            if cp_id == self.current_cp or not self.current_cp:
                kwh = float(parts[3])
                cost = float(parts[4])
                reason = parts[5] if len(parts) > 5 else "motivo desconocido"

                print(f"\n{'='*60}")
                print(f"  CARGA INTERRUMPIDA")
                print(f"{'='*60}")
                print(f"  Punto de carga: {cp_id}")
                print(f"  Motivo: {reason}")
                print(f"  Energía consumida (parcial): {kwh:.2f} kWh")
                print(f"  Importe cobrado: {cost:.2f}€")
                print(f"{'='*60}\n")

                self.charging = False
                self.current_cp = None
                self.manual_charge_active = False
                if not self.menu_blocked:
                    self.pending_ack = True


    # Ejecutar el menú principal
    def run(self):
        while self.running:
            try:
                self.show_menu()
                option = input("\n  Selecciona una opción: ").strip()

                # Si llegó un ticket o interrupción mientras el menú estaba activo, pausar antes de redibujar el menú
                if self.pending_ack:
                    self.pending_ack = False
                    input("\n  Presiona ENTER para volver al menú...")
                    continue

                if option == "1":
                    self.show_available_cps()
                    input("  Presiona ENTER para continuar...")

                elif option == "2":
                    self.request_single_charge()

                elif option == "3":
                    self.load_from_file()

                elif option == "0":
                    print(f"\n  Cerrando aplicación...")
                    self.running = False
                    break

                else:
                    print(f"\n  Opción inválida. Intenta de nuevo.")
                    time.sleep(1)

            except KeyboardInterrupt:
                print(f"\n\n  Interrupción detectada. Cerrando...")
                self.running = False
                break

        # Cerrar conexiones
        self.consumer.close()
        self.producer.close()
        print(f"  Driver {self.driver_id} finalizado correctamente.\n")


# Leer argumentos de línea de comandos
def args():
    broker_ip    = sys.argv[1] if len(sys.argv) > 1 else 'localhost'
    broker_port  = sys.argv[2] if len(sys.argv) > 2 else '9092'
    driver_id    = sys.argv[3] if len(sys.argv) > 3 else 'Driver1'
    return broker_ip, broker_port, driver_id


if __name__ == "__main__":
    broker_ip, broker_port, driver_id = args()
    app = DriverTerminal(broker_ip, broker_port, driver_id)
    app.run()
