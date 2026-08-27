const express = require('express');
const http = require('http');
const { Server } = require('socket.io');
const cors = require('cors');
const readline = require('readline');

const app = express();
const server = http.createServer(app);

app.use(cors());
app.use(express.json());

// ── Socket.IO ─────────────────────────────────────────────────────────
const io = new Server(server, {
    cors: {
        origin: '*',
        methods: ['GET', 'POST']
    },
    transports: ['websocket', 'polling'],
    pingTimeout: 20000,
    pingInterval: 25000
});

// ── Estado del servidor ───────────────────────────────────────────────
let connectedUsers = new Map();
let activeAlert = null;

// ── Eventos Socket.IO ────────────────────────────────────────────────
io.on('connection', (socket) => {
    console.log(`[CONNECT] Cliente conectado: ${socket.id}`);

    connectedUsers.set(socket.id, {
        id: socket.id,
        connectedAt: new Date()
    });

    io.emit('update_users', { count: connectedUsers.size });
    console.log(`[USERS] Usuarios en línea: ${connectedUsers.size}`);

    // Si hay una alerta activa, enviarla al nuevo cliente
    if (activeAlert) {
        socket.emit('alerta_sismica', activeAlert);
    }

    // ── Evento: Reporte del acelerómetro ──────────────────────────────
    socket.on('acelerometro_reporte', (data) => {
        console.log(`[SENSOR] ${data.user_id}: vib en (${data.latitud}, ${data.longitud})`);
        io.emit('sensor_event', {
            latitud: data.latitud,
            longitud: data.longitud,
            user_id: data.user_id,
            timestamp: data.timestamp
        });
    });

    // ── Evento: Cliente reporta "estoy a salvo" ──────────────────────
    socket.on('estoy_a_salvo', (data) => {
        console.log(`[SAFE] ${data.user_id} reportó estar a salvo`);
    });

    socket.on('disconnect', () => {
        connectedUsers.delete(socket.id);
        io.emit('update_users', { count: connectedUsers.size });
        console.log(`[DISCONNECT] Cliente desconectado: ${socket.id}`);
        console.log(`[USERS] Usuarios en línea: ${connectedUsers.size}`);
    });
});

// ── Dashboard HTML ────────────────────────────────────────────────────
app.get('/', (req, res) => {
    res.send(getDashboardHTML());
});

// ── Health check ──────────────────────────────────────────────────────
app.get('/health', (req, res) => {
    res.json({
        status: 'ok',
        users: connectedUsers.size,
        activeAlert: !!activeAlert,
        uptime: process.uptime()
    });
});

// ── Comando /test - Consola del servidor ──────────────────────────────
// Formato: /test /m(magnitud) /p(profundidad) /d(lat,lon) /s(on/off)
// Ejemplo: /test /m6.5 /p15 /d9.75,-83.75 /son
//
// Si se ejecuta, el texto de la alerta siempre tendrá "SIMULACRO" en grande
// ──────────────────────────────────────────────────────────────────────

function parseTestCommand(input) {
    const cmd = input.trim();

    if (!cmd.startsWith('/test')) {
        return null;
    }

    const magnitudeMatch = cmd.match(/\/m([\d.]+)/);
    const depthMatch = cmd.match(/\/p([\d.]+)/);
    const coordsMatch = cmd.match(/\/d([-\d.]+),([-\d.]+)/);
    const soundMatch = cmd.match(/\/s(on|off|on|off)/i);

    const magnitud = magnitudeMatch ? parseFloat(magnitudeMatch[1]) : 5.0;
    const profundidad = depthMatch ? parseFloat(depthMatch[1]) : 10;
    const latitud = coordsMatch ? parseFloat(coordsMatch[1]) : 9.75;
    const longitud = coordsMatch ? parseFloat(coordsMatch[2]) : -83.75;
    const sonido = soundMatch ? soundMatch[1].toLowerCase() === 'on' : true;

    // Calcular segundos estimados de llegada (fórmula simplificada)
    // Velocidad promedio de ondas P: ~6 km/s, ondas S: ~3.5 km/s
    const distanciaKm = 0; // Se calcularía con la ubicación del usuario
    const segundosEstimados = Math.max(5, Math.floor(profundidad * 0.8 + magnitud * 2));

    return {
        magnitud,
        profundidad,
        latitud,
        longitud,
        sonido,
        segundosEstimados,
        simulacro: true
    };
}

