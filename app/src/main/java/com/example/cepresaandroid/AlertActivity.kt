package com.example.cepresaandroid

import android.app.Activity
import android.content.Context
import android.graphics.Color
import android.graphics.Paint
import android.graphics.drawable.GradientDrawable
import android.media.AudioAttributes
import android.media.AudioManager
import android.media.MediaPlayer
import android.os.Build
import android.os.Bundle
import android.os.CountDownTimer
import android.os.Handler
import android.os.Looper
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import android.provider.Settings
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import org.osmdroid.config.Configuration
import org.osmdroid.tileprovider.tilesource.TileSourceFactory
import org.osmdroid.util.GeoPoint
import org.osmdroid.views.MapView
import org.osmdroid.views.overlay.Marker
import org.osmdroid.views.overlay.Polygon
import java.io.File
import java.util.Locale

class AlertActivity : Activity() {

    private var mediaPlayer: MediaPlayer? = null
    private val handler = Handler(Looper.getMainLooper())
    private var vibrator: Vibrator? = null
    private var countDownTimer: CountDownTimer? = null
    private var mapView: MapView? = null

    private var latitud = 0.0
    private var longitud = 0.0
    private var magnitud = 0.0
    private var profundidad = 0.0
    private var segundos = 30
    private var sonido = true
    private var simulacro = false

    private val vibratePattern = longArrayOf(0, 800, 200, 800, 200, 800)

    @Suppress("DEPRECATION")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Configurar osmdroid
        Configuration.getInstance().load(this, getSharedPreferences("osmdroid", Context.MODE_PRIVATE))
        Configuration.getInstance().userAgentValue = packageName

