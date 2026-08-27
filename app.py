import os
import time
import math
import re
import hmac
import hashlib
import threading
import json
import secrets
from datetime import datetime, timedelta
from collections import defaultdict
from functools import wraps

import urllib.request
from flask import Flask, render_template, jsonify, request
from flask_socketio import SocketIO, emit

# ─── Seguridad: Configuración ──────────────────────────────────────────
SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
API_KEY = os.environ.get("CEPRESA_API_KEY", secrets.token_hex(24))
HMAC_SECRET = os.environ.get("CEPRESA_HMAC_SECRET", secrets.token_hex(32))
CARTO_API_KEY = os.environ.get("CARTO_API_KEY", "cb1_29g6_1_201a8281a4099feebd035b61")

# ─── Rate Limiting ──────────────────────────────────────────────────────
RATE_LIMIT_WINDOW = 60  # segundos
RATE_LIMIT_MAX_REQUESTS = 30  # requests por ventana por IP
RATE_LIMIT_MAX_SENSORS = 10  # reportes de sensor por ventana por IP
RATE_LIMIT_MAX_ALERTS = 2  # alertas por ventana por IP global

# ─── Cooldowns ──────────────────────────────────────────────────────────
SENSOR_COOLDOWN_MS = 1000  # mínimo 1 segundo entre reportes del mismo sensor
IP_BAN_DURATION = 3600  # 1 hora de ban por comportamiento malicioso

# ─── Geofencing ─────────────────────────────────────────────────────────
# Solo reportar sismos dentro de estas coordenadas amplias (todo Centroamérica + más)
REPORT_LAT_MIN, REPORT_LAT_MAX = -60.0, 85.0
REPORT_LON_MIN, REPORT_LON_MAX = -180.0, 180.0

# Velocidad máxima física para cambio de ubicación (km/h) - avión comercial
MAX_LOCATION_SPEED_KMH = 1200

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = SECRET_KEY

socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# ═══════════════════════════════════════════════════════════════════════
# SISTEMA DE SEGURIDAD
# ═══════════════════════════════════════════════════════════════════════

