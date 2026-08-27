package com.example.cepresaandroid

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun EducationalScreen(onBack: () -> Unit) {
    val gray900 = Color(0xFF1A1A1A)
    val gray800 = Color(0xFF212121)
    val gray700 = Color(0xFF2D2D2D)
    val gray500 = Color(0xFF555555)
    val gray400 = Color(0xFF757575)
    val gray300 = Color(0xFF9E9E9E)
    val gray100 = Color(0xFFE0E0E0)
    val redAccent = Color(0xFFE94560)
    val orangeAccent = Color(0xFFFF9800)
    val greenAccent = Color(0xFF4CAF50)

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.verticalGradient(listOf(gray900, gray800, gray900))
            )
    ) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(20.dp)
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.padding(bottom = 24.dp)
            ) {
                TextButton(onClick = onBack) {
                    Text("< Volver", color = gray300, fontSize = 14.sp)
                }
                Spacer(modifier = Modifier.weight(1f))
                Text(
                    text = "INFORMACIÓN",
                    fontSize = 18.sp,
                    fontWeight = FontWeight.Bold,
                    color = gray100,
                    letterSpacing = 3.sp
                )
                Spacer(modifier = Modifier.weight(1f))
                Spacer(modifier = Modifier.width(80.dp))
            }

            InfoSection(symbol = "ℹ", symbolColor = redAccent, title = "¿QUÉ ES CEPRESA?",
                content = "CEPRESA es un sistema de alerta sísmica temprana basado en crowdsourcing. " +
                        "Utiliza los acelerómetros de los teléfonos para detectar vibraciones inusuales en tiempo real. " +
                        "Cuando múltiples dispositivos reportan vibraciones similares, el servidor verifica y emite la alerta.")

            Spacer(modifier = Modifier.height(14.dp))

            InfoSection(symbol = "📡", symbolColor = orangeAccent, title = "¿CÓMO FUNCIONA?",
                content = "1. Tu celular monitorea el acelerómetro constantemente\n" +
                        "2. Si detecta una vibración anormal, la reporta al servidor\n" +
                        "3. El servidor analiza reportes de múltiples usuarios\n" +
                        "4. Si hay suficientes reportes en una zona, emite la alerta\n" +
                        "5. Recibes una alerta con tiempo estimado de llegada")

            Spacer(modifier = Modifier.height(14.dp))

            InfoSection(symbol = "🛡", symbolColor = greenAccent, title = "CÓMO PROTEGERTE",
                content = "ANTES:\n" +
                        "• Identifica zonas seguras en tu hogar y trabajo\n" +
                        "• Mantén un kit de emergencia (agua, alimentos, linterna)\n" +
                        "• Asegura muebles pesados a las paredes\n\n" +
                        "DURANTE:\n" +
                        "• Agáchate, cúbrete y agárrate (DROP, COVER, HOLD ON)\n" +
                        "• Aléjate de ventanas y objetos que puedan caer\n" +
                        "• Si estás afuera, aléjate de edificios\n\n" +
                        "DESPUÉS:\n" +
                        "• Revisa si hay heridos\n" +
                        "• Verifica fugas de gas y agua\n" +
                        "• Mantente informado por radio o noticias")

            Spacer(modifier = Modifier.height(14.dp))

            InfoSection(symbol = "📊", symbolColor = redAccent, title = "ESCALA DE MAGNITUD",
                content = "M 1.0 - 2.5: No se siente\n" +
                        "M 2.5 - 3.5: Leve, pocas personas lo sienten\n" +
                        "M 3.5 - 4.5: Moderado, daño menor\n" +
                        "M 4.5 - 5.5: Fuerte, daño ligero\n" +
                        "M 5.5 - 6.5: Muy fuerte, daño significativo\n" +
                        "M 6.5 - 7.5: Severo, destrucción amplia\n" +
                        "M 7.5+: Devastador")

            Spacer(modifier = Modifier.height(14.dp))

            InfoSection(symbol = "📝", symbolColor = gray400, title = "NOTAS",
                content = "• Solo se emiten alertas para sismos de M3.5 en adelante\n" +
                        "• Para sismos menores, solo recibirás una notificación\n" +
                        "• El tiempo de alerta depende de tu distancia al epicentro\n" +
                        "• CEPRESA no reemplaza los sistemas oficiales de alerta")

            Spacer(modifier = Modifier.height(32.dp))
            Text("CEPRESA - Protegiendo vidas juntos", fontSize = 11.sp, color = gray500,
                modifier = Modifier.align(Alignment.CenterHorizontally))
            Spacer(modifier = Modifier.height(24.dp))
        }
    }
}

@Composable
fun InfoSection(symbol: String, symbolColor: Color, title: String, content: String) {
    val gray700 = Color(0xFF2D2D2D)
    val gray100 = Color(0xFFE0E0E0)
    val gray300 = Color(0xFF9E9E9E)

    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(gray700)
            .padding(16.dp)
    ) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.padding(bottom = 8.dp)
        ) {
            Text(symbol, fontSize = 18.sp, color = symbolColor)
            Spacer(modifier = Modifier.width(8.dp))
            Text(title, fontSize = 13.sp, fontWeight = FontWeight.Bold, color = gray100, letterSpacing = 1.sp)
        }
        Text(content, fontSize = 13.sp, color = gray300, lineHeight = 20.sp)
    }
}
