FROM python:3.11-slim

WORKDIR /app

COPY . /app

# Instalar librerías necesarias para Kafka (aunque scripts estén vacíos)
RUN pip install --no-cache-dir kafka-python

CMD ["python3", "main.py"]