class SecurityManager:
    """Centraliza toda la lógica de seguridad del servidor."""

    def __init__(self):
        self.ip_requests = defaultdict(list)  # ip -> [timestamps]
        self.ip_sensor_reports = defaultdict(list)  # ip -> [timestamps]
        self.ip_alert_triggers = []  # [(timestamp, ip)]
        self.banned_ips = {}  # ip -> ban_expiry_timestamp
        self.suspicious_ips = defaultdict(int)  # ip -> suspicion_score
        self.user_locations = {}  # user_id -> {"lat", "lon", "timestamp"}
        self.user_last_sensor = {}  # user_id -> timestamp
        self._lock = threading.Lock()

    # ── Rate Limiting ───────────────────────────────────────────────────

    def is_rate_limited(self, ip, limit_type="general"):
        """Verifica si una IP ha excedido el rate limit."""
        now = time.time()
        with self._lock:
            # Verificar si la IP está baneada
            if ip in self.banned_ips:
                if now < self.banned_ips[ip]:
                    return True
                else:
                    del self.banned_ips[ip]
                    self.suspicious_ips[ip] = max(0, self.suspicious_ips[ip] - 1)

            if limit_type == "sensor":
                self.ip_sensor_reports[ip] = [
                    t for t in self.ip_sensor_reports[ip]
                    if now - t < RATE_LIMIT_WINDOW
                ]
                if len(self.ip_sensor_reports[ip]) >= RATE_LIMIT_MAX_SENSORS:
                    self._mark_suspicious(ip, "rate_limit_sensor")
                    return True
                self.ip_sensor_reports[ip].append(now)

            elif limit_type == "alert":
                self.ip_alert_triggers = [
                    (t, i) for t, i in self.ip_alert_triggers
                    if now - t < RATE_LIMIT_WINDOW
                ]
                alert_count = sum(1 for _, i in self.ip_alert_triggers if i == ip)
                if alert_count >= RATE_LIMIT_MAX_ALERTS:
                    self._mark_suspicious(ip, "rate_limit_alert")
                    return True
                self.ip_alert_triggers.append((now, ip))

            else:  # general
                self.ip_requests[ip] = [
                    t for t in self.ip_requests[ip]
                    if now - t < RATE_LIMIT_WINDOW
                ]
                if len(self.ip_requests[ip]) >= RATE_LIMIT_MAX_REQUESTS:
                    self._mark_suspicious(ip, "rate_limit_general")
                    return True
                self.ip_requests[ip].append(now)

            return False

    def _mark_suspicious(self, ip, reason):
        """Marca una IP como sospechosa y la banea si excede el umbral."""
        self.suspicious_ips[ip] += 1
        print(f"[SECURITY] IP {ip} marcada sospechosa: {reason} (score: {self.suspicious_ips[ip]})")

        if self.suspicious_ips[ip] >= 5:
            self.ban_ip(ip, f"Acumuló {self.suspicious_ips[ip]} violaciones")

    def ban_ip(self, ip, reason=""):
        """Banea una IP temporalmente."""
        self.banned_ips[ip] = time.time() + IP_BAN_DURATION
        print(f"[SECURITY] IP BANEADA: {ip} por {IP_BAN_DURATION}s - {reason}")

    def is_ip_allowed(self, ip):
        """Verifica si una IP tiene permitido acceder."""
        if ip in self.banned_ips:
            if time.time() < self.banned_ips[ip]:
                return False
            del self.banned_ips[ip]
        return True

    # ── API Key Verification ────────────────────────────────────────────

    def verify_api_key(self, provided_key):
        """Verifica que la API key proporcionada sea válida."""
        if not provided_key:
            return False
        return hmac.compare_digest(provided_key, API_KEY)

    # ── HMAC Verification ───────────────────────────────────────────────

    def generate_hmac(self, data_str):
        """Genera un HMAC para una cadena de datos."""
        return hmac.new(
            HMAC_SECRET.encode(), data_str.encode(), hashlib.sha256
        ).hexdigest()

    def verify_hmac(self, data_str, provided_hmac):
        """Verifica que el HMAC proporcionado coincida con los datos."""
        if not provided_hmac:
            return False
        expected = self.generate_hmac(data_str)
        return hmac.compare_digest(expected, provided_hmac)

    # ── Input Validation ────────────────────────────────────────────────

    def validate_coordinates(self, lat, lon):
        """Valida que las coordenadas sean numéricas y estén en rangos razonables."""
        if lat is None or lon is None:
            return False
        try:
            lat = float(lat)
            lon = float(lon)
        except (TypeError, ValueError):
            return False
        if not (-90 <= lat <= 90):
            return False
        if not (-180 <= lon <= 180):
            return False
        return True

    def validate_magnitude(self, mag):
        """Valida que la magnitud esté en un rango razonable."""
        if mag is None:
            return False
        try:
            mag = float(mag)
        except (TypeError, ValueError):
            return False
        return 0.1 <= mag <= 10.0

    def validate_depth(self, depth):
        """Valida que la profundidad esté en un rango razonable."""
        if depth is None:
            return False
        try:
            depth = float(depth)
        except (TypeError, ValueError):
            return False
        return 0 <= depth <= 700  # km, máximo teórico

    def validate_user_id(self, user_id):
        """Valida que el user_id tenga un formato válido."""
        if not user_id or not isinstance(user_id, str):
            return False
        # Formato esperado: android_XXXXXXXX
        if re.match(r'^android_[a-f0-9]{8}$', user_id):
            return True
        # También aceptar user_XXXXXXXX (generado por el servidor)
        if re.match(r'^user_\d+$', user_id):
            return True
        return False

    def validate_sensor_data(self, data):
        """Valida todos los campos de un reporte del acelerómetro."""
        if not isinstance(data, dict):
            return False

        user_id = data.get("user_id")
        lat = data.get("latitud")
        lon = data.get("longitud")

        if not self.validate_user_id(user_id):
            return False
        if not self.validate_coordinates(lat, lon):
            return False

        # Verificar que las coordenadas estén en un rango geográfico razonable
        lat_f, lon_f = float(lat), float(lon)
        if not (REPORT_LAT_MIN <= lat_f <= REPORT_LAT_MAX):
            return False
        if not (REPORT_LON_MIN <= lon_f <= REPORT_LON_MAX):
            return False

        return True

    def validate_location_data(self, data):
        """Valida los datos de ubicación."""
        if not isinstance(data, dict):
            return False

        user_id = data.get("user_id")
        lat = data.get("latitud")
        lon = data.get("longitud")

        if not self.validate_user_id(user_id):
            return False
        if not self.validate_coordinates(lat, lon):
            return False

        return True

    # ── Geographic Validation ───────────────────────────────────────────

    def check_location_plausibility(self, user_id, new_lat, new_lon):
        """
        Verifica si el cambio de ubicación es físicamente posible.
        Detecta si un usuario se mueve demasiado rápido (spoofing).
        """
        now = time.time()

        if user_id in self.user_locations:
            prev = self.user_locations[user_id]
            if prev.get("lat") is not None and prev.get("timestamp") is not None:
                elapsed = now - prev["timestamp"]
                if elapsed > 0:
                    distance_km = haversine_km(
                        prev["lat"], prev["lon"], new_lat, new_lon
                    )
                    speed_kmh = distance_km / (elapsed / 3600)
                    if speed_kmh > MAX_LOCATION_SPEED_KMH:
                        return False

        self.user_locations[user_id] = {
            "lat": new_lat,
            "lon": new_lon,
            "timestamp": now
        }
        return True

    # ── Sensor Cooldown ─────────────────────────────────────────────────

    def check_sensor_cooldown(self, user_id):
        """Verifica si el sensor respetó el cooldown mínimo."""
        now = time.time() * 1000  # en ms
        if user_id in self.user_last_sensor:
            if now - self.user_last_sensor[user_id] < SENSOR_COOLDOWN_MS:
                return False
        self.user_last_sensor[user_id] = now
        return True

    # ── Anomaly Detection ───────────────────────────────────────────────

    def detect_anomaly(self, user_id, lat, lon):
        """
        Detecta patrones anómalos que podrían indicar falsos reportes.
        Retorna True si se detecta una anomalía.
        """
        # 1. Verificar si múltiples user_ids reportan desde la misma ubicación exacta
        #    en un período corto (ataque coordinado)
        now = time.time()
        same_location_count = 0
        for uid, loc in self.user_locations.items():
            if uid == user_id:
                continue
            if (loc.get("lat") is not None and
                    abs(loc["lat"] - lat) < 0.0001 and
                    abs(loc["lon"] - lon) < 0.0001 and
                    now - loc.get("timestamp", 0) < 30):
                same_location_count += 1

        if same_location_count >= 3:
            print(f"[ANOMALY] {same_location_count} usuarios reportando desde ubicación idéntica cerca de ({lat}, {lon})")
            return True

        # 2. Verificar si un usuario reporta ubicaciones que saltan mucho
        if user_id in self.user_locations:
            prev = self.user_locations[user_id]
            if prev.get("lat") is not None:
                distance = haversine_km(prev["lat"], prev["lon"], lat, lon)
                elapsed = now - prev.get("timestamp", 0)
                if elapsed < 10 and distance > 50:  # 50km en menos de 10 segundos
                    print(f"[ANOMALY] Usuario {user_id} saltó {distance:.1f}km en {elapsed:.1f}s")
                    return True

        return False

    def get_security_stats(self):
        """Retorna estadísticas de seguridad."""
        return {
            "banned_ips": len(self.banned_ips),
            "suspicious_ips": len(self.suspicious_ips),
            "total_requests": sum(len(r) for r in self.ip_requests.values()),
        }


