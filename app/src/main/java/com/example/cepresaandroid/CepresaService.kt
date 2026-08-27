package com.example.cepresaandroid

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.IBinder
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import io.socket.client.IO
import io.socket.client.Socket
import io.socket.emitter.Emitter
import org.json.JSONObject
import java.util.UUID

class CepresaService : Service(), SensorEventListener, LocationListener {

    companion object {
        const val TAG = "CepresaService"
        const val CHANNEL_ID = "cepresa_channel"
        const val NOTIFICATION_ID = 1
        const val ALERT_NOTIFICATION_ID = 2
        const val SERVER_URL = "https://servidorcepresa-production.up.railway.app/"
        const val ACTION_UPDATE_USERS = "com.example.cepresaandroid.UPDATE_USERS"
        const val ACTION_ALERT = "com.example.cepresaandroid.ALERT"
        const val MIN_MAGNITUDE = 3.5
        const val CARTO_API_KEY = "cb1_29g6_1_201a8281a4099feebd035b61"

        private const val VIBRATION_THRESHOLD = 15.0f
        private const val COOLDOWN_MS = 15000L
        private const val SENSOR_DELAY_US = 1000000
        private const val MIN_LOCATION_INTERVAL_MS = 60000L
        private const val MIN_LOCATION_DISTANCE_M = 30f
        private const val LOCATION_REPORT_INTERVAL_MS = 60000L

        var isRunning = false
            private set
        var onlineCount = 0
            private set
    }

    private var socket: Socket? = null
    private lateinit var sensorManager: SensorManager
    private var accelerometer: Sensor? = null
    private lateinit var locationManager: LocationManager
    private var wakeLock: PowerManager.WakeLock? = null

    private var userId: String = ""
    private var lastKnownLocation: Location? = null
    private var lastReportTime = 0L
    private var handler: android.os.Handler? = null

    private val locationListener = object : LocationListener {
        override fun onLocationChanged(location: Location) {
            lastKnownLocation = location
        }

        @Deprecated("Deprecated in API")
        override fun onStatusChanged(provider: String?, status: Int, extras: android.os.Bundle?) {}
        override fun onProviderEnabled(provider: String) {}
        override fun onProviderDisabled(provider: String) {}
    }

    private val locationReportRunnable = object : Runnable {
        override fun run() {
            val loc = lastKnownLocation
            if (loc != null && socket?.connected() == true) {
                emitLocationReport(loc.latitude, loc.longitude)
            }
            handler?.postDelayed(this, LOCATION_REPORT_INTERVAL_MS)
        }
    }

    private val onConnect = Emitter.Listener {
        Log.d(TAG, "Socket conectado al servidor")
        val loc = lastKnownLocation
        if (loc != null) {
            emitLocationReport(loc.latitude, loc.longitude)
        }
        handler?.post(locationReportRunnable)
    }

    private val onDisconnect = Emitter.Listener {
        Log.d(TAG, "Socket desconectado del servidor")
        handler?.removeCallbacks(locationReportRunnable)
    }

    private val onUpdateUsers = Emitter.Listener { args ->
        try {
            val data = args[0] as JSONObject
            onlineCount = data.getInt("count")
            val intent = Intent(ACTION_UPDATE_USERS).apply {
                putExtra("count", onlineCount)
                setPackage(packageName)
            }
            sendBroadcast(intent)
        } catch (e: Exception) {
            Log.e(TAG, "Error parsing update_users: ${e.message}")
        }
    }

