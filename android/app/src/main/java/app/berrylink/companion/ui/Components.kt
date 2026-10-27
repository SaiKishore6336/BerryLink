package app.berrylink.companion.ui

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.berrylink.companion.ui.theme.BerryBlue
import app.berrylink.companion.ui.theme.BerryLight
import app.berrylink.companion.ui.theme.Coral
import app.berrylink.companion.ui.theme.Ink
import app.berrylink.companion.ui.theme.Mint
import app.berrylink.companion.ui.theme.NightSoft
import app.berrylink.companion.ui.theme.Panel
import app.berrylink.companion.ui.theme.TextMain
import app.berrylink.companion.ui.theme.TextMuted
import kotlin.random.Random

@Composable
fun StarField(modifier: Modifier = Modifier) {
    val stars = remember {
        val random = Random(17)
        List(105) {
            Triple(
                random.nextFloat(),
                random.nextFloat(),
                random.nextFloat(),
            )
        }
    }
    val transition = rememberInfiniteTransition(label = "stars")
    val twinkle by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(4200, easing = LinearEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "twinkle",
    )
    Canvas(modifier = modifier.fillMaxSize()) {
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(Color(0x2E567DE8), Color.Transparent),
                center = Offset(size.width * 0.92f, size.height * 0.10f),
                radius = size.width * 0.85f,
            ),
            radius = size.width * 0.85f,
            center = Offset(size.width * 0.92f, size.height * 0.10f),
        )
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(Color(0x2249BE9E), Color.Transparent),
                center = Offset(size.width * 0.08f, size.height * 0.82f),
                radius = size.width * 0.75f,
            ),
            radius = size.width * 0.75f,
            center = Offset(size.width * 0.08f, size.height * 0.82f),
        )
        stars.forEachIndexed { index, star ->
            val base = 0.18f + star.third * 0.42f
            val alpha = (base * (0.62f + 0.38f * sinF((twinkle * 2f * PI_F + star.third * 8f)))).coerceIn(0.05f, 0.72f)
            val radius = (0.55f + star.third * 1.15f).dp.toPx()
            val color = when (index % 17) {
                0 -> Color(0xFFBBD2FF)
                5 -> Color(0xFFFFE0A6)
                else -> Color.White
            }
            drawCircle(
                color = color.copy(alpha = alpha),
                radius = radius,
                center = Offset(star.first * size.width, star.second * size.height),
            )
            if (index % 23 == 0) {
                drawLine(
                    color = color.copy(alpha = alpha * 0.65f),
                    start = Offset(star.first * size.width - radius * 2.4f, star.second * size.height),
                    end = Offset(star.first * size.width + radius * 2.4f, star.second * size.height),
                    strokeWidth = 0.7.dp.toPx(),
                )
            }
        }
    }
}

@Composable
fun GlassCard(
    modifier: Modifier = Modifier,
    padding: Dp = 18.dp,
    content: @Composable () -> Unit,
) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(24.dp),
        color = Panel.copy(alpha = 0.68f),
        border = BorderStroke(1.dp, Color.White.copy(alpha = 0.075f)),
        tonalElevation = 0.dp,
        shadowElevation = 0.dp,
    ) {
        Box(Modifier.padding(padding)) { content() }
    }
}

@Composable
fun StatusPill(
    text: String,
    color: Color,
    modifier: Modifier = Modifier,
) {
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(50),
        color = color.copy(alpha = 0.13f),
        border = BorderStroke(1.dp, color.copy(alpha = 0.28f)),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 11.dp, vertical = 7.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(7.dp),
        ) {
            Box(
                Modifier
                    .size(7.dp)
                    .background(color, CircleShape),
            )
            Text(
                text = text,
                style = MaterialTheme.typography.labelMedium,
                color = color,
                maxLines = 1,
            )
        }
    }
}