security = SecurityManager()

# ═══════════════════════════════════════════════════════════════════════
# ESTADO DEL SERVIDOR
# ═══════════════════════════════════════════════════════════════════════

connected_users = {}
user_locations_server = {}  # user_id -> {"lat": ..., "lon": ...}
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


MIN_USERS_FOR_ALERT = 15


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
    print(f"[!!!] ALERTA SISMICA - M{params['magnitud']} en ({params['latitud']}, {params['longitud']}) - {len(connected_users)} usuarios")

    def auto_clear():
        time.sleep(60)
        global active_alert
        active_alert = None
        socketio.emit("alerta_clear", {})
    threading.Thread(target=auto_clear, daemon=True).start()
    return True


# ═══════════════════════════════════════════════════════════════════════
# DECORATORS DE SEGURIDAD
# ═══════════════════════════════════════════════════════════════════════

def require_api_key(f):
    """Decorator que requiere una API key válida."""
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = request.remote_addr or "unknown"

        if not security.is_ip_allowed(ip):
            return jsonify({"error": "IP banned", "reason": "Exceso de peticiones"}), 403

        if security.is_rate_limited(ip, "general"):
            return jsonify({"error": "Rate limit exceeded", "retry_after": RATE_LIMIT_WINDOW}), 429

        api_key = request.headers.get("X-API-Key") or request.args.get("api_key")
        if not security.verify_api_key(api_key):
            print(f"[SECURITY] API key inválida desde {ip}")
            return jsonify({"error": "Unauthorized", "message": "API key required"}), 401

        return f(*args, **kwargs)
    return decorated


