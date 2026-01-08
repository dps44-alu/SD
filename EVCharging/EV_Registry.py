from flask import Flask, request, jsonify
import json
import secrets
import threading
import os


app = Flask(__name__)


REGISTRY_DB = "db.json" 
DB_LOCK = threading.Lock()


def load_registry():
    with DB_LOCK:
        try:
            with open(REGISTRY_DB, "r") as f:
                data = json.load(f)
                # Adaptar estructura de db.json
                return {
                    "registered_cps": [
                        {
                            "id": cp["id"],
                            "address": cp["address"],
                            "price": cp["price"],
                            "username": f"cp_{cp['id']}",
                            "password": "placeholder"  # Se generará en registro
                        }
                        for cp in data.get("charging_points", [])
                    ]
                }
        except FileNotFoundError:
            return {"registered_cps": []}
        

def save_registry(registry_data):
    with DB_LOCK:
        try:
            # Leer db.json actual
            with open(REGISTRY_DB, "r") as f:
                db = json.load(f)
        except FileNotFoundError:
            db = {"charging_points": [], "drivers": []}
        
        # Actualizar charging_points con datos del registry
        db["charging_points"] = [
            {
                "id": cp["id"],
                "address": cp["address"],
                "price": cp["price"],
                "status": "INACTIVE",  # Estado inicial
                "driver": "",
                "kwh_consumed": 0,
                "money_consumed": 0
            }
            for cp in registry_data["registered_cps"]
        ]
        
        # Guardar
        with open(REGISTRY_DB, "w") as f:
            json.dump(db, f, indent=4)
            

# POST /register - Registrar un nuevo CP
@app.route('/register', methods=['POST'])
def register_cp():
    data = request.json
    cp_id = data.get("id")
    address = data.get("address")
    price = data.get("price")
    
    if not cp_id or not address or price is None:
        return jsonify({"status": "ERROR", "message": "Faltan datos"}), 400
    
    registry = load_registry()
    
    # Verificar si ya existe
    for cp in registry["registered_cps"]:
        if cp["id"] == cp_id:
            return jsonify({"status": "ERROR", "message": "CP ya registrado"}), 409
    
    # Generar credenciales (username y password)
    username = f"cp_{cp_id}"
    password = secrets.token_urlsafe(16)
    
    # AÃ±adir al registro
    registry["registered_cps"].append({
        "id": cp_id,
        "address": address,
        "price": price,
        "username": username,
        "password": password
    })
    save_registry(registry)
    
    print(f"[Registry] CP {cp_id} registrado exitosamente")
    
    return jsonify({
        "status": "SUCCESS",
        "username": username,
        "password": password
    }), 201


# DELETE /register/<cp_id> - Dar de baja un CP
@app.route('/register/<cp_id>', methods=['DELETE'])
def unregister_cp(cp_id):
    registry = load_registry()
    
    # Buscar y eliminar
    found = False
    for i, cp in enumerate(registry["registered_cps"]):
        if cp["id"] == cp_id:
            registry["registered_cps"].pop(i)
            found = True
            break
    
    if not found:
        return jsonify({"status": "ERROR", "message": "CP no encontrado"}), 404
    
    save_registry(registry)
    print(f"[Registry] CP {cp_id} dado de baja")
    
    return jsonify({"status": "SUCCESS"}), 200


# GET /register/<cp_id> - Consultar si un CP estÃ¡ registrado
@app.route('/register/<cp_id>', methods=['GET'])
def check_cp(cp_id):
    registry = load_registry()
    
    for cp in registry["registered_cps"]:
        if cp["id"] == cp_id:
            return jsonify({
                "status": "REGISTERED",
                "id": cp["id"],
                "address": cp["address"],
                "price": cp["price"]
            }), 200
    
    return jsonify({"status": "NOT_FOUND"}), 404


# Usar HTTPS simple con certificado autofirmado
# Generar certificado: openssl req -x509 -newkey rsa:4096 -nodes -out cert.pem -keyout key.pem -days 365
if __name__ == "__main__":
    if not os.path.exists("cert.pem") or not os.path.exists("key.pem"):
        print("[Registry] ADVERTENCIA: Ejecutar para generar certificados SSL:")
        print("openssl req -x509 -newkey rsa:4096 -nodes -out cert.pem -keyout key.pem -days 365")
        print("[Registry] Iniciando sin SSL (solo para desarrollo)")
        app.run(host='0.0.0.0', port=5001, debug=False)
    else:
        print("[Registry] Iniciando con SSL en puerto 5001")
        app.run(host='0.0.0.0', port=5001, ssl_context=('cert.pem', 'key.pem'), debug=False)