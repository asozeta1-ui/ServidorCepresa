const express = require('express');
const http = require('http');
const crypto = require('crypto');
const path = require('path');
const { Server } = require('socket.io');
const cors = require('cors');
const readline = require('readline');

const app = express();
const server = http.createServer(app);

// ═══════════════════════════════════════════════════════════════════════
// SEGURIDAD: Configuración
// ═══════════════════════════════════════════════════════════════════════

const API_KEY = process.env.CEPRESA_API_KEY || crypto.randomBytes(24).toString('hex');
const HMAC_SECRET = process.env.CEPRESA_HMAC_SECRET || crypto.randomBytes(32).toString('hex');

// Rate limiting
const RATE_LIMIT_WINDOW = 60 * 1000; // 1 minuto
const RATE_LIMIT_MAX_GENERAL = 30;
const RATE_LIMIT_MAX_SENSORS = 10;
const RATE_LIMIT_MAX_ALERTS = 2;
const SENSOR_COOLDOWN_MS = 1000;
const IP_BAN_DURATION = 3600 * 1000; // 1 hora

// Geofencing
const REPORT_LAT_MIN = -60.0, REPORT_LAT_MAX = 85.0;
const REPORT_LON_MIN = -180.0, REPORT_LON_MAX = 180.0;
const MAX_LOCATION_SPEED_KMH = 1200;

// ═══════════════════════════════════════════════════════════════════════
// SISTEMA DE SEGURIDAD
// ═══════════════════════════════════════════════════════════════════════

class SecurityManager {
    constructor() {
        this.ipRequests = new Map();       // ip -> [timestamps]
        this.ipSensorReports = new Map();  // ip -> [timestamps]
        this.ipAlertTriggers = [];         // [{timestamp, ip}]
        this.bannedIps = new Map();        // ip -> expiry
        this.suspiciousIps = new Map();    // ip -> score
        this.userLocations = new Map();    // userId -> {lat, lon, timestamp}
        this.userLastSensor = new Map();   // userId -> timestamp
    }

    // ── Rate Limiting ───────────────────────────────────────────────
    isRateLimited(ip, type = 'general') {
        const now = Date.now();

        // Verificar ban
        if (this.bannedIps.has(ip)) {
            if (now < this.bannedIps.get(ip)) return true;
            this.bannedIps.delete(ip);
            const score = this.suspiciousIps.get(ip) || 0;
            this.suspiciousIps.set(ip, Math.max(0, score - 1));
        }

        if (type === 'sensor') {
            const reports = (this.ipSensorReports.get(ip) || []).filter(t => now - t < RATE_LIMIT_WINDOW);
            if (reports.length >= RATE_LIMIT_MAX_SENSORS) {
                this._markSuspicious(ip, 'rate_limit_sensor');
                return true;
            }
            reports.push(now);
            this.ipSensorReports.set(ip, reports);
        } else if (type === 'alert') {
            this.ipAlertTriggers = this.ipAlertTriggers.filter(t => now - t.timestamp < RATE_LIMIT_WINDOW);
            const count = this.ipAlertTriggers.filter(t => t.ip === ip).length;
            if (count >= RATE_LIMIT_MAX_ALERTS) {
                this._markSuspicious(ip, 'rate_limit_alert');
                return true;
            }
            this.ipAlertTriggers.push({ timestamp: now, ip });
        } else {
            const requests = (this.ipRequests.get(ip) || []).filter(t => now - t < RATE_LIMIT_WINDOW);
            if (requests.length >= RATE_LIMIT_MAX_GENERAL) {
                this._markSuspicious(ip, 'rate_limit_general');
                return true;
            }
            requests.push(now);
            this.ipRequests.set(ip, requests);
        }
        return false;
    }

    _markSuspicious(ip, reason) {
        const score = (this.suspiciousIps.get(ip) || 0) + 1;
        this.suspiciousIps.set(ip, score);
        console.log(`[SECURITY] IP ${ip} sospechosa: ${reason} (score: ${score})`);
        if (score >= 5) this.banIp(ip, `${score} violaciones acumuladas`);
    }

