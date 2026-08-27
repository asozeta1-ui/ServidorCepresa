package com.example.cepresaandroid

import android.Manifest
import android.app.NotificationManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import com.example.cepresaandroid.ui.theme.*

class MainActivity : ComponentActivity() {

    private var onlineCount = 0

    private val requiredPermissions = buildList {
        add(Manifest.permission.ACCESS_FINE_LOCATION)
        add(Manifest.permission.ACCESS_COARSE_LOCATION)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            add(Manifest.permission.POST_NOTIFICATIONS)
            add(Manifest.permission.READ_MEDIA_AUDIO)
        } else {
            add(Manifest.permission.READ_EXTERNAL_STORAGE)
        }
    }

    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { _ ->
        requestBackgroundLocation()
    }

    private val backgroundLocationLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) {
        requestDndAccess()
    }

    private val batteryLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {
        requestDndAccess()
    }

    private val dndLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {
        startCepresaService()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()

        setContent {
            CepresaTheme {
                val context = LocalContext.current
                var usersOnline by remember { mutableIntStateOf(0) }
                var isServiceActive by remember { mutableStateOf(CepresaService.isRunning) }

                val receiver = remember {
                    object : BroadcastReceiver() {
                        override fun onReceive(ctx: Context?, intent: Intent?) {
                            usersOnline = intent?.getIntExtra("count", 0) ?: 0
                            isServiceActive = CepresaService.isRunning
                        }
                    }
                }

                DisposableEffect(Unit) {
                    val filter = IntentFilter(CepresaService.ACTION_UPDATE_USERS)
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                        registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED)
                    } else {
                        registerReceiver(receiver, filter)
                    }
                    onDispose {
                        unregisterReceiver(receiver)
                    }
                }

                LaunchedEffect(isServiceActive) {
                    if (isServiceActive) {
                        while (true) {
                            usersOnline = CepresaService.onlineCount
                            kotlinx.coroutines.delay(1000)
                        }
                    }
                }

                LaunchedEffect(Unit) {
                    if (!CepresaService.isRunning) {
                        startPermissionFlow()
                    }
                }

                MainScreen(
                    usersOnline = usersOnline,
                    isServiceActive = isServiceActive,
                    onStartService = { startPermissionFlow() }
                )
            }
        }
    }

    override fun onResume() {
        super.onResume()
    }

    private fun startPermissionFlow() {
        val missingPermissions = requiredPermissions.filter {
            ContextCompat.checkSelfPermission(this, it) != PackageManager.PERMISSION_GRANTED
        }

        if (missingPermissions.isNotEmpty()) {
            permissionLauncher.launch(missingPermissions.toTypedArray())
        } else {
            requestBackgroundLocation()
        }
    }

    private fun requestBackgroundLocation() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_BACKGROUND_LOCATION)
                != PackageManager.PERMISSION_GRANTED
            ) {
                backgroundLocationLauncher.launch(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
                return
            }
        }
        requestDndAccess()
    }

    private fun requestDndAccess() {
        val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !notificationManager.isNotificationPolicyAccessGranted) {
            val intent = Intent(Settings.ACTION_NOTIFICATION_POLICY_ACCESS_SETTINGS)
            dndLauncher.launch(intent)
            return
        }
        checkBatteryOptimization()
    }

    private fun checkBatteryOptimization() {
        val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
        if (!powerManager.isIgnoringBatteryOptimizations(packageName)) {
            val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                data = Uri.parse("package:$packageName")
            }
            batteryLauncher.launch(intent)
            return
        }
        startCepresaService()
    }

    private fun startCepresaService() {
        val intent = Intent(this, CepresaService::class.java)
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent)
        } else {
            startService(intent)
        }
    }
}

