import sys
import time
import threading
from kafka import KafkaProducer, KafkaConsumer


CHARGE_DURATION = 7  # Segundos de carga simulada


class DriverTerminal:
    def __init__(self, broker_ip, broker_port, driver_id):
        self.broker_ip = broker_ip
        self.broker_port = broker_port
        self.driver_id = driver_id
        self.charging = False
        self.current_cp = None
        self.available_cps = {}
        self.running = True
        self.manual_charge_active = False  # Nueva flag para cargas desde CP
        self.last_consumption = {"kwh": 0, "cost": 0}  # Último consumo recibido
        
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
            group_id=f"driver-{driver_id}",
            auto_offset_reset="latest",
            consumer_timeout_ms=1000
        )
        
        print(f"\n{'='*60}")
        print(f"  EV DRIVER - Sistema de Carga de Vehículos Eléctricos")
        print(f"{'='*60}")
        print(f"  Driver ID:    {self.driver_id}")
        print(f"  Broker:       {self.broker_ip}:{self.broker_port}")
        print(f"{'='*60}\n")
        
        # Iniciar hilos
        threading.Thread(target=self.listen_kafka, daemon=True).start()
        threading.Thread(target=self.update_cp_list, daemon=True).start()
    
    def clear_screen(self):
        """Limpiar pantalla (multiplataforma)"""
        import os
        os.system('cls' if os.name == 'nt' else 'clear')
    
    def show_menu(self):
        """Mostrar menú principal"""
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
    
    def show_available_cps(self):
        """Mostrar lista de CPs disponibles"""
        print(f"\n{'='*60}")
        print(f"  PUNTOS DE CARGA DISPONIBLES")
        print(f"{'='*60}")
        
        if not self.available_cps:
            print("  No hay información de puntos de carga")
            print("  (Esperando datos del sistema...)")
        else:
            print(f"\n  {'ID':<10} {'Dirección':<20} {'Precio':<12} {'Estado'}")
            print(f"  {'-'*56}")
            
            for cp_id, info in sorted(self.available_cps.items()):
                status = info["status"]
                address = info["address"]
                price = info["price"]
                
                print(f"  {cp_id:<10} {address:<20} {price:.2f}€/kWh    {status}")
        
        print(f"{'='*60}\n")
    
    def request_single_charge(self):
        """Solicitar una carga única"""
        print(f"\n{'─'*60}")
        print(f"  SOLICITAR CARGA ÚNICA")
        print(f"{'─'*60}")
        
        if self.charging:
            print(f"  Ya hay una carga en proceso en {self.current_cp}")
            print(f"  Por favor, espera a que termine.")
            input("\n  Presiona ENTER para continuar...")
            return
        
        # Mostrar CPs disponibles primero
        if self.available_cps:
            print(f"\n  CPs disponibles: {', '.join([cp for cp, info in self.available_cps.items() if info['status'] == 'ACTIVE'])}")
        
        cp_id = input("\n  Introduce el ID del Punto de Carga: ").strip()
        
        if not cp_id:
            print("  ID vacío. Operación cancelada.")
            input("\n  Presiona ENTER para continuar...")
            return
        
        self.request_charge(cp_id)
        
        # Esperar un momento para ver la respuesta
        print("\n  Esperando respuesta del sistema...")
        time.sleep(2)

        if self.charging:
            while self.charging:
                time.sleep(0.5)
            
            time.sleep(2)
            print("\n  Carga completada")
    
        input("\n  Presiona ENTER para volver al menú...")
    
    def load_from_file(self):
        """Cargar lista de CPs desde un archivo"""
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
                cp_ids = [line.strip() for line in f if line.strip()]
            
            if not cp_ids:
                print("  El archivo está vacío")
                input("\n  Presiona ENTER para continuar...")
                return
            
            print(f"\n  Archivo cargado correctamente")
            print(f"  {len(cp_ids)} solicitudes encontradas: {', '.join(cp_ids)}")
            
            confirm = input("\n  ¿Deseas procesar todas las solicitudes? (s/n): ").strip().lower()
            
            if confirm == 's':
                print(f"\n  Iniciando procesamiento de solicitudes...")
                print(f"  (Este proceso puede tardar varios minutos)")
                print(f"\n{'─'*60}\n")
                
                self.process_cp_list(cp_ids)
            
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
    
    def process_cp_list(self, cp_ids):
        """Procesar lista de CPs secuencialmente"""
        for i, cp_id in enumerate(cp_ids, 1):
            print(f"  [{i}/{len(cp_ids)}] Procesando: {cp_id}")
            self.request_charge(cp_id)
            
            while self.charging:
                time.sleep(0.5)
            
            if i < len(cp_ids):
                print(f"  Esperando 4 segundos antes de la siguiente solicitud...")
                time.sleep(4)
                print()
        
        print(f"\n{'='*60}")
        print(f"  TODAS LAS SOLICITUDES COMPLETADAS")
        print(f"{'='*60}\n")
    
    def request_charge(self, cp_id):
        """Enviar solicitud de carga"""
        self.charging = True
        self.current_cp = cp_id
        
        request = f"REQUEST#{self.driver_id}#{cp_id}#{CHARGE_DURATION}"
        print(f"  Enviando solicitud de carga a {cp_id}...")
        self.producer.send("peticiones_conductores", request)
        self.producer.flush()
    
    def listen_kafka(self):
        """Escuchar mensajes de Kafka"""
        while self.running:
            try:
                messages = self.consumer.poll(timeout_ms=500)
                
                for _, msgs in messages.items():
                    for msg in msgs:
                        self.process_message(msg.value)
                        
            except Exception as e:
                print(f"  Error en Kafka: {e}")
                time.sleep(1)
    
    def process_message(self, message):
        """Procesar mensaje recibido"""
        parts = message.split("#")
        
        if len(parts) < 3:
            return
        
        msg_type = parts[0]
        driver_id = parts[1]
        cp_id = parts[2]
        
        # Filtrar mensajes para este driver
        if driver_id != self.driver_id:
            return
        
        if msg_type == "ACCEPTED":
            # Puede venir tanto de petición normal como de carga manual del CP
            print(f"\n  ✅ Carga autorizada en {cp_id}")
            print(f"  Iniciando proceso de carga...")
            
            # Si no estábamos esperando una carga, es porque fue iniciada desde el CP
            if not self.charging:
                print(f"  📍 Esta carga fue iniciada desde el punto de recarga")
                self.charging = True
                self.current_cp = cp_id
            
        elif msg_type == "REJECTED":
            print(f"  ❌ Carga RECHAZADA en {cp_id}")
            print(f"  Motivo: Punto de carga no disponible")
            self.charging = False
            self.current_cp = None
            
        elif msg_type == "CONSUMPTION":
            # Solo mostrar si es nuestro CP actual
            if cp_id == self.current_cp:
                kwh = float(parts[3])
                cost = float(parts[4])
                print(f"  ⚡ Consumo en tiempo real: {kwh:.2f} kWh | {cost:.2f}€")
            
        elif msg_type == "TICKET":
            # Solo procesar si es nuestro CP
            if cp_id == self.current_cp or not self.current_cp:
                kwh = float(parts[3])
                cost = float(parts[4])
                print(f"\n{'='*60}")
                print(f"  🧾 TICKET FINAL DE CARGA")
                print(f"{'='*60}")
                print(f"  Punto de carga: {cp_id}")
                print(f"  Energía consumida: {kwh:.2f} kWh")
                print(f"  Importe total: {cost:.2f}€")
                print(f"{'='*60}\n")
                
                self.charging = False
                self.current_cp = None
    
    def update_cp_list(self):
        """Actualizar lista de CPs disponibles desde BD"""
        import json
        
        while self.running:
            try:
                with open("db.json", "r") as f:
                    db = json.load(f)
                
                new_cps = {}
                for cp in db.get("charging_points", []):
                    cp_id = cp["id"]
                    new_cps[cp_id] = {
                        "status": cp["status"],
                        "address": cp["address"],
                        "price": cp["price"]
                    }
                
                self.available_cps = new_cps
                
            except Exception as e:
                pass
            
            time.sleep(2)
    
    def run(self):
        """Ejecutar el menú principal"""
        while self.running:
            try:
                self.show_menu()
                option = input("\n  Selecciona una opción: ").strip()
                
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


def args():
    """Leer argumentos de línea de comandos"""
    if len(sys.argv) != 4:
        print("Uso: python EV_Driver.py <broker_ip> <broker_port> <driver_id>")
        sys.exit(1)
    return sys.argv[1], sys.argv[2], sys.argv[3]


if __name__ == "__main__":
    broker_ip, broker_port, driver_id = args()
    app = DriverTerminal(broker_ip, broker_port, driver_id)
    app.run()