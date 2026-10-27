package app.berrylink.companion.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.sp
import app.berrylink.companion.R

val Night = Color(0xFF070A18)
val NightDeep = Color(0xFF040611)
val NightSoft = Color(0xFF10162E)
val Panel = Color(0xFF151C38)
val BerryBlue = Color(0xFF6F8FF5)
val BerryLight = Color(0xFFA9BCFF)
val BerryDeep = Color(0xFF334CBE)
val Mint = Color(0xFF58D6A6)
val Butter = Color(0xFFFFCF70)
val Coral = Color(0xFFFF758B)
val Lavender = Color(0xFFC4A2FF)
val Ink = Color(0xFF0D1539)
val TextMain = Color(0xFFF1F5FF)
val TextMuted = Color(0xFF9DAAD0)

val Fredoka = FontFamily(Font(R.font.fredoka, FontWeight.Normal))
val IbmPlex = FontFamily(Font(R.font.ibm_plex_sans, FontWeight.Normal))

private val BerryColors = darkColorScheme(
    primary = BerryBlue,
    onPrimary = Color.White,
    primaryContainer = BerryDeep,
    onPrimaryContainer = BerryLight,
    secondary = Mint,
    onSecondary = Ink,
    tertiary = Butter,
    background = Night,
    onBackground = TextMain,
    surface = Panel,
    onSurface = TextMain,
    surfaceVariant = NightSoft,
    onSurfaceVariant = TextMuted,
    outline = Color(0xFF354066),
    error = Coral,
    onError = Ink,
)

private val BerryTypography = Typography(
    displayLarge = TextStyle(
        fontFamily = Fredoka,
        fontWeight = FontWeight.Normal,
        fontSize = 54.sp,
        lineHeight = 58.sp,
        letterSpacing = (-0.5).sp,
    ),
    displayMedium = TextStyle(
        fontFamily = Fredoka,
        fontWeight = FontWeight.Normal,
        fontSize = 40.sp,
        lineHeight = 44.sp,
    ),
    headlineLarge = TextStyle(
        fontFamily = Fredoka,
        fontWeight = FontWeight.Normal,
        fontSize = 30.sp,
        lineHeight = 34.sp,
    ),
    headlineMedium = TextStyle(
        fontFamily = Fredoka,
        fontWeight = FontWeight.Normal,
        fontSize = 24.sp,
        lineHeight = 29.sp,
    ),
    titleLarge = TextStyle(
        fontFamily = Fredoka,
        fontWeight = FontWeight.Normal,
        fontSize = 21.sp,
        lineHeight = 26.sp,
    ),
    titleMedium = TextStyle(
        fontFamily = IbmPlex,
        fontWeight = FontWeight.SemiBold,
        fontSize = 16.sp,
        lineHeight = 21.sp,
    ),
    bodyLarge = TextStyle(
        fontFamily = IbmPlex,
        fontWeight = FontWeight.Normal,
        fontSize = 16.sp,
        lineHeight = 23.sp,
    ),
    bodyMedium = TextStyle(
        fontFamily = IbmPlex,
        fontWeight = FontWeight.Normal,
        fontSize = 14.sp,
        lineHeight = 20.sp,
    ),
    bodySmall = TextStyle(
        fontFamily = IbmPlex,
        fontWeight = FontWeight.Normal,
        fontSize = 12.sp,
        lineHeight = 17.sp,
    ),
    labelLarge = TextStyle(
        fontFamily = IbmPlex,
        fontWeight = FontWeight.SemiBold,
        fontSize = 14.sp,
        lineHeight = 18.sp,
        letterSpacing = 0.1.sp,
    ),
    labelMedium = TextStyle(
        fontFamily = IbmPlex,
        fontWeight = FontWeight.Medium,
        fontSize = 12.sp,
        lineHeight = 16.sp,
        letterSpacing = 0.2.sp,
    ),
    labelSmall = TextStyle(
        fontFamily = IbmPlex,
        fontWeight = FontWeight.Medium,
        fontSize = 10.sp,
        lineHeight = 14.sp,
        letterSpacing = 0.5.sp,
    ),
)

@Composable
fun BerryLinkTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = BerryColors,
        typography = BerryTypography,
        content = content,
    )
}