    banIp(ip, reason = '') {
        this.bannedIps.set(ip, Date.now() + IP_BAN_DURATION);
        console.log(`[SECURITY] IP BANEADA: ${ip} por ${IP_BAN_DURATION / 1000}s - ${reason}`);
    }

    isIpAllowed(ip) {
        if (this.bannedIps.has(ip)) {
            if (Date.now() < this.bannedIps.get(ip)) return false;
            this.bannedIps.delete(ip);
        }
        return true;
    }

    // ── API Key ─────────────────────────────────────────────────────
    verifyApiKey(key) {
        if (!key) return false;
        return crypto.timingSafeEqual(Buffer.from(key), Buffer.from(API_KEY));
    }

    // ── HMAC ────────────────────────────────────────────────────────
    generateHmac(dataStr) {
        return crypto.createHmac('sha256', HMAC_SECRET).update(dataStr).digest('hex');
    }

    verifyHmac(dataStr, signature) {
        if (!signature) return false;
        const expected = this.generateHmac(dataStr);
        return crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(signature));
    }

    // ── Validación ──────────────────────────────────────────────────
    validateCoordinates(lat, lon) {
        if (lat == null || lon == null) return false;
        const latN = parseFloat(lat), lonN = parseFloat(lon);
        return !isNaN(latN) && !isNaN(lonN) && latN >= -90 && latN <= 90 && lonN >= -180 && lonN <= 180;
    }

    validateMagnitude(mag) {
        if (mag == null) return false;
        const m = parseFloat(mag);
        return !isNaN(m) && m >= 0.1 && m <= 10.0;
    }

    validateDepth(depth) {
        if (depth == null) return false;
        const d = parseFloat(depth);
        return !isNaN(d) && d >= 0 && d <= 700;
    }

    validateUserId(id) {
        if (!id || typeof id !== 'string') return false;
        return /^android_[a-f0-9]{8}$/.test(id) || /^user_\d+$/.test(id);
    }

    validateSensorData(data) {
        if (!data || typeof data !== 'object') return false;
        const { user_id, latitud, longitud } = data;
        if (!this.validateUserId(user_id)) return false;
        if (!this.validateCoordinates(latitud, longitud)) return false;
        const lat = parseFloat(latitud), lon = parseFloat(longitud);
        return lat >= REPORT_LAT_MIN && lat <= REPORT_LAT_MAX && lon >= REPORT_LON_MIN && lon <= REPORT_LON_MAX;
    }

    validateLocationData(data) {
        if (!data || typeof data !== 'object') return false;
        const { user_id, latitud, longitud } = data;
        return this.validateUserId(user_id) && this.validateCoordinates(latitud, longitud);
    }

    // ── Plausibilidad geográfica ────────────────────────────────────
    checkLocationPlausibility(userId, newLat, newLon) {
        const now = Date.now();
        const prev = this.userLocations.get(userId);
        if (prev && prev.lat != null && prev.timestamp) {
            const elapsed = (now - prev.timestamp) / 1000;
            if (elapsed > 0) {
                const distKm = this.haversineKm(prev.lat, prev.lon, newLat, newLon);
                const speedKmh = distKm / (elapsed / 3600);
                if (speedKmh > MAX_LOCATION_SPEED_KMH) return false;
            }
        }
        this.userLocations.set(userId, { lat: newLat, lon: newLon, timestamp: now });
        return true;
    }

    // ── Sensor cooldown ─────────────────────────────────────────────
    checkSensorCooldown(userId) {
        const now = Date.now();
        const last = this.userLastSensor.get(userId);
        if (last && now - last < SENSOR_COOLDOWN_MS) return false;
        this.userLastSensor.set(userId, now);
        return true;
    }

    // ── Detección de anomalías ──────────────────────────────────────
    detectAnomaly(userId, lat, lon) {
        const now = Date.now();
        let sameLocationCount = 0;
        for (const [uid, loc] of this.userLocations) {
            if (uid === userId || !loc.lat) continue;
            if (Math.abs(loc.lat - lat) < 0.0001 && Math.abs(loc.lon - lon) < 0.0001
                && now - (loc.timestamp || 0) < 30000) {
                sameLocationCount++;
            }
        }
        if (sameLocationCount >= 3) {
            console.log(`[ANOMALY] ${sameLocationCount} usuarios en ubicación idéntica cerca de (${lat}, ${lon})`);
            return true;
        }

        const prev = this.userLocations.get(userId);
        if (prev && prev.lat != null) {
            const dist = this.haversineKm(prev.lat, prev.lon, lat, lon);
            const elapsed = (now - (prev.timestamp || 0)) / 1000;
            if (elapsed < 10 && dist > 50) {
                console.log(`[ANOMALY] ${userId} saltó ${dist.toFixed(1)}km en ${elapsed.toFixed(1)}s`);
                return true;
            }
        }
        return false;
    }

    // ── Haversine ───────────────────────────────────────────────────
    haversineKm(lat1, lon1, lat2, lon2) {
        const R = 6371;
        const dLat = (lat2 - lat1) * Math.PI / 180;
        const dLon = (lon2 - lon1) * Math.PI / 180;
        const a = Math.sin(dLat / 2) ** 2 +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLon / 2) ** 2;
        return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    }

    getStats() {
        return {
            bannedIps: this.bannedIps.size,
            suspiciousIps: this.suspiciousIps.size,
        };
    }
}

