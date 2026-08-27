import os
import time
import math
import re
import threading
import json
from datetime import datetime, timedelta
from collections import defaultdict

import urllib.request
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "cepresa-secret-key-dev")

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# --- Estado del servidor ---
connected_users = {}
user_locations = {}  # user_id -> {"lat": ..., "lon": ...}
accelerometer_reports = []
alert_cooldown = {}
active_alert = None
ALERT_COOLDOWN_SECONDS = 60
REPORT_WINDOW_SECONDS = 2
MIN_REPORTS_FOR_ALERT = 5
MAX_DISTANCE_KM = 10

# Coordenadas aproximadas de Costa Rica
CR_LAT_MIN, CR_LAT_MAX = 8.0, 11.2
CR_LON_MIN, CR_LON_MAX = -86.0, -82.5

# Países y sus rangos de coordenadas (para detectar sismos)
COUNTRY_RANGES = [
    ("Costa Rica", 8.0, 11.2, -86.0, -82.5),
    ("México", 14.0, 33.0, -118.0, -86.0),
    ("Japón", 24.0, 46.0, 122.0, 146.0),
    ("Chile", -56.0, -17.0, -76.0, -66.0),
    ("Colombia", -4.0, 13.0, -79.0, -66.0),
    ("Perú", -18.0, 0.0, -82.0, -68.0),
    ("Ecuador", -5.0, 2.0, -81.0, -75.0),
    ("Argentina", -55.0, -21.0, -74.0, -53.0),
    ("Estados Unidos", 24.0, 49.0, -125.0, -66.0),
    ("Canadá", 41.0, 84.0, -141.0, -52.0),
    ("Brasil", -34.0, 5.0, -74.0, -34.0),
    ("Guatemala", 13.0, 18.0, -92.0, -88.0),
    ("Honduras", 13.0, 16.5, -89.0, -83.0),
    ("El Salvador", 13.0, 14.5, -90.0, -87.0),
    ("Nicaragua", 10.0, 15.0, -88.0, -82.0),
    ("Panamá", 7.0, 9.6, -83.0, -77.0),
    ("China", 18.0, 54.0, 73.0, 135.0),
    ("India", 6.0, 37.0, 68.0, 97.0),
    ("Turquía", 36.0, 42.0, 26.0, 45.0),
    ("Italia", 36.0, 47.0, 6.0, 19.0),
    ("Filipinas", 4.0, 21.0, 116.0, 127.0),
    ("Indonesia", -11.0, 6.0, 95.0, 141.0),
    ("Nueva Zelanda", -47.0, -34.0, 165.0, 179.0),
    ("Islandia", 63.0, 67.0, -25.0, -13.0),
    ("Grecia", 34.0, 42.0, 19.0, 30.0),
    ("Rusia", 41.0, 82.0, 27.0, 180.0),
]


def detect_country(lat, lon):
    for name, lat_min, lat_max, lon_min, lon_max in COUNTRY_RANGES:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return name
    return "Desconocido"


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def is_in_costa_rica(lat, lon):
    return CR_LAT_MIN <= lat <= CR_LAT_MAX and CR_LON_MIN <= lon <= CR_LON_MAX


def check_seismic_trigger(lat, lon):
    now = time.time()
    accelerometer_reports.append({"lat": lat, "lon": lon, "timestamp": now})
    accelerometer_reports[:] = [
        r for r in accelerometer_reports if now - r["timestamp"] <= REPORT_WINDOW_SECONDS * 3
    ]
    recent = [r for r in accelerometer_reports if now - r["timestamp"] <= REPORT_WINDOW_SECONDS]
    cluster_count = sum(1 for r in recent if haversine_km(lat, lon, r["lat"], r["lon"]) <= MAX_DISTANCE_KM)
    if cluster_count >= MIN_REPORTS_FOR_ALERT:
        if now - alert_cooldown.get("last", 0) > ALERT_COOLDOWN_SECONDS:
            alert_cooldown["last"] = now
            accelerometer_reports.clear()
            return True
    return False


MIN_USERS_FOR_ALERT = 1


