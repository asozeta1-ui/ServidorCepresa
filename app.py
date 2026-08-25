import os
import time
import math
from datetime import datetime
from collections import defaultdict

from flask import Flask, render_template, jsonify
from flask_socketio import SocketIO, emit

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "cepresa-secret-key-dev")

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# --- Estado del servidor ---
connected_users = {}
accelerometer_reports = []
alert_cooldown = {}
ALERT_COOLDOWN_SECONDS = 60
REPORT_WINDOW_SECONDS = 2
MIN_REPORTS_FOR_ALERT = 5
MAX_DISTANCE_KM = 10

# Coordenadas aproximadas de Costa Rica
CR_LAT_MIN, CR_LAT_MAX = 8.0, 11.2
CR_LON_MIN, CR_LON_MAX = -86.0, -82.5


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
    accelerometer_reports.append(
        {"lat": lat, "lon": lon, "timestamp": now}
    )

    accelerometer_reports[:] = [
        r for r in accelerometer_reports if now - r["timestamp"] <= REPORT_WINDOW_SECONDS * 3
    ]

    recent = [r for r in accelerometer_reports if now - r["timestamp"] <= REPORT_WINDOW_SECONDS]

    cluster_count = 0
    for r in recent:
        if haversine_km(lat, lon, r["lat"], r["lon"]) <= MAX_DISTANCE_KM:
            cluster_count += 1

    if cluster_count >= MIN_REPORTS_FOR_ALERT:
        user_id = connected_users.get("current_user", "unknown")
        if now - alert_cooldown.get("last", 0) > ALERT_COOLDOWN_SECONDS:
            alert_cooldown["last"] = now
            accelerometer_reports.clear()
            return True
    return False


# --- Rutas HTTP ---
@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/status")
def api_status():
    return jsonify(
        {
            "personas_en_linea": len(connected_users),
            "alertas_activas": sum(1 for v in alert_cooldown.values() if isinstance(v, bool)),
            "timestamp": datetime.utcnow().isoformat(),
        }
    )


# --- WebSocket events ---
@socketio.on("connect")
def handle_connect():
    user_id = f"user_{int(time.time() * 1000) % 100000}"
    connected_users[user_id] = {
        "connected_at": time.time(),
        "last_report": None,
    }
    emit("user_registered", {"user_id": user_id})
    socketio.emit("update_users", {"count": len(connected_users)})
    print(f"[+] User connected: {user_id} (Total: {len(connected_users)})")


@socketio.on("disconnect")
def handle_disconnect():
    keys = list(connected_users.keys())
    if keys:
        removed = keys[-1]
        del connected_users[removed]
        socketio.emit("update_users", {"count": len(connected_users)})
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

    # Retransmitir al dashboard para visualización en tiempo real
    socketio.emit(
        "sensor_event",
        {
            "user_id": user_id,
            "latitud": lat,
            "longitud": lon,
            "timestamp": timestamp,
        },
    )

    # Verificar si se debe disparar alerta
    if check_seismic_trigger(lat, lon):
        alert_payload = {
            "tipo": "alerta_sismica",
            "latitud": lat,
            "longitud": lon,
            "timestamp": datetime.utcnow().isoformat(),
            "mensaje": "ALERTA SISMO detectado por la red CEPRESA. Protéjase ahora.",
        }
        socketio.emit("alerta_sismica", alert_payload)
        print(f"[!!!] SISMIC ALERT TRIGGERED at ({lat}, {lon})")


@socketio.on("reportar_ubicacion")
def handle_location(data):
    user_id = data.get("user_id", "unknown")
    if user_id in connected_users:
        connected_users[user_id]["lat"] = data.get("latitud")
        connected_users[user_id]["lon"] = data.get("longitud")


# --- Simulación de sismos (para testing) ---
@app.route("/api/simulate_earthquake", methods=["POST"])
def simulate_earthquake():
    fake_data = {
        "tipo": "alerta_sismica",
        "latitud": 9.9281,
        "longitud": -84.0907,
        "timestamp": datetime.utcnow().isoformat(),
        "mensaje": "ALERTA SISMO detectado por la red CEPRESA. Protéjase ahora.",
        "simulado": True,
    }
    socketio.emit("alerta_sismica", fake_data)
    return jsonify({"status": "simulated alert sent"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    socketio.run(app, host="0.0.0.0", port=port, debug=debug)
