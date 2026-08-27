package com.example.cepresaandroid.ui.theme

import android.app.Activity
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat

private val DarkGrayColorScheme = darkColorScheme(
    primary = Gray200,
    secondary = Gray400,
    tertiary = Gray300,
    background = Gray900,
    surface = Gray800,
    onPrimary = Gray900,
    onSecondary = Gray50,
    onTertiary = Gray50,
    onBackground = Gray100,
    onSurface = Gray100,
    surfaceVariant = Gray700,
    onSurfaceVariant = Gray300,
    outline = Gray500
)

@Composable
fun CepresaTheme(
    content: @Composable () -> Unit
) {
    val colorScheme = DarkGrayColorScheme
    val view = LocalView.current

    if (!view.isInEditMode) {
        SideEffect {
            val window = (view.context as Activity).window
            window.statusBarColor = Gray900.toArgb()
            window.navigationBarColor = Gray900.toArgb()
            WindowCompat.getInsetsController(window, view).isAppearanceLightStatusBars = false
        }
    }

    MaterialTheme(
        colorScheme = colorScheme,
        typography = Typography,
        content = content
    )
}