def trigger_alert(params):
    global active_alert

    if len(connected_users) < MIN_USERS_FOR_ALERT:
        print(f"[BLOCKED] Alerta bloqueada: solo {len(connected_users)}/{MIN_USERS_FOR_ALERT} usuarios conectados")
        return False

    now = datetime.utcnow()
    alert_data = {
        "tipo": "alerta_sismica",
        "latitud": params["latitud"],
        "longitud": params["longitud"],
        "magnitud": params["magnitud"],
        "profundidad": params["profundidad"],
        "segundos": params["segundos"],
        "sonido": params["sonido"],
        "simulacro": params.get("simulacro", False),
        "timestamp": now.isoformat(),
        "mensaje": (
            f"SIMULACRO - Sismo de magnitud {params['magnitud']} detectado"
            if params.get("simulacro")
            else f"Sismo de magnitud {params['magnitud']} detectado por la red CEPRESA"
        ),
    }
    active_alert = alert_data
    socketio.emit("alerta_sismica", alert_data)
    print(f"[!!!] ALERTA SISICA - M{params['magnitud']} en ({params['latitud']}, {params['longitud']}) - {len(connected_users)} usuarios")

    def auto_clear():
        time.sleep(60)
        global active_alert
        active_alert = None
        socketio.emit("alerta_clear", {})
    threading.Thread(target=auto_clear, daemon=True).start()
    return True


# --- Worker: sismos reales del mundo (USGS) ---
def usgs_worker():
    """Poll USGS earthquake feed cada 30 segundos y emite puntos rojos parpadeantes."""
    seen_ids = set()
    url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_hour.geojson"

    while True:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CEPRESA/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())

            for feature in data.get("features", []):
                eq_id = feature["id"]
                if eq_id in seen_ids:
                    continue
                seen_ids.add(eq_id)

                props = feature["properties"]
                coords = feature["geometry"]["coordinates"]
                mag = props.get("mag", 0)
                place = props.get("place", "")
                eq_time = props.get("time", 0)

                lon_eq, lat_eq, depth_eq = coords[0], coords[1], coords[2]
                country = detect_country(lat_eq, lon_eq)

                socketio.emit("earthquake_global", {
                    "latitud": lat_eq,
                    "longitud": lon_eq,
                    "magnitud": round(mag, 1),
                    "profundidad": round(depth_eq, 1),
                    "pais": country,
                    "lugar": place,
                    "timestamp": eq_time,
                })

            # Limpiar IDs viejos (mantener solo ultimas 200)
            if len(seen_ids) > 200:
                seen_ids = set(list(seen_ids)[-100:])

        except Exception as e:
            print(f"[USGS] Error: {e}")

        time.sleep(30)


# --- Rutas HTTP ---
@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/status")
def api_status():
    return jsonify({
        "personas_en_linea": len(connected_users),
        "alerta_activa": active_alert is not None,
        "timestamp": datetime.utcnow().isoformat(),
    })


@app.route("/api/test", methods=["POST"])
def api_test():
    data = request.get_json(silent=True) or {}
    params = {
        "magnitud": float(data.get("magnitud", 5.0)),
        "profundidad": float(data.get("profundidad", 10.0)),
        "latitud": float(data.get("latitud", 9.75)),
        "longitud": float(data.get("longitud", -83.75)),
        "sonido": bool(data.get("sonido", True)),
        "segundos": max(5, int(float(data.get("profundidad", 10.0)) * 0.8 + float(data.get("magnitud", 5.0)) * 2)),
        "simulacro": True,
    }
    sent = trigger_alert(params)
    if not sent:
        return jsonify({"status": "blocked", "reason": f"Se necesitan al menos {MIN_USERS_FOR_ALERT} usuarios. Actuales: {len(connected_users)}"}), 400
    return jsonify({"status": "alert sent", "params": params})


@app.route("/api/users")
def api_users():
    locations = []
    for uid, loc in user_locations.items():
        if loc.get("lat") is not None and loc.get("lon") is not None:
            locations.append({"lat": loc["lat"], "lon": loc["lon"]})
    return jsonify({"count": len(connected_users), "locations": locations})


# --- WebSocket events ---
@socketio.on("connect")
def handle_connect():
    user_id = f"user_{int(time.time() * 1000) % 100000}"
    connected_users[user_id] = {"connected_at": time.time(), "last_report": None}
    user_locations[user_id] = {"lat": None, "lon": None}
    emit("user_registered", {"user_id": user_id})
    socketio.emit("update_users", {"count": len(connected_users)})
    print(f"[+] User connected: {user_id} (Total: {len(connected_users)})")


@socketio.on("disconnect")
def handle_disconnect():
    sid = request.sid
    removed = None
    for uid in list(connected_users.keys()):
        if connected_users[uid].get("sid") == sid:
            removed = uid
            break
    if not removed:
        keys = list(connected_users.keys())
        if keys:
            removed = keys[-1]
    if removed:
        connected_users.pop(removed, None)
        user_locations.pop(removed, None)
        socketio.emit("update_users", {"count": len(connected_users)})
        _broadcast_user_locations()
        print(f"[-] User disconnected: {removed} (Total: {len(connected_users)})")