function triggerAlert(params) {
    const now = new Date();
    const timestamp = now.toISOString();

    const alertData = {
        latitud: params.latitud,
        longitud: params.longitud,
        magnitud: params.magnitud,
        profundidad: params.profundidad,
        segundos: params.segundosEstimados,
        sonido: params.sonido,
        simulacro: params.simulacro,
        timestamp,
        mensaje: params.simulacro
            ? `SIMULACRO - Sismo de magnitud ${params.magnitud} detectado`
            : `Sismo de magnitud ${params.magnitud} detectado por la red CEPRESA`
    };

    activeAlert = alertData;
    io.emit('alerta_sismica', alertData);

    console.log('═══════════════════════════════════════════');
    console.log('  ⚠️  ALERTA SÍSMICA EMITIDA');
    console.log('═══════════════════════════════════════════');
    console.log(`  Magnitud:    ${params.magnitud}`);
    console.log(`  Profundidad: ${params.profundidad} km`);
    console.log(`  Coordenadas: ${params.latitud}, ${params.longitud}`);
    console.log(`  Segundos:    ${params.segundosEstimados}`);
    console.log(`  Sonido:      ${params.sonido ? 'ON' : 'OFF'}`);
    console.log(`  SIMULACRO:   SÍ`);
    console.log('═══════════════════════════════════════════');

    // Auto-clear after 60 seconds
    setTimeout(() => {
        activeAlert = null;
        io.emit('alerta_clear', {});
        console.log('[ALERT] Alerta auto-desactivada después de 60s');
    }, 60000);
}

// ── Consola interactiva ───────────────────────────────────────────────
const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
    prompt: 'CEPRESA> '
});

console.log('');
console.log('╔═══════════════════════════════════════════════════╗');
console.log('║         CEPRESA - Servidor de Alerta Sísmica     ║');
console.log('╠═══════════════════════════════════════════════════╣');
console.log('║  Comando: /test /m<magnitud> /p<prof> /d<lat,lon> ║');
console.log('║          /s(on/off) - Sonido de la alerta         ║');
console.log('║                                                   ║');
console.log('║  Ejemplo:                                         ║');
console.log('║    /test /m6.5 /p15 /d9.75,-83.75 /s on          ║');
console.log('║                                                   ║');
console.log('║  NOTA: Siempre se envía como SIMULACRO            ║');
console.log('╚═══════════════════════════════════════════════════╝');
console.log('');

rl.prompt();

rl.on('line', (line) => {
    const input = line.trim();

    if (input === '/help') {
        console.log('');
        console.log('Comandos disponibles:');
        console.log('  /test /m<mag> /p<prof> /d<lat,lon> /s(on/off)  - Emitir alerta');
        console.log('  /status  - Estado del servidor');
        console.log('  /clear   - Desactivar alerta activa');
        console.log('  /users   - Usuarios conectados');
        console.log('  /help    - Mostrar esta ayuda');
        console.log('');
    } else if (input === '/status') {
        console.log('');
        console.log(`  Usuarios conectados: ${connectedUsers.size}`);
        console.log(`  Alerta activa: ${activeAlert ? 'SÍ' : 'NO'}`);
        console.log(`  Uptime: ${Math.floor(process.uptime())}s`);
        console.log('');
    } else if (input === '/clear') {
        activeAlert = null;
        io.emit('alerta_clear', {});
        console.log('[ALERT] Alerta desactivada manualmente');
    } else if (input === '/users') {
        console.log('');
        console.log(`  Usuarios conectados: ${connectedUsers.size}`);
        connectedUsers.forEach((user, id) => {
            console.log(`    - ${id} (desde ${user.connectedAt.toLocaleTimeString()})`);
        });
        console.log('');
    } else if (input.startsWith('/test')) {
        const params = parseTestCommand(input);
        if (params) {
            triggerAlert(params);
        } else {
            console.log('[ERROR] Formato: /test /m<magnitud> /p<profundidad> /d<lat,lon> /s(on/off)');
        }
    } else if (input) {
        console.log(`[UNKNOWN] Comando no reconocido: ${input}. Usa /help`);
    }

    rl.prompt();
});

// ── Puerto ────────────────────────────────────────────────────────────
const PORT = process.env.PORT || 3000;
server.listen(PORT, '0.0.0.0', () => {
    console.log(`[SERVER] Servidor CEPRESA corriendo en puerto ${PORT}`);
});