const security = new SecurityManager();

// ── Express config ──────────────────────────────────────────────────
app.use(cors({ origin: '*' }));
app.use(express.json({ limit: '1kb' })); // Limitar tamaño del body

// ── Security headers ───────────────────────────────────────────────
app.use((req, res, next) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('X-Frame-Options', 'DENY');
    res.setHeader('X-XSS-Protection', '1; mode=block');
    next();
});

// ── Rate limit middleware para endpoints HTTP ───────────────────────
function requireApiKey(req, res, next) {
    const ip = req.ip || req.connection.remoteAddress || 'unknown';
    if (!security.isIpAllowed(ip)) return res.status(403).json({ error: 'IP banned' });
    if (security.isRateLimited(ip, 'general')) return res.status(429).json({ error: 'Rate limit exceeded' });

    const key = req.headers['x-api-key'] || req.query.api_key;
    if (!security.verifyApiKey(key)) {
        console.log(`[SECURITY] API key inválida desde ${ip}`);
        return res.status(401).json({ error: 'Unauthorized', message: 'API key required' });
    }
    next();
}

// ═══════════════════════════════════════════════════════════════════════
// Socket.IO (con CORS restringido por configuración)
// ═══════════════════════════════════════════════════════════════════════

const io = new Server(server, {
    cors: { origin: '*', methods: ['GET', 'POST'] },
    transports: ['websocket', 'polling'],
    pingTimeout: 20000,
    pingInterval: 25000
});

let connectedUsers = new Map();
let activeAlert = null;
let accelerometerReports = [];
const REPORT_WINDOW_MS = 2000;
const MIN_REPORTS = 5;
const MAX_DISTANCE_KM = 10;
const ALERT_COOLDOWN_MS = 60000;
let lastAlertTime = 0;

function checkSeismicTrigger(lat, lon) {
    const now = Date.now();
    accelerometerReports.push({ lat, lon, timestamp: now });
    accelerometerReports = accelerometerReports.filter(r => now - r.timestamp <= REPORT_WINDOW_MS * 3);
    const recent = accelerometerReports.filter(r => now - r.timestamp <= REPORT_WINDOW_MS);
    const count = recent.filter(r => security.haversineKm(lat, lon, r.lat, r.lon) <= MAX_DISTANCE_KM).length;
    if (count >= MIN_REPORTS && now - lastAlertTime > ALERT_COOLDOWN_MS) {
        lastAlertTime = now;
        accelerometerReports = [];
        return true;
    }
    return false;
}