@Composable
fun SpeechBubble(
    text: String,
    provider: String?,
    notice: String?,
    isError: Boolean,
    isThinking: Boolean,
    modifier: Modifier = Modifier,
) {
    val accent = if (isError) Coral else if (isThinking) Color(0xFFFFD37A) else BerryLight
    val providerLabel = when (provider) {
        "mock" -> "LOCAL MOCK"
        "gemini" -> "GEMINI FREE TIER"
        null -> null
        else -> provider.uppercase()
    }
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Surface(
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(24.dp),
            color = Panel.copy(alpha = 0.94f),
            border = BorderStroke(1.dp, accent.copy(alpha = 0.24f)),
            shadowElevation = 0.dp,
        ) {
            Column(
                modifier = Modifier.padding(horizontal = 18.dp, vertical = 14.dp),
                verticalArrangement = Arrangement.spacedBy(7.dp),
            ) {
                if (isThinking) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        ThinkingDots()
                        Text(
                            text = "Thinking it over…",
                            style = MaterialTheme.typography.bodyMedium,
                            color = TextMuted,
                        )
                    }
                } else {
                    Text(
                        text = text,
                        style = MaterialTheme.typography.bodyLarge,
                        color = if (isError) Color(0xFFFFC9D1) else TextMain,
                        maxLines = 7,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                if (!notice.isNullOrBlank()) {
                    Text(
                        text = notice,
                        style = MaterialTheme.typography.bodySmall,
                        color = if (providerLabel == "LOCAL MOCK") Color(0xFFFFD890) else TextMuted,
                        maxLines = 4,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                if (providerLabel != null) {
                    Surface(
                        shape = RoundedCornerShape(50),
                        color = accent.copy(alpha = 0.12f),
                    ) {
                        Text(
                            text = providerLabel,
                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                            style = MaterialTheme.typography.labelSmall.copy(
                                fontWeight = FontWeight.SemiBold,
                                letterSpacing = 0.8.sp,
                            ),
                            color = accent,
                        )
                    }
                }
            }
        }
        Canvas(
            modifier = Modifier
                .width(24.dp)
                .height(10.dp),
        ) {
            val path = Path().apply {
                moveTo(0f, 0f)
                lineTo(size.width, 0f)
                lineTo(size.width * 0.5f, size.height)
                close()
            }
            drawPath(path, Panel.copy(alpha = 0.94f))
        }
    }
}

@Composable
internal fun ThinkingDots() {
    val transition = rememberInfiniteTransition(label = "thinking-dots")
    val phase by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(900, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "dot-phase",
    )
    Row(horizontalArrangement = Arrangement.spacedBy(3.dp)) {
        repeat(3) { index ->
            val pulse = (sinF((phase * 2f * PI_F) - index * 1.25f) + 1f) / 2f
            Box(
                Modifier
                    .size(5.dp)
                    .background(
                        color = Color(0xFFFFD37A).copy(alpha = 0.35f + pulse * 0.65f),
                        shape = CircleShape,
                    ),
            )
        }
    }
}

@Composable
fun HoldToTalkButton(
    recording: Boolean,
    enabled: Boolean,
    level: Float,
    modifier: Modifier = Modifier,
    onStart: () -> Unit,
    onRelease: () -> Unit,
    onCancel: () -> Unit,
) {
    val currentStart by rememberUpdatedState(onStart)
    val currentRelease by rememberUpdatedState(onRelease)
    val currentCancel by rememberUpdatedState(onCancel)
    val transition = rememberInfiniteTransition(label = "talk-pulse")
    val pulse by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(1150, easing = LinearEasing),
            repeatMode = RepeatMode.Restart,
        ),
        label = "talk-pulse-value",
    )
    val accent = when {
        recording -> Coral
        !enabled -> Color(0xFF5D6885)
        else -> Mint
    }

    Box(
        modifier = modifier
            .size(132.dp)
            .semantics {
                role = Role.Button
                contentDescription = if (recording) {
                    "Recording. Release to send."
                } else {
                    "Hold to talk to BerryLink"
                }
            }
            .pointerInput(enabled) {
                if (!enabled) return@pointerInput
                detectTapGestures(
                    onPress = {
                        currentStart()
                        val completed = tryAwaitRelease()
                        if (completed) currentRelease() else currentCancel()
                    },
                )
            },
        contentAlignment = Alignment.Center,
    ) {
        Canvas(Modifier.fillMaxSize()) {
            val center = Offset(size.width / 2f, size.height / 2f)
            val baseRadius = size.minDimension * 0.39f
            if (recording) {
                repeat(3) { index ->
                    val wave = (pulse + index * 0.27f) % 1f
                    drawCircle(
                        color = Coral.copy(alpha = (1f - wave) * 0.22f),
                        radius = baseRadius * (1.05f + wave * 0.45f),
                        center = center,
                        style = Stroke(width = 1.5.dp.toPx()),
                    )
                }
            }
            drawCircle(
                color = accent.copy(alpha = if (enabled) 0.13f else 0.06f),
                radius = baseRadius * 1.16f,
                center = center,
                style = Stroke(width = 1.dp.toPx()),
            )
            drawCircle(
                color = accent.copy(alpha = if (enabled) 0.30f else 0.12f),
                radius = baseRadius * 1.03f,
                center = center,
                style = Stroke(width = 1.4.dp.toPx()),
            )
            drawArc(
                color = accent.copy(alpha = if (enabled) 0.85f else 0.25f),
                startAngle = -90f,
                sweepAngle = if (recording) 18f + level.coerceIn(0f, 1f) * 324f else 290f,
                useCenter = false,
                topLeft = Offset(center.x - baseRadius * 1.09f, center.y - baseRadius * 1.09f),
                size = Size(baseRadius * 2.18f, baseRadius * 2.18f),
                style = Stroke(width = 3.2.dp.toPx(), cap = StrokeCap.Round),
            )
        }
        Box(
            modifier = Modifier
                .size(96.dp)
                .background(
                    brush = Brush.radialGradient(
                        colors = if (recording) {
                            listOf(Color(0xFFFF9CAE), Coral, Color(0xFFC63C57))
                        } else if (enabled) {
                            listOf(Color(0xFF8EA7FF), BerryBlue, Color(0xFF3E58C9))
                        } else {
                            listOf(Color(0xFF38425F), Color(0xFF242C43))
                        },
                        center = Offset(96f * 0.34f, 96f * 0.28f),
                        radius = 96f,
                    ),
                    shape = CircleShape,
                ),
            contentAlignment = Alignment.Center,
        ) {
            MicGlyph(
                modifier = Modifier.size(34.dp),
                color = if (enabled) Color(0xFFF7FAFF) else Color(0xFF7C87A5),
            )
        }
    }
}

