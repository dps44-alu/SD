import sys
import time
from kafka import KafkaProducer, KafkaConsumer

def args():
    return sys.argv[1], sys.argv[2], sys.argv[3]


def load_cp_ids(filename):
    with open(filename, "r") as f:
        ids = [line.strip() for line in f if line.strip()]
    return ids


def main(broker_id, broker_port, driver_id):
    producer = KafkaProducer(
        bootstrap_servers=f"{broker_id}:{broker_port}",
        value_serializer=lambda v: v.encode("utf-8")
    )

    consumer = KafkaConsumer(
        "respuestas_central",
        bootstrap_servers=f"{broker_id}:{broker_port}",
        value_deserializer=lambda v: v.decode("utf-8"),
        group_id=f"driver-{driver_id}"
    )

    cp_ids = load_cp_ids("driver1.txt")

    for cp_id in cp_ids:
        # 1. Enviar petición al Central
        request = f"REQUEST#{driver_id}#{cp_id}"
        print(f"[Driver] Enviando petición: {request}")
        producer.send("peticiones_conductores", request)
        producer.flush()

        # 2. Esperar respuesta
        print(f"[Driver] Esperando respuesta de Central...")
        for msg in consumer:
            response = msg.value
            print(f"[Driver] Respuesta recibida: {response}")

            parts = response.split("#")
            if parts[1] == driver_id and parts[2] == cp_id:  # la respuesta es para este driver
                if parts[0] == "ACCEPTED":
                    print(f"[Driver] Punto {cp_id} asignado correctamente")
                    break
                elif parts[0] == "REJECTED":
                    print(f"[Driver] Punto {cp_id} no disponible")
                    continue
        
        # 3. Usar CP durante 5 segundos
        print(f"[Driver] Usando {cp_id} durante 5s...")
        time.sleep(5)

        # 4. Liberar CP
        release = f"RELEASE#{driver_id}#{cp_id}"
        print(f"[Driver] Liberando {cp_id}")
        producer.send("peticiones_conductores", release)
        producer.flush()

        # 5. Esperar confirmación de Central
        for msg in consumer:
            response = msg.value
            parts = response.split("#")
            if parts[0] == "RELEASED" and parts[1] == driver_id and parts[2] == cp_id:
                print(f"[Driver] {cp_id} liberado correctamente")
                break

        time.sleep(5)  # esperar antes de la siguiente petición

if __name__ == "__main__":
    broker_id, broker_port, driver_id = args()
    main(broker_id, broker_port, driver_id)