def require_hmac(f):
    """Decorator que requiere HMAC válido en el body."""
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = request.remote_addr or "unknown"

        if not security.is_ip_allowed(ip):
            return jsonify({"error": "IP banned"}), 403

        signature = request.headers.get("X-Signature")
        body = request.get_data(as_text=True)
        timestamp = request.headers.get("X-Timestamp")

        if not timestamp or not signature:
            return jsonify({"error": "Missing signature"}), 401

        # Verificar que el timestamp no sea viejo (5 minutos)
        try:
            req_time = float(timestamp)
            if abs(time.time() - req_time) > 300:
                return jsonify({"error": "Request expired"}), 401
        except ValueError:
            return jsonify({"error": "Invalid timestamp"}), 401

        data_to_verify = f"{timestamp}:{body}"
        if not security.verify_hmac(data_to_verify, signature):
            print(f"[SECURITY] HMAC inválido desde {ip}")
            return jsonify({"error": "Invalid signature"}), 401

        return f(*args, **kwargs)
    return decorated


# ═══════════════════════════════════════════════════════════════════════
# RUTAS HTTP
# ═══════════════════════════════════════════════════════════════════════

@app.after_request
def add_security_headers(response):
    """Agrega headers de seguridad a todas las respuestas."""
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    return response


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


@app.route("/api/security")
@require_api_key
def api_security():
    """Endpoint para monitorear el estado de seguridad (requiere API key)."""
    return jsonify({
        "security_stats": security.get_security_stats(),
        "connected_users": len(connected_users),
        "banned_ips": list(security.banned_ips.keys()),
    })


@app.route("/api/test", methods=["POST"])
@require_api_key
def api_test():
    ip = request.remote_addr or "unknown"

    if security.is_rate_limited(ip, "alert"):
        return jsonify({"error": "Rate limit exceeded for alerts"}), 429

    data = request.get_json(silent=True) or {}

    # Validar parámetros estrictamente
    magnitud = data.get("magnitud")
    profundidad = data.get("profundidad")
    latitud = data.get("latitud")
    longitud = data.get("longitud")

    if not security.validate_magnitude(magnitud):
        return jsonify({"error": "Invalid magnitude (0.1-10.0)"}), 400
    if not security.validate_depth(profundidad):
        return jsonify({"error": "Invalid depth (0-700 km)"}), 400
    if not security.validate_coordinates(latitud, longitud):
        return jsonify({"error": "Invalid coordinates"}), 400

    params = {
        "magnitud": float(magnitud),
        "profundidad": float(profundidad),
        "latitud": float(latitud),
        "longitud": float(longitud),
        "sonido": bool(data.get("sonido", True)),
        "segundos": max(5, int(float(profundidad) * 0.8 + float(magnitud) * 2)),
        "simulacro": True,
    }

    print(f"[SECURITY] Test alert desde {ip}: M{params['magnitud']} en ({params['latitud']}, {params['longitud']})")

    sent = trigger_alert(params)
    if not sent:
        return jsonify({"status": "blocked", "reason": f"Se necesitan al menos {MIN_USERS_FOR_ALERT} usuarios. Actuales: {len(connected_users)}"}), 400
    return jsonify({"status": "alert sent", "params": params})