@Composable
fun MicGlyph(modifier: Modifier = Modifier, color: Color = TextMain) {
    Canvas(modifier) {
        val w = size.width
        val h = size.height
        drawRoundRect(
            color = color,
            topLeft = Offset(w * 0.35f, h * 0.08f),
            size = Size(w * 0.30f, h * 0.50f),
            cornerRadius = androidx.compose.ui.geometry.CornerRadius(w * 0.15f, w * 0.15f),
        )
        drawArc(
            color = color,
            startAngle = 0f,
            sweepAngle = 180f,
            useCenter = false,
            topLeft = Offset(w * 0.21f, h * 0.32f),
            size = Size(w * 0.58f, h * 0.38f),
            style = Stroke(width = w * 0.075f, cap = StrokeCap.Round),
        )
        drawLine(
            color = color,
            start = Offset(w * 0.5f, h * 0.70f),
            end = Offset(w * 0.5f, h * 0.84f),
            strokeWidth = w * 0.075f,
            cap = StrokeCap.Round,
        )
        drawLine(
            color = color,
            start = Offset(w * 0.34f, h * 0.87f),
            end = Offset(w * 0.66f, h * 0.87f),
            strokeWidth = w * 0.075f,
            cap = StrokeCap.Round,
        )
    }
}

@Composable
fun MiniBerryMark(modifier: Modifier = Modifier, size: Dp = 38.dp) {
    Canvas(modifier.size(size)) {
        val w = this.size.width
        val h = this.size.height
        val top = h * 0.22f
        val body = Path().apply {
            moveTo(-w * 0.04f, h)
            cubicTo(-w * 0.06f, h * 0.54f, w * 0.20f, top, w * 0.5f, top)
            cubicTo(w * 0.80f, top, w * 1.06f, h * 0.54f, w * 1.04f, h)
            close()
        }
        drawPath(
            body,
            brush = Brush.linearGradient(
                colors = listOf(
                    Color(0xFFA9BCFF),
                    Color(0xFF6C86F5),
                    Color(0xFF4254D6),
                    Color(0xFF2B2F8F),
                ),
                start = Offset(w * 0.22f, top),
                end = Offset(w * 0.8f, h),
            ),
        )
        drawPath(
            starPath(
                center = Offset(w * 0.5f, top + h * 0.03f),
                outer = w * 0.105f,
                inner = w * 0.05f,
                rotation = -0.06f,
            ),
            color = Color(0xFF1C1F66),
        )
        listOf(-1f, 1f).forEach { side ->
            val cx = w * 0.5f + side * w * 0.18f
            val cy = h * 0.55f
            drawOval(
                color = Color(0xFFF9FBFF),
                topLeft = Offset(cx - w * 0.125f, cy - h * 0.16f),
                size = Size(w * 0.25f, h * 0.32f),
            )
            drawCircle(
                color = Ink,
                radius = w * 0.062f,
                center = Offset(cx + w * 0.012f, cy + h * 0.04f),
            )
            drawCircle(
                color = Color.White,
                radius = w * 0.018f,
                center = Offset(cx - w * 0.005f, cy + h * 0.015f),
            )
            drawLine(
                color = Color(0xFF1C1F66),
                start = Offset(cx - w * 0.10f, cy - h * 0.10f),
                end = Offset(cx + w * 0.10f, cy - h * 0.10f),
                strokeWidth = w * 0.018f,
                cap = StrokeCap.Round,
            )
        }
    }
}

@Composable
fun Caption(text: String, modifier: Modifier = Modifier, color: Color = TextMuted) {
    Text(
        text = text,
        modifier = modifier,
        style = MaterialTheme.typography.labelSmall.copy(letterSpacing = 0.8.sp),
        color = color,
        textAlign = TextAlign.Center,
    )
}

@Composable
fun TinyStatusDot(color: Color, modifier: Modifier = Modifier) {
    Box(
        modifier
            .size(6.dp)
            .background(color, CircleShape),
    )
}