@Composable
fun MainScreen(
    usersOnline: Int,
    isServiceActive: Boolean,
    onStartService: () -> Unit
) {
    var showEducational by remember { mutableStateOf(false) }

    if (showEducational) {
        EducationalScreen(onBack = { showEducational = false })
        return
    }

    val infiniteTransition = rememberInfiniteTransition(label = "pulse")

    val ringRotation by infiniteTransition.animateFloat(
        initialValue = 0f,
        targetValue = 360f,
        animationSpec = infiniteRepeatable(
            animation = tween(20000, easing = LinearEasing),
            repeatMode = RepeatMode.Restart
        ),
        label = "ringRotation"
    )

    val centerScale by infiniteTransition.animateFloat(
        initialValue = 0.8f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(1500, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "centerScale"
    )

    val glowAlpha by infiniteTransition.animateFloat(
        initialValue = 0.3f,
        targetValue = 0.8f,
        animationSpec = infiniteRepeatable(
            animation = tween(2000, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse
        ),
        label = "glowAlpha"
    )

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.radialGradient(
                    colors = listOf(
                        Color(0xFF1a1a2e),
                        Color(0xFF0f0f1a),
                        Color(0xFF0a0a12)
                    ),
                    radius = 800f
                )
            )
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(24.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Spacer(modifier = Modifier.height(48.dp))

            Text(
                text = "CEPRESA",
                fontSize = 28.sp,
                fontWeight = FontWeight.Black,
                color = Color(0xFFe94560),
                letterSpacing = 8.sp
            )

            Spacer(modifier = Modifier.height(4.dp))

            Text(
                text = "SISTEMA DE ALERTA SISMICA",
                fontSize = 9.sp,
                color = Color(0xFF555555),
                letterSpacing = 3.sp
            )

            Spacer(modifier = Modifier.height(60.dp))

            Box(
                modifier = Modifier.size(220.dp),
                contentAlignment = Alignment.Center
            ) {
                Canvas(
                    modifier = Modifier
                        .fillMaxSize()
                        .alpha(if (isServiceActive) glowAlpha else 0.2f)
                ) {
                    val strokeWidth = 4.dp.toPx()
                    val radius = (size.minDimension - strokeWidth) / 2
                    val center = Offset(size.width / 2, size.height / 2)

                    drawArc(
                        color = Color(0xFFe94560),
                        startAngle = ringRotation,
                        sweepAngle = 120f,
                        useCenter = false,
                        topLeft = Offset(strokeWidth / 2, strokeWidth / 2),
                        size = androidx.compose.ui.geometry.Size(radius * 2, radius * 2),
                        style = androidx.compose.ui.graphics.drawscope.Stroke(
                            width = strokeWidth,
                            cap = StrokeCap.Round
                        )
                    )

                    drawArc(
                        color = Color(0xFF555555),
                        startAngle = ringRotation + 180f,
                        sweepAngle = 60f,
                        useCenter = false,
                        topLeft = Offset(strokeWidth / 2, strokeWidth / 2),
                        size = androidx.compose.ui.geometry.Size(radius * 2, radius * 2),
                        style = androidx.compose.ui.graphics.drawscope.Stroke(
                            width = strokeWidth / 2,
                            cap = StrokeCap.Round
                        )
                    )
                }

                Box(
                    modifier = Modifier
                        .size(180.dp)
                        .clip(CircleShape)
                        .background(
                            Brush.radialGradient(
                                colors = if (isServiceActive) {
                                    listOf(Color(0xFF2a2a3e), Color(0xFF1a1a2e))
                                } else {
                                    listOf(Color(0xFF1a1a1a), Color(0xFF111111))
                                }
                            )
                        )
                        .border(
                            width = 2.dp,
                            color = if (isServiceActive) Color(0xFF333355) else Color(0xFF222222),
                            shape = CircleShape
                        ),
                    contentAlignment = Alignment.Center
                ) {
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        modifier = Modifier.scale(centerScale)
                    ) {
                        Text(
                            text = if (isServiceActive) "$usersOnline" else "0",
                            fontSize = 56.sp,
                            fontWeight = FontWeight.Light,
                            color = if (isServiceActive) Color(0xFFe94560) else Color(0xFF333333)
                        )
                        Text(
                            text = "PROTEGIDOS",
                            fontSize = 10.sp,
                            color = if (isServiceActive) Color(0xFF888888) else Color(0xFF333333),
                            letterSpacing = 3.sp
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(24.dp))

            Text(
                text = "Asegurando $usersOnline personas",
                fontSize = 18.sp,
                fontWeight = FontWeight.Light,
                color = if (isServiceActive) Color(0xFFcccccc) else Color(0xFF444444),
                textAlign = TextAlign.Center
            )

            Spacer(modifier = Modifier.height(8.dp))

            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.alpha(if (isServiceActive) 0.8f else 0.3f)
            ) {
                Box(
                    modifier = Modifier
                        .size(6.dp)
                        .clip(CircleShape)
                        .background(if (isServiceActive) Color(0xFF4CAF50) else Color(0xFF333333))
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = if (isServiceActive) "MONITOREO ACTIVO" else "SISTEMA INACTIVO",
                    fontSize = 10.sp,
                    color = if (isServiceActive) Color(0xFF888888) else Color(0xFF333333),
                    letterSpacing = 2.sp
                )
            }

            Spacer(modifier = Modifier.height(48.dp))

            if (isServiceActive) {
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceEvenly
                ) {
                    FeatureItem("ACELEROMETRO", "Activo")
                    FeatureItem("UBICACION", "Activa")
                    FeatureItem("ALERTAS", "Activo")
                }
            }

            Spacer(modifier = Modifier.weight(1f))

            if (!isServiceActive) {
                Button(
                    onClick = { onStartService() },
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(56.dp),
                    shape = RoundedCornerShape(16.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = Color(0xFFe94560),
                        contentColor = Color.White
                    )
                ) {
                    Text(
                        text = "ACTIVAR PROTECCION",
                        fontSize = 13.sp,
                        fontWeight = FontWeight.Bold,
                        letterSpacing = 3.sp
                    )
                }
            } else {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(56.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        Box(
                            modifier = Modifier
                                .size(8.dp)
                                .clip(CircleShape)
                                .background(Color(0xFF4CAF50))
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = "PROTECCION ACTIVA - SIEMPRE ON",
                            fontSize = 12.sp,
                            fontWeight = FontWeight.Bold,
                            color = Color(0xFF4CAF50),
                            letterSpacing = 2.sp
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(16.dp))

            OutlinedButton(
                onClick = { showEducational = true },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(48.dp),
                shape = RoundedCornerShape(12.dp),
                colors = ButtonDefaults.outlinedButtonColors(
                    contentColor = Color(0xFF888888)
                )
            ) {
                Text(
                    text = "APRENDER MAS",
                    fontSize = 12.sp,
                    fontWeight = FontWeight.Medium,
                    letterSpacing = 2.sp
                )
            }

            Spacer(modifier = Modifier.height(12.dp))

            Text(
                text = "CEPRESA v2.0 - Crowdsourcing sismico",
                fontSize = 9.sp,
                color = Color(0xFF333333),
                textAlign = TextAlign.Center
            )

            Spacer(modifier = Modifier.height(24.dp))
        }
    }
}

@Composable
fun FeatureItem(title: String, status: String) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = title,
            fontSize = 9.sp,
            color = Color(0xFF666666),
            letterSpacing = 1.sp
        )
        Spacer(modifier = Modifier.height(4.dp))
        Text(
            text = status,
            fontSize = 11.sp,
            color = Color(0xFF4CAF50),
            fontWeight = FontWeight.Medium
        )
    }
}