@app.route("/api/users")
def api_users():
    locations = []
    for uid, loc in user_locations_server.items():
        if loc.get("lat") is not None and loc.get("lon") is not None:
            locations.append({"lat": loc["lat"], "lon": loc["lon"]})
    return jsonify({"count": len(connected_users), "locations": locations})


@app.route("/api/simulate_earthquake", methods=["POST"])
@require_api_key
def simulate_earthquake():
    ip = request.remote_addr or "unknown"

    if security.is_rate_limited(ip, "alert"):
        return jsonify({"error": "Rate limit exceeded for alerts"}), 429

    print(f"[SECURITY] Simulacro solicitado desde {ip}")

    sent = trigger_alert({
        "latitud": 9.9281, "longitud": -84.0907,
        "magnitud": 6.2, "profundidad": 20.0,
        "segundos": 36, "sonido": True, "simulacro": True,
    })
    if not sent:
        return jsonify({"status": "blocked", "reason": f"Se necesitan al menos {MIN_USERS_FOR_ALERT} usuarios"}), 400
    return jsonify({"status": "simulated alert sent"})


@app.route("/api/ban_ip", methods=["POST"])
@require_api_key
def ban_ip_endpoint():
    """Endpoint para banear IPs manualmente (requiere API key)."""
    data = request.get_json(silent=True) or {}
    ip_to_ban = data.get("ip")
    reason = data.get("reason", "Banned manually")

    if not ip_to_ban:
        return jsonify({"error": "IP required"}), 400

    # Validar formato de IP
    if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip_to_ban):
        return jsonify({"error": "Invalid IP format"}), 400

    security.ban_ip(ip_to_ban, reason)
    return jsonify({"status": "banned", "ip": ip_to_ban})


# ═══════════════════════════════════════════════════════════════════════
# WEBSOCKET EVENTS (con validación de seguridad)
# ═══════════════════════════════════════════════════════════════════════

@socketio.on("connect")
def handle_connect():
    ip = request.remote_addr or "unknown"

    if not security.is_ip_allowed(ip):
        print(f"[SECURITY] Conexión rechazada: IP {ip} baneada")
        return False  # Rechazar conexión

    if security.is_rate_limited(ip, "general"):
        print(f"[SECURITY] Conexión rechazada: rate limit {ip}")
        return False

    user_id = f"user_{int(time.time() * 1000) % 100000}"
    connected_users[user_id] = {"connected_at": time.time(), "last_report": None, "ip": ip}
    user_locations_server[user_id] = {"lat": None, "lon": None}
    emit("user_registered", {"user_id": user_id})
    socketio.emit("update_users", {"count": len(connected_users)})
    print(f"[+] User connected: {user_id} from {ip} (Total: {len(connected_users)})")


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
        user_locations_server.pop(removed, None)
        security.user_locations.pop(removed, None)
        socketio.emit("update_users", {"count": len(connected_users)})
        _broadcast_user_locations()
        print(f"[-] User disconnected: {removed} (Total: {len(connected_users)})")


