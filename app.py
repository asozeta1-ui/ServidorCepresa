import os
import time
import math
import re
from datetime import datetime
from collections import defaultdict

from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "cepresa-secret-key-dev")

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# --- Estado del servidor ---
connected_users = {}
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


def parse_test_command(text):
    """
    Formato: /test /m<magnitud> /p<profundidad> /d<lat,lon> /s(on/off)
    Ejemplo: /test /m6.5 /p15 /d9.75,-83.75 /s on
    """
    text = text.strip()
    if not text.lower().startswith("/test"):
        return None

    mag_match = re.search(r'/m([\d.]+)', text, re.IGNORECASE)
    prof_match = re.search(r'/p([\d.]+)', text, re.IGNORECASE)
    coord_match = re.search(r'/d([-\d.]+),([-\d.]+)', text, re.IGNORECASE)
    sound_match = re.search(r'/s(on|off)', text, re.IGNORECASE)

    magnitud = float(mag_match.group(1)) if mag_match else 5.0
    profundidad = float(prof_match.group(1)) if prof_match else 10.0
    latitud = float(coord_match.group(1)) if coord_match else 9.75
    longitud = float(coord_match.group(2)) if coord_match else -83.75
    sonido = sound_match.group(1).lower() == "on" if sound_match else True

    # Segundos estimados de llegada (fórmula simplificada)
    segundos = max(5, int(profundidad * 0.8 + magnitud * 2))

    return {
        "magnitud": magnitud,
        "profundidad": profundidad,
        "latitud": latitud,
        "longitud": longitud,
        "sonido": sonido,
        "segundos": segundos,
        "simulacro": True,
    }


def trigger_alert(params):
    global active_alert
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

    print("=" * 50)
    print("  ALERTA SISMICA EMITIDA")
    print("=" * 50)
    print(f"  Magnitud:    {params['magnitud']}")
    print(f"  Profundidad: {params['profundidad']} km")
    print(f"  Coordenadas: {params['latitud']}, {params['longitud']}")
    print(f"  Segundos:    {params['segundos']}")
    print(f"  Sonido:      {'ON' if params['sonido'] else 'OFF'}")
    print(f"  SIMULACRO:   {'SI' if params.get('simulacro') else 'NO'}")
    print("=" * 50)

    # Auto-clear despues de 60 segundos
    def auto_clear():
        time.sleep(60)
        global active_alert
        active_alert = None
        socketio.emit("alerta_clear", {})
        print("[ALERT] Alerta auto-desactivada despues de 60s")

    import threading
    threading.Thread(target=auto_clear, daemon=True).start()


# --- Rutas HTTP ---
@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/status")
def api_status():
    return jsonify(
        {
            "personas_en_linea": len(connected_users),
            "alerta_activa": active_alert is not None,
            "timestamp": datetime.utcnow().isoformat(),
        }
    )


@app.route("/api/test", methods=["POST"])
def api_test():
    """
    Endpoint HTTP para lanzar una alerta de prueba.
    POST /api/test
    Body JSON: {"magnitud": 6.5, "profundidad": 15, "latitud": 9.75, "longitud": -83.75, "sonido": true}
    """
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
    trigger_alert(params)
    return jsonify({"status": "alert sent", "params": params})


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

    socketio.emit(
        "sensor_event",
        {
            "user_id": user_id,
            "latitud": lat,
            "longitud": lon,
            "timestamp": timestamp,
        },
    )

    if check_seismic_trigger(lat, lon):
        trigger_alert({
            "latitud": lat,
            "longitud": lon,
            "magnitud": 5.0,
            "profundidad": 10.0,
            "segundos": 30,
            "sonido": True,
            "simulacro": False,
        })


@socketio.on("estoy_a_salvo")
def handle_estoy_a_salvo(data):
    user_id = data.get("user_id", "unknown")
    timestamp = data.get("timestamp", datetime.utcnow().isoformat())
    print(f"[SAFE] {user_id} reporto estar a salvo ({timestamp})")


@socketio.on("reportar_ubicacion")
def handle_location(data):
    user_id = data.get("user_id", "unknown")
    if user_id in connected_users:
        connected_users[user_id]["lat"] = data.get("latitud")
        connected_users[user_id]["lon"] = data.get("longitud")


# --- Simulacion de sismos (para testing via HTTP) ---
@app.route("/api/simulate_earthquake", methods=["POST"])
def simulate_earthquake():
    trigger_alert({
        "latitud": 9.9281,
        "longitud": -84.0907,
        "magnitud": 6.2,
        "profundidad": 20.0,
        "segundos": 36,
        "sonido": True,
        "simulacro": True,
    })
    return jsonify({"status": "simulated alert sent"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    socketio.run(app, host="0.0.0.0", port=port, debug=debug)
