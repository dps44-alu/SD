import sys
import time
import threading
from kafka import KafkaProducer, KafkaConsumer


CHARGE_DURATION = 7     # Segundos de carga simulada


# ---------------------------
# Driver
# ---------------------------
# Lee argumentos
def args ():
    return sys.argv[1], sys.argv[2], sys.argv[3]


# Carga los Ids de los CPs que el conductor va a utilizardesde un archivo
def load_cp_ids (filename):
    with open(filename, "r") as f:
        ids = [line.strip() for line in f if line.strip()]
    return ids


# Maneja la solicitud de CPs y la impresión del consumo en tiempo real
def main (broker_id, broker_port, driver_id):
    producer = KafkaProducer(
        bootstrap_servers = f"{broker_id}:{broker_port}",
        value_serializer = lambda v: v.encode("utf-8")
    )

    consumer = KafkaConsumer(
        "respuestas_central",
        bootstrap_servers = f"{broker_id}:{broker_port}",
        value_deserializer = lambda v: v.decode("utf-8"),
        group_id = f"driver-{driver_id}",
        auto_offset_reset = "earliest",
        consumer_timeout_ms = 10000
    )

    cp_ids = load_cp_ids("driver1.txt")

    for cp_id in cp_ids:
        # Envia una petición por un CP al Central
        request = f"REQUEST#{driver_id}#{cp_id}#{CHARGE_DURATION}"
        print(f"[Driver] Enviando petición: {request}")
        producer.send("peticiones_conductores", request)
        producer.flush()

        # Espera la respuesta de Central
        print(f"[Driver] Esperando respuesta de Central...")
        response_received = False
        
        for msg in consumer:
            response = msg.value
            print(f"[Driver] Respuesta recibida: {response}")

            # Separa las partes del mensaje
            parts = response.split("#")
            if parts[1] == driver_id and parts[2] == cp_id:                                 
                response_received = True
                if parts[0] == "ACCEPTED":
                    print(f"[Driver] Punto {cp_id} asignado correctamente")
                    
                    # Usa el CP y escucha actualizaciones de consumo
                    print(f"[Driver] Usando {cp_id} durante {CHARGE_DURATION} segundos...")
                    
                    # Escucha las actualizaciones del consumo 
                    start_time = time.time()

                    while time.time() - start_time < CHARGE_DURATION:
                        try:
                            msg_consumption = consumer.poll(timeout_ms = 1000)
                            for _, messages in msg_consumption.items():
                                for msg in messages:
                                    response = msg.value
                                    parts_consumption = response.split("#")
                                    
                                    if parts_consumption[0] == "CONSUMPTION" and parts_consumption[1] == driver_id and parts_consumption[2] == cp_id:
                                        kwh = float(parts_consumption[3])
                                        cost = float(parts_consumption[4])
                                        print(f"[Driver] Consumo actual: {kwh:.2f} kWh | Coste: {cost:.2f}€")

                        except Exception as e:
                            pass

                    # Libera al CP
                    release = f"RELEASE#{driver_id}#{cp_id}"
                    print(f"[Driver] Liberando {cp_id}")
                    producer.send("peticiones_conductores", release)
                    producer.flush()

                    # Espera confirmación de liberación de Central
                    print(f"[Driver] Esperando confirmación de liberación...")
                    for msg_release in consumer:
                        response_release = msg_release.value
                        parts_release = response_release.split("#")
                        if parts_release[0] == "RELEASED" and parts_release[1] == driver_id and parts_release[2] == cp_id:
                            print(f"[Driver] {cp_id} liberado correctamente")
                            break
                    
                    break
                    
                elif parts[0] == "REJECTED":
                    print(f"[Driver] Punto {cp_id} no disponible")
                    break
        
        if not response_received:
            print(f"[Driver] No se recibió respuesta para {cp_id} (timeout)")
        
        time.sleep(5)

    # Cierra las conexiones
    print(f"[Driver] Todas las peticiones completadas. Cerrando conexiones...")
    consumer.close()
    producer.close()
    print(f"[Driver] Driver {driver_id} finalizado correctamente.")


# Inicia el programa
if __name__ == "__main__":
    broker_id, broker_port, driver_id = args()
    main(broker_id, broker_port, driver_id)