@socketio.on("acelerometro_reporte")
def handle_accelerometer(data):
    ip = request.remote_addr or "unknown"

    # Rate limit por IP
    if security.is_rate_limited(ip, "sensor"):
        print(f"[SECURITY] Sensor reporte bloqueado: rate limit {ip}")
        return

    # Validar datos estrictamente
    if not security.validate_sensor_data(data):
        print(f"[SECURITY] Sensor reporte rechazado: datos inválidos desde {ip}")
        return

    user_id = data["user_id"]
    lat = float(data["latitud"])
    lon = float(data["longitud"])
    timestamp = data.get("timestamp", datetime.utcnow().isoformat())

    # Cooldown del sensor
    if not security.check_sensor_cooldown(user_id):
        print(f"[SECURITY] Sensor reporte ignorado: cooldown {user_id}")
        return

    # Verificar que el user_id esté conectado
    if user_id not in connected_users:
        print(f"[SECURITY] Sensor reporte de usuario no conectado: {user_id}")
        return

    # Verificar plausibilidad de ubicación
    if not security.check_location_plausibility(user_id, lat, lon):
        print(f"[SECURITY] Ubicación implausible para {user_id}: movimiento imposible")
        security._mark_suspicious(ip, "location_implausible")
        return

    # Detección de anomalías
    if security.detect_anomaly(user_id, lat, lon):
        print(f"[SECURITY] Anomalía detectada para {user_id}")
        return

    connected_users[user_id]["last_report"] = time.time()

    # Actualizar ubicación del usuario
    if user_id in user_locations_server:
        user_locations_server[user_id]["lat"] = lat
        user_locations_server[user_id]["lon"] = lon
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
    if not security.validate_user_id(user_id):
        return
    print(f"[SAFE] {user_id} reporto estar a salvo")


@socketio.on("reportar_ubicacion")
def handle_location(data):
    ip = request.remote_addr or "unknown"

    if security.is_rate_limited(ip, "sensor"):
        return

    if not security.validate_location_data(data):
        print(f"[SECURITY] Location data inválida desde {ip}")
        return

    user_id = data["user_id"]
    lat = float(data["latitud"])
    lon = float(data["longitud"])

    if user_id not in connected_users:
        return

    if not security.check_location_plausibility(user_id, lat, lon):
        security._mark_suspicious(ip, "location_implausible")
        return

    user_locations_server[user_id] = {"lat": lat, "lon": lon}
    _broadcast_user_locations()


def _broadcast_user_locations():
    locations = []
    for uid, loc in user_locations_server.items():
        if loc.get("lat") is not None and loc.get("lon") is not None:
            locations.append({"lat": loc["lat"], "lon": loc["lon"]})
    socketio.emit("user_locations", {"locations": locations})


# ═══════════════════════════════════════════════════════════════════════
# WORKER: Sismos reales del mundo (USGS)
# ═══════════════════════════════════════════════════════════════════════

def usgs_worker():
    """Poll USGS earthquake feed cada 30 segundos."""
    seen_ids = set()
    url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_hour.geojson"

    while True:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CEPRESA/2.0"})
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

            if len(seen_ids) > 200:
                seen_ids = set(list(seen_ids)[-100:])

        except Exception as e:
            print(f"[USGS] Error: {e}")

        time.sleep(30)


# ═══════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("  CEPRESA - Servidor de Alerta Sísmica v2.0 (Hardened)")
    print("=" * 60)
    print(f"  API Key:        {API_KEY[:8]}...{API_KEY[-4:]}")
    print(f"  HMAC Secret:    {HMAC_SECRET[:8]}...{HMAC_SECRET[-4:]}")
    print(f"  Rate Limit:     {RATE_LIMIT_MAX_REQUESTS} req/min, {RATE_LIMIT_MAX_SENSORS} sensors/min")
    print(f"  IP Ban:         {IP_BAN_DURATION}s por comportamiento sospechoso")
    print("=" * 60)
    print()

    # --- MODO CLI: Enviar el simulacro al servidor en vivo ---
    if len(sys.argv) > 1 and sys.argv[1] == "simular":
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

        req = urllib.request.Request(
            url, data=datos,
            headers={
                "Content-Type": "application/json",
                "X-API-Key": API_KEY,
            }
        )

        print(f"[CLI] Enviando simulacro M{mag} a {url}...")
        try:
            with urllib.request.urlopen(req) as response:
                print("Exito:", response.read().decode())
        except urllib.error.HTTPError as e:
            print("Alerta bloqueada por el servidor:", e.read().decode())
        except Exception as e:
            print("Error de conexion:", e)

        sys.exit(0)

    # --- MODO SERVIDOR ---
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    threading.Thread(target=usgs_worker, daemon=True).start()

    print(f"[SERVER] Servidor CEPRESA corriendo en puerto {port} (debug={debug})")
    socketio.run(app, host="0.0.0.0", port=port, debug=debug)