// ── Dashboard HTML ────────────────────────────────────────────────────
function getDashboardHTML() {
    return `<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CEPRESA - Dashboard</title>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', system-ui, sans-serif;
            background: #0f0f1a;
            color: #e0e0e0;
            overflow: hidden;
            height: 100vh;
        }
        #map { position: absolute; top: 0; left: 0; width: 100%; height: 100%; z-index: 1; }
        .overlay {
            position: absolute; top: 0; left: 0; right: 0; z-index: 1000;
            background: linear-gradient(180deg, rgba(15,15,26,0.95) 0%, rgba(15,15,26,0.7) 80%, transparent 100%);
            padding: 20px 30px;
            display: flex; justify-content: space-between; align-items: center;
        }
        .brand { font-size: 1.8rem; font-weight: 800; color: #e94560; letter-spacing: 3px; }
        .stats { text-align: right; }
        .stats .count {
            font-size: 2.8rem; font-weight: 700;
            color: #e94560;
        }
        .stats .label { font-size: 0.85rem; color: #888; text-transform: uppercase; letter-spacing: 1px; }
        #alert-overlay {
            display: none; position: fixed; top: 0; left: 0; right: 0; bottom: 0;
            z-index: 9999; background: rgba(180,0,0,0.15);
            animation: alertFlash 0.8s infinite alternate;
        }
        @keyframes alertFlash {
            from { background: rgba(180,0,0,0.1); }
            to { background: rgba(180,0,0,0.35); }
        }
        #alert-message {
            display: none; position: fixed; top: 50%; left: 50%;
            transform: translate(-50%,-50%); z-index: 10000;
            background: rgba(140,0,0,0.95); color: #fff;
            padding: 40px 60px; border-radius: 12px; text-align: center;
            border: 3px solid #ff0000;
            box-shadow: 0 0 80px rgba(255,0,0,0.6);
        }
        #alert-message h1 { font-size: 2.5rem; margin-bottom: 10px; }
        #alert-message .simulacro { font-size: 1.5rem; color: #ffcc00; font-weight: bold; margin-bottom: 10px; }
        #alert-message .details { font-size: 1rem; color: #ffcccc; margin-top: 10px; }
    </style>
</head>
<body>
    <div id="map"></div>
    <div class="overlay">
        <div class="brand">CEPRESA</div>
        <div class="stats">
            <div class="count" id="user-count">0</div>
            <div class="label">personas en línea</div>
        </div>
    </div>
    <div id="alert-overlay"></div>
    <div id="alert-message">
        <div class="simulacro" id="alert-simulacro" style="display:none">⚠ SIMULACRO ⚠</div>
        <h1>ALERTA SÍSMICA</h1>
        <p>Sismo detectado por la red CEPRESA</p>
        <div class="details" id="alert-detail"></div>
    </div>
    <script>
        const map = L.map('map', { zoomControl: false, attributionControl: false }).setView([9.75,-83.75], 7);
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', { maxZoom: 19 }).addTo(map);
        const socket = io();
        let alertActive = false;
        socket.on('connect', () => console.log('Conectado'));
        socket.on('update_users', (d) => document.getElementById('user-count').textContent = d.count);
        socket.on('alerta_sismica', (d) => {
            document.getElementById('alert-overlay').style.display = 'block';
            const msg = document.getElementById('alert-message');
            msg.style.display = 'block';
            if (d.simulacro) document.getElementById('alert-simulacro').style.display = 'block';
            document.getElementById('alert-detail').innerHTML =
                'Magnitud: ' + d.magnitud + ' | Profundidad: ' + d.profundidad + ' km<br>' +
                'Coordenadas: ' + d.latitud.toFixed(4) + ', ' + d.longitud.toFixed(4) + '<br>' +
                'Tiempo estimado: ' + d.segundos + 's';
            map.setView([d.latitud, d.longitud], 9);
            L.marker([d.latitud, d.longitud]).addTo(map).bindPopup('ALERTA SÍSMICA').openPopup();
            setTimeout(() => {
                document.getElementById('alert-overlay').style.display = 'none';
                msg.style.display = 'none';
                document.getElementById('alert-simulacro').style.display = 'none';
            }, 30000);
        });
        socket.on('alerta_clear', () => {
            document.getElementById('alert-overlay').style.display = 'none';
            document.getElementById('alert-message').style.display = 'none';
            document.getElementById('alert-simulacro').style.display = 'none';
        });
    </script>
</body>
</html>`;
}
