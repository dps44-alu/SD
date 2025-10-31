import sys
import time
from kafka import KafkaProducer, KafkaConsumer


CHARGE_DURATION = 7  # Segundos de carga simulada


# ---------------------------
# Driver
# ---------------------------
# Lee argumentos
def args():
    return sys.argv[1], sys.argv[2], sys.argv[3]


# Carga el ID de los CPs desde un archivo
def load_cp_ids(filename):
    with open(filename, "r") as f:
        ids = [line.strip() for line in f if line.strip()]
    return ids


# Lógica principal del driver
def main(broker_id, broker_port, driver_id):
    producer = KafkaProducer(
        bootstrap_servers=f"{broker_id}:{broker_port}",
        value_serializer=lambda v: v.encode("utf-8")
    )

    consumer = KafkaConsumer(
        "respuestas_central",
        bootstrap_servers=f"{broker_id}:{broker_port}",
        value_deserializer=lambda v: v.decode("utf-8"),
        group_id=f"driver-{driver_id}",
        auto_offset_reset="earliest",
        consumer_timeout_ms=15000  # Aumentado timeout
    )

    cp_ids = load_cp_ids("driver1.txt")

    for cp_id in cp_ids:
        # Enviar petición de carga
        request = f"REQUEST#{driver_id}#{cp_id}#{CHARGE_DURATION}"
        print(f"[Driver] Enviando petición: {request}")
        producer.send("peticiones_conductores", request)
        producer.flush()

        # Esperar respuesta de Central
        print(f"[Driver] Esperando respuesta de Central...")
        response_received = False
        
        for msg in consumer:
            response = msg.value
            parts = response.split("#")
            
            # Verificar que el mensaje es para este driver y CP
            if len(parts) >= 3 and parts[1] == driver_id and parts[2] == cp_id:
                response_received = True
                
                if parts[0] == "ACCEPTED":
                    print(f"[Driver] Punto {cp_id} asignado correctamente")
                    print(f"[Driver] Esperando inicio de carga...")
                    
                    # Escuchar actualizaciones de consumo y ticket final
                    charging_complete = False
                    
                    while not charging_complete:
                        try:
                            msg_updates = consumer.poll(timeout_ms=1000)
                            for _, messages in msg_updates.items():
                                for msg in messages:
                                    update = msg.value
                                    update_parts = update.split("#")
                                    
                                    if len(update_parts) >= 3 and update_parts[1] == driver_id and update_parts[2] == cp_id:
                                        
                                        if update_parts[0] == "CONSUMPTION":
                                            kwh = float(update_parts[3])
                                            cost = float(update_parts[4])
                                            print(f"[Driver] Consumo: {kwh:.2f} kWh | Coste: {cost:.2f}€")
                                        
                                        elif update_parts[0] == "TICKET":
                                            kwh = float(update_parts[3])
                                            cost = float(update_parts[4])
                                            print(f"\n[Driver] TICKET FINAL:")
                                            print(f"         CP: {cp_id}")
                                            print(f"         Energía: {kwh:.2f} kWh")
                                            print(f"         Importe: {cost:.2f}€")
                                            charging_complete = True
                                            break
                        
                        except Exception as e:
                            print(f"[Driver] Error escuchando actualizaciones: {e}")
                            break
                    
                    # Esperar 4 segundos antes del siguiente
                    print(f"[Driver] Esperando 4s antes de la siguiente petición...\n")
                    break
                    
                elif parts[0] == "REJECTED":
                    print(f"[Driver] Punto {cp_id} no disponible")
                    break
        
        if not response_received:
            print(f"[Driver] ⚠ No se recibió respuesta para {cp_id} (timeout)")
        
        time.sleep(4)

    # Cerrar conexiones
    print(f"[Driver] Todas las peticiones completadas. Cerrando conexiones...")
    consumer.close()
    producer.close()
    print(f"[Driver] Driver {driver_id} finalizado correctamente.")


# Inicia el programa
if __name__ == "__main__":
    broker_id, broker_port, driver_id = args()
    main(broker_id, broker_port, driver_id)