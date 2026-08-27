package com.example.cepresaandroid

import android.content.Context
import android.os.Build
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun PrivacyTermsScreen(onAccept: () -> Unit) {
    val context = LocalContext.current
    val scrollState = rememberScrollState()
    var accepted by remember { mutableStateOf(false) }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF0f0f1a))
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(24.dp)
                .verticalScroll(scrollState),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Spacer(modifier = Modifier.height(40.dp))

            Text(
                text = "CEPRESA",
                fontSize = 24.sp,
                fontWeight = FontWeight.Black,
                color = Color(0xFFe94560),
                letterSpacing = 6.sp
            )

            Spacer(modifier = Modifier.height(8.dp))

            Text(
                text = "Politica de Privacidad y Terminos de Uso",
                fontSize = 14.sp,
                fontWeight = FontWeight.Bold,
                color = Color(0xFFcccccc),
                textAlign = TextAlign.Center
            )

            Spacer(modifier = Modifier.height(4.dp))

            Text(
                text = "Desarrollado por JiamiauStudios",
                fontSize = 10.sp,
                color = Color(0xFF666666)
            )

            Spacer(modifier = Modifier.height(24.dp))

            // Seccion 1
            PrivacySection(
                title = "1. Informacion que Recopilamos",
                text = """CEPRESA recopila exclusivamente los siguientes datos para funcionar correctamente:

• Ubicacion GPS (latitud y longitud): Se usa para identificar tu zona geografica y enviarte alertas sismicas relevantes. Tu ubicacion se comparte con otros usuarios de forma anonima (sin nombre, email ni identificadores personales).

• Datos del acelerometro: El sensor de vibracion de tu dispositivo detecta movimientos inusuales. Solo se envia la magnitud de la vibracion, nunca se almacena ni registra tu actividad diaria.

• ID unico del dispositivo: Un identificador aleatorio (ej: android_a1b2c3d4) que NO esta vinculado a tu nombre, telefono, email ni ningun dato personal. Se usa exclusivamente para validar que multiples dispositivos reales confirmen un sismo y evitar falsas alarmas.

• Marca de tiempo: Hora exacta del reporte para la ventana de deteccion de 2 segundos.

NO recopilamos: nombre, email, telefono, contactos, fotos, archivos, historial de navegacion, IMEI, o cualquier dato de identificacion personal."""
            )

            Spacer(modifier = Modifier.height(16.dp))

            // Seccion 2
            PrivacySection(
                title = "2. Para Que Usamos Cada Permiso",
                text = """Permiso de Ubicacion (GPS):
- Para calcularte el tiempo de llegada del sismo a tu ubicacion exacta.
- Para agrupar reportes de la misma zona geografica (radio de 10km).
- Para enviarte alertas solo de sismos que afectan tu area.
- Se solicita acceso en segundo plano para protegerte aunque la app no este abierta.

Permiso de Sensores (Acelerometro):
- Para detectar vibraciones inusuales que podrian ser sismos.
- El acelerometro solo se lee 1 vez por segundo (optimizado para bateria).
- Los datos de vibracion se procesan localmente y solo se envia la magnitud al servidor.

Permiso de Notificaciones:
- Para enviarte alertas sismicas criticas con sonido y vibracion.
- Para mostrarte la pantalla de emergencia cuando se detecta un sismo.
- Las notificaciones son essenciales para tu seguridad.

Permiso de Audio:
- Para reproducir la alarma de emergencia a volumen maximo durante un sismo.
- El audio solo se reproduce cuando hay una alerta activa.

Permiso de No Molestar:
- Para silenciar automaticamente otros sonidos y priorizar la alarma de sismo.
- Para asegurar que la alarma de emergencia se escuche incluso en modo silencio.

Permiso de Bateria:
- Para que el servicio de monitoreo funcione 24/7 sin que el sistema operativo lo cierre.
- Sin este permiso, Android podria detener la proteccion para ahorrar bateria.

Permiso de Iniciar con el Dispositivo:
- Para que CEPRESA se active automaticamente cuando enciendes tu telefono.
- Asi nunca estas desprotegido despues de un reinicio."""
            )

            Spacer(modifier = Modifier.height(16.dp))

            // Seccion 3
            PrivacySection(
                title = "3. Almacenamiento y Seguridad de Datos",
                text = """• Los reportes del acelerometro se almacenan SOLO en la memoria RAM del servidor (memoria volatil).
• La memoria se limpia automaticamente cada 10 segundos.
• Los reportes tienen una ventana de vida de 2 segundos (se eliminan despues).
• NO usamos bases de datos tradicionales para los reportes en tiempo real.
• NO vendemos, compartimos ni monetizamos ningun dato.
• Tu ID unico es realmente unico: se genera localmente en tu dispositivo y nunca sale de la app.
• La comunicacion con el servidor usa cifrado HTTPS/TLS.
• El servidor esta ubicado en la nube con acceso restringido.

Resumen: CEPRESA es una herramienta de seguridad publica. Tus datos se usan UNICAMENTE para detectar sismos y protegerte. No hay fines comerciales."""
            )

            Spacer(modifier = Modifier.height(16.dp))

            // Seccion 4
            PrivacySection(
                title = "4. Comparticion de Datos",
                text = """• Tu ubicacion aproximada se muestra en el dashboard publico como un punto verde sin identificacion personal.
• Cuando reportas una vibracion, el servidor recibe: tu ID aleatorio, coordenadas y timestamp. Nada mas.
• En caso de un sismo confirmado, la alerta se envia a TODOS los usuarios sin excepcion.
• No compartimos datos con terceros, anunciantes, ni redes sociales.
• En caso de requerimiento legal, solo proporcionariamos datos si una autoridad competente lo solicita formalmente."""
            )

            Spacer(modifier = Modifier.height(16.dp))

            // Seccion 5
            PrivacySection(
                title = "5. Tus Derechos",
                text = """• Puedes desinstalar CEPRESA en cualquier momento. Al hacerlo, todos tus datos se eliminan.
• Puedes revocar permisos individualmente desde la configuracion de tu dispositivo.
• Puedes solicitar informacion sobre los datos que hemos recopilado contactandonos.
• CEPRESA no requiere registro ni cuenta de usuario.

IMPORTANTE: Si revocas permisos criticos (ubicacion, sensores, notificaciones), la proteccion sismica NO funcionara correctamente. Te recomendamos mantener todos los permisos activos para tu seguridad."""
            )

            Spacer(modifier = Modifier.height(16.dp))

            // Seccion 6
            PrivacySection(
                title = "6. Limitacion de Responsabilidad",
                text = """CEPRESA es un sistema complementario de alerta temprana. NO reemplaza a los servicios sismologicos oficiales. La precision depende del numero de usuarios activos en tu zona. JiamiauStudios no se hace responsable por danos derivados del uso o no uso de esta aplicacion. Al usar CEPRESA, confirmas que entiendes estas limitaciones."""
            )

            Spacer(modifier = Modifier.height(24.dp))

            // Checkbox
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.padding(horizontal = 8.dp)
            ) {
                Checkbox(
                    checked = accepted,
                    onCheckedChange = { accepted = it },
                    colors = CheckboxDefaults.colors(
                        checkedColor = Color(0xFFe94560),
                        uncheckedColor = Color(0xFF555555)
                    )
                )
                Spacer(modifier = Modifier.width(8.dp))
                Text(
                    text = "He leido y acepto la Politica de Privacidad y Terminos de Uso",
                    fontSize = 12.sp,
                    color = Color(0xFF888888),
                    modifier = Modifier.weight(1f)
                )
            }

            Spacer(modifier = Modifier.height(16.dp))

            // Boton Aceptar
            Button(
                onClick = {
                    savePrivacyAccepted(context)
                    onAccept()
                },
                enabled = accepted,
                modifier = Modifier
                    .fillMaxWidth()
                    .height(56.dp),
                shape = RoundedCornerShape(16.dp),
                colors = ButtonDefaults.buttonColors(
                    containerColor = if (accepted) Color(0xFFe94560) else Color(0xFF333333),
                    contentColor = Color.White,
                    disabledContainerColor = Color(0xFF333333),
                    disabledContentColor = Color(0xFF666666)
                )
            ) {
                Text(
                    text = "ACEPTAR Y CONTINUAR",
                    fontSize = 13.sp,
                    fontWeight = FontWeight.Bold,
                    letterSpacing = 3.sp
                )
            }

            Spacer(modifier = Modifier.height(12.dp))

            Text(
                text = "JiamiauStudios - Proteccion sismica para todos",
                fontSize = 9.sp,
                color = Color(0xFF333333),
                textAlign = TextAlign.Center
            )

            Spacer(modifier = Modifier.height(24.dp))
        }
    }
}

@Composable
fun PrivacySection(title: String, text: String) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(
                Color(0xFF1a1a2e),
                RoundedCornerShape(12.dp)
            )
            .padding(16.dp)
    ) {
        Text(
            text = title,
            fontSize = 14.sp,
            fontWeight = FontWeight.Bold,
            color = Color(0xFFe94560),
            modifier = Modifier.padding(bottom = 8.dp)
        )
        Text(
            text = text,
            fontSize = 11.sp,
            color = Color(0xFFaaaaaa),
            lineHeight = 16.sp
        )
    }
}

private fun savePrivacyAccepted(context: Context) {
    context.getSharedPreferences("cepresa", Context.MODE_PRIVATE)
        .edit().putBoolean("privacy_accepted", true).apply()
}

fun isPrivacyAccepted(context: Context): Boolean {
    return context.getSharedPreferences("cepresa", Context.MODE_PRIVATE)
        .getBoolean("privacy_accepted", false)
}