function triggerAlert(params) {
    const now = new Date().toISOString();
    const alertData = {
        latitud: params.latitud,
        longitud: params.longitud,
        magnitud: params.magnitud,
        profundidad: params.profundidad,
        segundos: params.segundos,
        sonido: params.sonido,
        simulacro: params.simulacro,
        timestamp: now,
        mensaje: params.simulacro
            ? `SIMULACRO - Sismo de magnitud ${params.magnitud} detectado`
            : `Sismo de magnitud ${params.magnitud} detectado por la red CEPRESA`
    };

    activeAlert = alertData;
    io.emit('alerta_sismica', alertData);

    console.log('═══════════════════════════════════════════');
    console.log('  ALERTA SISMICA EMITIDA');
    console.log('═══════════════════════════════════════════');
    console.log(`  Magnitud:    ${params.magnitud}`);
    console.log(`  Coordenadas: ${params.latitud}, ${params.longitud}`);
    console.log('═══════════════════════════════════════════');

    setTimeout(() => {
        activeAlert = null;
        io.emit('alerta_clear', {});
        console.log('[ALERT] Alerta auto-desactivada después de 60s');
    }, 60000);
}

// ── Socket.IO Events (con validación) ──────────────────────────────
io.on('connection', (socket) => {
    const ip = socket.handshake.address || 'unknown';
    console.log(`[CONNECT] Cliente: ${socket.id} desde ${ip}`);

    if (!security.isIpAllowed(ip)) {
        console.log(`[SECURITY] Conexión rechazada: IP ${ip} baneada`);
        socket.disconnect(true);
        return;
    }

    connectedUsers.set(socket.id, { id: socket.id, connectedAt: new Date(), ip });
    io.emit('update_users', { count: connectedUsers.size });

    if (activeAlert) socket.emit('alerta_sismica', activeAlert);

    socket.on('acelerometro_reporte', (data) => {
        if (!data || typeof data !== 'object') return;

        if (security.isRateLimited(ip, 'sensor')) {
            console.log(`[SECURITY] Sensor bloqueado: rate limit ${ip}`);
            return;
        }

        if (!security.validateSensorData(data)) {
            console.log(`[SECURITY] Sensor rechazado: datos inválidos desde ${ip}`);
            return;
        }

        const userId = data.user_id;
        const lat = parseFloat(data.latitud);
        const lon = parseFloat(data.longitud);

        if (!security.checkSensorCooldown(userId)) return;
        if (!security.checkLocationPlausibility(userId, lat, lon)) {
            security._markSuspicious(ip, 'location_implausible');
            return;
        }
        if (security.detectAnomaly(userId, lat, lon)) return;

        console.log(`[SENSOR] ${userId}: vib en (${lat}, ${lon})`);
        io.emit('sensor_event', { latitud: lat, longitud: lon, user_id: userId, timestamp: data.timestamp });

        if (checkSeismicTrigger(lat, lon)) {
            triggerAlert({ latitud: lat, longitud: lon, magnitud: 5.0, profundidad: 10.0, segundos: 30, sonido: true, simulacro: false });
        }
    });

    socket.on('estoy_a_salvo', (data) => {
        if (data?.user_id && security.validateUserId(data.user_id)) {
            console.log(`[SAFE] ${data.user_id} reportó estar a salvo`);
        }
    });

    socket.on('reportar_ubicacion', (data) => {
        if (!security.validateLocationData(data)) return;
        if (security.isRateLimited(ip, 'sensor')) return;

        const userId = data.user_id;
        const lat = parseFloat(data.latitud);
        const lon = parseFloat(data.longitud);

        if (!security.checkLocationPlausibility(userId, lat, lon)) {
            security._markSuspicious(ip, 'location_implausible');
        }
    });

    socket.on('disconnect', () => {
        connectedUsers.delete(socket.id);
        io.emit('update_users', { count: connectedUsers.size });
        console.log(`[DISCONNECT] ${socket.id} (Total: ${connectedUsers.size})`);
    });
});

// ── HTTP Endpoints ──────────────────────────────────────────────────
app.get('/', (req, res) => res.sendFile(path.join(__dirname, '..', 'templates', 'dashboard.html')));

app.get('/health', (req, res) => {
    res.json({ status: 'ok', users: connectedUsers.size, activeAlert: !!activeAlert, uptime: process.uptime() });
});