        window.addFlags(
            WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON or
                    WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD or
                    WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or
                    WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON or
                    WindowManager.LayoutParams.FLAG_ALLOW_LOCK_WHILE_SCREEN_ON
        )

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true)
            setTurnScreenOn(true)
            val keyguardManager = getSystemService(Context.KEYGUARD_SERVICE) as android.app.KeyguardManager
            keyguardManager.requestDismissKeyguard(this, null)
        }

        setContentView(R.layout.activity_alert)

        latitud = intent.getDoubleExtra("latitud", 9.75)
        longitud = intent.getDoubleExtra("longitud", -83.75)
        magnitud = intent.getDoubleExtra("magnitud", 5.0)
        profundidad = intent.getDoubleExtra("profundidad", 10.0)
        segundos = intent.getIntExtra("segundos", 30)
        sonido = intent.getBooleanExtra("sonido", true)
        simulacro = intent.getBooleanExtra("simulacro", false)

        setupUI()
        startAlarm()
        startVibration()
        startCountdown()
        setupMap()
    }

    private fun setupUI() {
        val tvTitle = findViewById<TextView>(R.id.tvAlertTitle)
        val tvSimulacro = findViewById<TextView>(R.id.tvSimulacro)
        val tvMagnitude = findViewById<TextView>(R.id.tvMagnitude)
        val tvDepth = findViewById<TextView>(R.id.tvDepth)
        val btnSafe = findViewById<Button>(R.id.btnSafe)

        tvTitle.text = "ALERTA SÍSMICA"

        if (simulacro) {
            tvSimulacro.visibility = View.VISIBLE
            tvSimulacro.text = "⚠ SIMULACRO ⚠"
        } else {
            tvSimulacro.visibility = View.GONE
        }

        tvMagnitude.text = "M ${String.format(Locale.US, "%.1f", magnitud)}"
        val magColor = when {
            magnitud >= 7.0 -> Color.parseColor("#FF0000")
            magnitud >= 5.0 -> Color.parseColor("#FF6600")
            magnitud >= 3.5 -> Color.parseColor("#FFAA00")
            else -> Color.parseColor("#44FF44")
        }
        tvMagnitude.setTextColor(magColor)

        tvDepth.text = "Profundidad: ${String.format(Locale.US, "%.1f", profundidad)} km"

        btnSafe.setOnClickListener {
            dismissAlert()
        }
    }

    private fun startCountdown() {
        val tvCountdown = findViewById<TextView>(R.id.tvCountdown)
        val tvSecondsLabel = findViewById<TextView>(R.id.tvSecondsLabel)

        countDownTimer = object : CountDownTimer(segundos.toLong() * 1000, 1000) {
            override fun onTick(millisUntilFinished: Long) {
                val secondsRemaining = (millisUntilFinished / 1000).toInt()
                tvCountdown.text = "$secondsRemaining"
            }

            override fun onFinish() {
                tvCountdown.text = "0"
                tvCountdown.setTextColor(Color.parseColor("#FF0000"))
                tvSecondsLabel.text = "¡EL SISMO LLEGA!"
            }
        }.start()
    }

    private fun setupMap() {
        mapView = findViewById(R.id.mapView)
        mapView?.setTileSource(TileSourceFactory.MAPNIK)
        mapView?.setMultiTouchControls(true)
        mapView?.setBuiltInZoomControls(false)

        val mapController = mapView?.controller
        val epicenter = GeoPoint(latitud, longitud)

        mapController?.setZoom(8.0)
        mapController?.setCenter(epicenter)

        // Marcador del epicentro
        val marker = Marker(mapView)
        marker.position = epicenter
        marker.setAnchor(Marker.ANCHOR_CENTER, Marker.ANCHOR_CENTER)
        marker.title = "Epicentro - M${String.format(Locale.US, "%.1f", magnitud)}"
        marker.subDescription = "Profundidad: ${String.format(Locale.US, "%.1f", profundidad)} km"

        // Icono del marcador
        val markerDrawable = GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(Color.parseColor("#FF0000"))
            setSize(30, 30)
        }
        marker.icon = markerDrawable

        mapView?.overlays?.add(marker)

        // Círculo de afectación
        val radius = when {
            magnitud >= 7.0 -> 2.0  // grados
            magnitud >= 5.0 -> 1.0
            magnitud >= 3.5 -> 0.5
            else -> 0.2
        }

        val circlePoints = mutableListOf<GeoPoint>()
        for (i in 0..360 step 5) {
            val angle = Math.toRadians(i.toDouble())
            val lat = latitud + radius * Math.cos(angle)
            val lon = longitud + radius * Math.sin(angle)
            circlePoints.add(GeoPoint(lat, lon))
        }
        circlePoints.add(circlePoints.first())

        val polygon = Polygon()
        polygon.points = circlePoints
        polygon.fillColor = Color.parseColor("#33FF0000")
        polygon.strokeColor = Color.parseColor("#FF0000")
        polygon.strokeWidth = 3f

        mapView?.overlays?.add(polygon)
        mapView?.invalidate()
    }

    private fun startAlarm() {
        if (!sonido) return

        try {
            val alertUri = android.net.Uri.parse(
                "android.resource://${packageName}/${R.raw.alertasismica}"
            )
            mediaPlayer = MediaPlayer().apply {
                setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ALARM)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build()
                )
                setDataSource(this@AlertActivity, alertUri)
                isLooping = true
                prepare()
                start()
            }

            val audioManager = getSystemService(Context.AUDIO_SERVICE) as AudioManager
            @Suppress("DEPRECATION")
            audioManager.setStreamVolume(
                AudioManager.STREAM_ALARM,
                audioManager.getStreamMaxVolume(AudioManager.STREAM_ALARM),
                0
            )
        } catch (e: Exception) {
            e.printStackTrace()
        }
    }

    @Suppress("DEPRECATION")
    private fun startVibration() {
        vibrator = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val vm = getSystemService(Context.VIBRATOR_MANAGER_SERVICE) as VibratorManager
            vm.defaultVibrator
        } else {
            getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val effect = VibrationEffect.createWaveform(vibratePattern, 0)
            vibrator?.vibrate(effect)
        } else {
            vibrator?.vibrate(vibratePattern, 0)
        }
    }

    private fun stopAlarm() {
        try {
            mediaPlayer?.let {
                if (it.isPlaying) it.stop()
                it.release()
            }
        } catch (_: Exception) {}
        mediaPlayer = null
        vibrator?.cancel()
        countDownTimer?.cancel()
    }

    private fun dismissAlert() {
        stopAlarm()
        finish()
    }

    override fun onResume() {
        super.onResume()
        mapView?.onResume()
    }

    override fun onPause() {
        super.onPause()
        mapView?.onPause()
    }

    override fun onDestroy() {
        super.onDestroy()
        stopAlarm()
        mapView?.onDetach()
    }

    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        // No permitir cerrar
    }
}