    private val onAlertaSismica = Emitter.Listener { args ->
        try {
            val data = args[0] as JSONObject
            Log.w(TAG, "ALERTA SISMICA RECIBIDA: $data")

            val latitud = data.getDouble("latitud")
            val longitud = data.getDouble("longitud")
            val magnitud = data.optDouble("magnitud", 0.0)
            val profundidad = data.optDouble("profundidad", 0.0)
            val segundos = data.optInt("segundos", 30)
            val sonido = data.optBoolean("sonido", true)
            val simulacro = data.optBoolean("simulacro", false)
            val mensaje = data.optString("mensaje", "Sismo detectado")
            val timestamp = data.optString("timestamp", "")

            val alertIntent = Intent(ACTION_ALERT).apply {
                putExtra("latitud", latitud)
                putExtra("longitud", longitud)
                putExtra("magnitud", magnitud)
                putExtra("profundidad", profundidad)
                putExtra("segundos", segundos)
                putExtra("simulacro", simulacro)
                putExtra("mensaje", mensaje)
                setPackage(packageName)
            }
            sendBroadcast(alertIntent)

            if (magnitud >= MIN_MAGNITUDE) {
                val intent = Intent(this, AlertActivity::class.java).apply {
                    addFlags(
                        Intent.FLAG_ACTIVITY_NEW_TASK or
                                Intent.FLAG_ACTIVITY_CLEAR_TOP or
                                Intent.FLAG_ACTIVITY_SINGLE_TOP
                    )
                    putExtra("latitud", latitud)
                    putExtra("longitud", longitud)
                    putExtra("magnitud", magnitud)
                    putExtra("profundidad", profundidad)
                    putExtra("segundos", segundos)
                    putExtra("sonido", sonido)
                    putExtra("simulacro", simulacro)
                    putExtra("mensaje", mensaje)
                    putExtra("timestamp", timestamp)
                }
                startActivity(intent)
            } else {
                showLowMagnitudeNotification(magnitud, segundos, simulacro)
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error parsing alerta_sismica: ${e.message}")
        }
    }

    private val onAlertaClear = Emitter.Listener {
        Log.d(TAG, "Alerta desactivada por el servidor")
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        isRunning = true
        userId = getOrCreateUserId()
        sensorManager = getSystemService(Context.SENSOR_SERVICE) as SensorManager
        accelerometer = sensorManager.getDefaultSensor(Sensor.TYPE_ACCELEROMETER)
        locationManager = getSystemService(Context.LOCATION_SERVICE) as LocationManager

        createNotificationChannel()
        startForegroundNotification()
        handler = android.os.Handler(android.os.Looper.getMainLooper())

        acquireWakeLock()
        connectSocket()
        startSensors()
        startLocationUpdates()

        saveServiceActive(true)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        return START_STICKY
    }

    override fun onDestroy() {
        super.onDestroy()
        isRunning = false
        saveServiceActive(false)
        handler?.removeCallbacksAndMessages(null)
        disconnectSocket()
        stopSensors()
        stopLocationUpdates()
        releaseWakeLock()
    }

    private fun saveServiceActive(active: Boolean) {
        getSharedPreferences("cepresa", Context.MODE_PRIVATE)
            .edit().putBoolean("service_active", active).apply()
    }

    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "CEPRESA Alerta Sismica",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Monitoreo sismico activo"
                setShowBadge(false)
            }
            val manager = getSystemService(NotificationManager::class.java)
            manager.createNotificationChannel(channel)
        }
    }

    private fun startForegroundNotification() {
        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("CEPRESA activo")
            .setContentText("Monitoreando actividad sismica")
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setOngoing(true)
            .setSilent(true)
            .build()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIFICATION_ID,
                notification,
                ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
            )
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun showLowMagnitudeNotification(magnitud: Double, segundos: Int, simulacro: Boolean) {
        val title = if (simulacro) "SIMULACRO - Sismo leve" else "Sismo leve detectado"
        val text = "Magnitud ${"%.1f".format(magnitud)} - Llega en ~${segundos}s"

        val notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle(title)
            .setContentText(text)
            .setSmallIcon(R.drawable.ic_launcher_foreground)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setStyle(
                NotificationCompat.BigTextStyle()
                    .bigText("$text\nMantengase alerta y siga las instrucciones de seguridad.")
            )
            .build()

        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        manager.notify(ALERT_NOTIFICATION_ID, notification)
    }

    private fun acquireWakeLock() {
        val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
        wakeLock = powerManager.newWakeLock(
            PowerManager.PARTIAL_WAKE_LOCK,
            "cepresa::sensor_wakelock"
        ).apply {
            acquire(6 * 60 * 60 * 1000L)
        }
    }

    private fun releaseWakeLock() {
        wakeLock?.let {
            if (it.isHeld) it.release()
        }
    }

    private fun connectSocket() {
        try {
            val opts = IO.Options().apply {
                reconnection = true
                reconnectionAttempts = Int.MAX_VALUE
                reconnectionDelay = 3000
                reconnectionDelayMax = 30000
                timeout = 30000
                upgrade = true
                rememberUpgrade = false
                transports = arrayOf("websocket", "polling")
            }

            socket = IO.socket(SERVER_URL, opts).apply {
                on(Socket.EVENT_CONNECT, onConnect)
                on(Socket.EVENT_DISCONNECT, onDisconnect)
                on(Socket.EVENT_CONNECT_ERROR) { args ->
                    val error = args.firstOrNull()
                    Log.e(TAG, "Error de conexion Socket.IO: $error")
                }
                on("update_users", onUpdateUsers)
                on("alerta_sismica", onAlertaSismica)
                on("alerta_clear", onAlertaClear)
                connect()
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error al crear socket: ${e.message}")
        }
    }

    private fun disconnectSocket() {
        socket?.disconnect()
        socket?.off()
        socket = null
    }

    private fun emitSensorEvent(latitud: Double, longitud: Double) {
        val data = JSONObject().apply {
            put("user_id", userId)
            put("latitud", latitud)
            put("longitud", longitud)
            put("timestamp", System.currentTimeMillis())
        }
        socket?.emit("acelerometro_reporte", data)
        Log.d(TAG, "Evento acelerometro emitido: $data")
    }

    fun emitEstoyASalvo() {
        val data = JSONObject().apply {
            put("user_id", userId)
            put("timestamp", System.currentTimeMillis())
        }
        socket?.emit("estoy_a_salvo", data)
        Log.d(TAG, "Evento estoy_a_salvo emitido")
    }

    private fun emitLocationReport(latitud: Double, longitud: Double) {
        val data = JSONObject().apply {
            put("user_id", userId)
            put("latitud", latitud)
            put("longitud", longitud)
        }
        socket?.emit("reportar_ubicacion", data)
        Log.d(TAG, "Ubicacion reportada: ($latitud, $longitud)")
    }

    private fun startSensors() {
        accelerometer?.let {
            sensorManager.registerListener(this, it, SENSOR_DELAY_US.toInt())
        }
    }

    private fun stopSensors() {
        sensorManager.unregisterListener(this)
    }

    override fun onSensorChanged(event: SensorEvent?) {
        if (event?.sensor?.type != Sensor.TYPE_ACCELEROMETER) return

        val x = event.values[0]
        val y = event.values[1]
        val z = event.values[2]

        val magnitude = Math.sqrt((x * x + y * y + z * z).toDouble()).toFloat()

        if (magnitude > VIBRATION_THRESHOLD) {
            val now = System.currentTimeMillis()
            if (now - lastReportTime > COOLDOWN_MS) {
                lastReportTime = now
                val loc = lastKnownLocation
                if (loc != null) {
                    emitSensorEvent(loc.latitude, loc.longitude)
                }
            }
        }
    }

    override fun onAccuracyChanged(sensor: Sensor?, accuracy: Int) {}

    @Suppress("MissingPermission")
    private fun startLocationUpdates() {
        try {
            if (locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
                locationManager.requestLocationUpdates(
                    LocationManager.GPS_PROVIDER,
                    MIN_LOCATION_INTERVAL_MS,
                    MIN_LOCATION_DISTANCE_M,
                    locationListener
                )
            }
            if (locationManager.isProviderEnabled(LocationManager.NETWORK_PROVIDER)) {
                locationManager.requestLocationUpdates(
                    LocationManager.NETWORK_PROVIDER,
                    MIN_LOCATION_INTERVAL_MS,
                    MIN_LOCATION_DISTANCE_M,
                    locationListener
                )
            }
            lastKnownLocation = getLastKnownLocation()
        } catch (e: SecurityException) {
            Log.e(TAG, "Sin permisos de ubicacion: ${e.message}")
        }
    }

    @Suppress("MissingPermission")
    private fun getLastKnownLocation(): Location? {
        var location: Location? = null
        try {
            location = locationManager.getLastKnownLocation(LocationManager.GPS_PROVIDER)
                ?: locationManager.getLastKnownLocation(LocationManager.NETWORK_PROVIDER)
        } catch (_: SecurityException) {}
        return location
    }

    private fun stopLocationUpdates() {
        locationManager.removeUpdates(locationListener)
    }

    override fun onLocationChanged(location: Location) {
        lastKnownLocation = location
    }

    @Deprecated("Deprecated in Java")
    override fun onStatusChanged(provider: String?, status: Int, extras: android.os.Bundle?) {}
    override fun onProviderEnabled(provider: String) {}
    override fun onProviderDisabled(provider: String) {}

    private fun getOrCreateUserId(): String {
        val prefs = getSharedPreferences("cepresa", Context.MODE_PRIVATE)
        var id = prefs.getString("user_id", null)
        if (id == null) {
            id = "android_${UUID.randomUUID().toString().take(8)}"
            prefs.edit().putString("user_id", id).apply()
        }
        return id
    }
}