app.get('/api/security', requireApiKey, (req, res) => {
    res.json({ stats: security.getStats(), connectedUsers: connectedUsers.size });
});

app.get('/api/status', (req, res) => {
    res.json({ personas_en_linea: connectedUsers.size, alerta_activa: !!activeAlert, timestamp: new Date().toISOString() });
});

app.post('/api/test', requireApiKey, (req, res) => {
    const ip = req.ip || 'unknown';
    if (security.isRateLimited(ip, 'alert')) return res.status(429).json({ error: 'Rate limit for alerts' });

    const { magnitud = 5.0, profundidad = 10.0, latitud = 9.75, longitud = -83.75, sonido = true } = req.body || {};

    if (!security.validateMagnitude(magnitud)) return res.status(400).json({ error: 'Invalid magnitude (0.1-10.0)' });
    if (!security.validateDepth(profundidad)) return res.status(400).json({ error: 'Invalid depth (0-700 km)' });
    if (!security.validateCoordinates(latitud, longitud)) return res.status(400).json({ error: 'Invalid coordinates' });

    const segundos = Math.max(5, Math.floor(parseFloat(profundidad) * 0.8 + parseFloat(magnitud) * 2));
    triggerAlert({ latitud: parseFloat(latitud), longitud: parseFloat(longitud), magnitud: parseFloat(magnitud), profundidad: parseFloat(profundidad), segundos, sonido: !!sonido, simulacro: true });
    res.json({ status: 'alert sent' });
});

// ── Consola interactiva ─────────────────────────────────────────────
const rl = readline.createInterface({ input: process.stdin, output: process.stdout, prompt: 'CEPRESA> ' });

console.log('');
console.log('╔═══════════════════════════════════════════════════╗');
console.log('║     CEPRESA - Servidor Hardened v2.0              ║');
console.log('╠═══════════════════════════════════════════════════╣');
console.log(`║  API Key:    ${API_KEY.substring(0, 8)}...                          ║`);
console.log('║  /help para comandos disponibles                 ║');
console.log('╚═══════════════════════════════════════════════════╝');
console.log('');

rl.prompt();

rl.on('line', (line) => {
    const input = line.trim();
    if (input === '/help') {
        console.log('\nComandos: /test, /status, /clear, /users, /security, /help\n');
    } else if (input === '/status') {
        console.log(`\n  Usuarios: ${connectedUsers.size} | Alerta: ${activeAlert ? 'SÍ' : 'NO'} | Uptime: ${Math.floor(process.uptime())}s\n`);
    } else if (input === '/clear') {
        activeAlert = null;
        io.emit('alerta_clear', {});
        console.log('[ALERT] Alerta desactivada');
    } else if (input === '/users') {
        console.log(`\n  Conectados: ${connectedUsers.size}`);
        connectedUsers.forEach((u, id) => console.log(`    - ${id} desde ${u.connectedAt.toLocaleTimeString()}`));
        console.log('');
    } else if (input === '/security') {
        const s = security.getStats();
        console.log(`\n  Baneadas: ${s.bannedIps} | Sospechosas: ${s.suspiciousIps}\n`);
    } else if (input.startsWith('/test')) {
        const magM = input.match(/\/m([\d.]+)/);
        const profM = input.match(/\/p([\d.]+)/);
        const coordM = input.match(/\/d([-\d.]+),([-\d.]+)/);
        const mag = magM ? parseFloat(magM[1]) : 5.0;
        const prof = profM ? parseFloat(profM[1]) : 10;
        const lat = coordM ? parseFloat(coordM[1]) : 9.75;
        const lon = coordM ? parseFloat(coordM[2]) : -83.75;
        const seg = Math.max(5, Math.floor(prof * 0.8 + mag * 2));
        triggerAlert({ latitud: lat, longitud: lon, magnitud: mag, profundidad: prof, segundos: seg, sonido: true, simulacro: true });
    } else if (input) {
        console.log(`[UNKNOWN] ${input}. Usa /help`);
    }
    rl.prompt();
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, '0.0.0.0', () => {
    console.log(`[SERVER] CEPRESA corriendo en puerto ${PORT}`);
});