@socketio.on("acelerometro_reporte")
def handle_accelerometer(data):
    user_id = data.get("user_id", "unknown")
    lat = data.get("latitud")
    lon = data.get("longitud")
    timestamp = data.get("timestamp", datetime.utcnow().isoformat())

    if lat is None or lon is None:
        return

    if user_id in connected_users:
        connected_users[user_id]["last_report"] = time.time()

    # Actualizar ubicacion del usuario
    if user_id in user_locations:
        user_locations[user_id]["lat"] = lat
        user_locations[user_id]["lon"] = lon
        _broadcast_user_locations()

    socketio.emit("sensor_event", {
        "user_id": user_id,
        "latitud": lat,
        "longitud": lon,
        "timestamp": timestamp,
    })

    if check_seismic_trigger(lat, lon):
        trigger_alert({
            "latitud": lat, "longitud": lon,
            "magnitud": 5.0, "profundidad": 10.0,
            "segundos": 30, "sonido": True, "simulacro": False,
        })


@socketio.on("estoy_a_salvo")
def handle_estoy_a_salvo(data):
    user_id = data.get("user_id", "unknown")
    print(f"[SAFE] {user_id} reporto estar a salvo")


@socketio.on("reportar_ubicacion")
def handle_location(data):
    user_id = data.get("user_id", "unknown")
    lat = data.get("latitud")
    lon = data.get("longitud")
    if user_id in connected_users and lat is not None and lon is not None:
        user_locations[user_id] = {"lat": lat, "lon": lon}
        _broadcast_user_locations()


def _broadcast_user_locations():
    locations = []
    for uid, loc in user_locations.items():
        if loc.get("lat") is not None and loc.get("lon") is not None:
            locations.append({"lat": loc["lat"], "lon": loc["lon"]})
    socketio.emit("user_locations", {"locations": locations})


@app.route("/api/simulate_earthquake", methods=["POST"])
def simulate_earthquake():
    sent = trigger_alert({
        "latitud": 9.9281, "longitud": -84.0907,
        "magnitud": 6.2, "profundidad": 20.0,
        "segundos": 36, "sonido": True, "simulacro": True,
    })
    if not sent:
        return jsonify({"status": "blocked", "reason": f"Se necesitan al menos {MIN_USERS_FOR_ALERT} usuarios"}), 400
    return jsonify({"status": "simulated alert sent"})

if __name__ == "__main__":
    import sys
    import json
    import urllib.request

    # --- MODO CLI: Enviar el simulacro al servidor en vivo ---
    if len(sys.argv) > 1 and sys.argv[1] == "simular":
        # Capturar parámetros o usar los de Cartago por defecto
        mag = float(sys.argv[2]) if len(sys.argv) > 2 else 5.2
        prof = float(sys.argv[3]) if len(sys.argv) > 3 else 35.0
        lat = float(sys.argv[4]) if len(sys.argv) > 4 else 9.8644
        lon = float(sys.argv[5]) if len(sys.argv) > 5 else -83.9194
        sonido = sys.argv[6].lower() == "true" if len(sys.argv) > 6 else False
        
        puerto = os.environ.get("PORT", "5000")
        url = f"http://127.0.0.1:{puerto}/api/test"
        
        datos = json.dumps({
            "magnitud": mag,
            "profundidad": prof,
            "latitud": lat,
            "longitud": lon,
            "sonido": sonido
        }).encode("utf-8")
        
        req = urllib.request.Request(url, data=datos, headers={"Content-Type": "application/json"})
        
        print(f"[CLI] Enviando simulacro M{mag} a {url}...")
        try:
            with urllib.request.urlopen(req) as response:
                print("✅ Éxito:", response.read().decode())
        except urllib.error.HTTPError as e:
            print("⚠️ Alerta bloqueada por el servidor:", e.read().decode())
        except Exception as e:
            print("❌ Error de conexión (¿Está el servidor encendido?):", e)
            
        sys.exit(0)

    # --- MODO SERVIDOR: Iniciar la aplicación web normal ---
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"

    # Iniciar worker de sismos USGS
    threading.Thread(target=usgs_worker, daemon=True).start()

    socketio.run(app, host="0.0.0.0", port=port, debug=debug)
    
