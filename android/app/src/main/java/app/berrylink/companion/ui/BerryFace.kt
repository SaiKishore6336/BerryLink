package app.berrylink.companion.ui

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.runtime.withFrameNanos
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.graphics.drawscope.rotate
import androidx.compose.ui.graphics.drawscope.translate
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import app.berrylink.companion.model.BerryActivity
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt
import kotlin.random.Random

/**
 * The phone-side berry, drawn after the supplied Bluey reference: a true
 * semicircle (a flat floor plus a half-circle dome) that fills the lower
 * screen, a navy star on the forehead, heavy friendly eyelids, two very large
 * eyes, soft cheeks and a tiny mouth.
 *
 * His gaze is intentionally independent of the PC mouse. It drifts while idle,
 * looks up when thinking, and follows a finger touching the face; it never
 * follows the Kali cursor.
 */
@Composable
fun BerryFace(
    activity: BerryActivity,
    level: Float,
    modifier: Modifier = Modifier,
    gazeTarget: Offset? = null,
) {
    val transition = rememberInfiniteTransition(label = "berry-face")
    val breathe by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(2600, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "breathe",
    )
    val sparkle by transition.animateFloat(
        initialValue = 0f,
        targetValue = 1f,
        animationSpec = infiniteRepeatable(
            animation = tween(1600, easing = FastOutSlowInEasing),
            repeatMode = RepeatMode.Reverse,
        ),
        label = "sparkle",
    )
    // Live motion state. The face is never a still image: a frame loop runs
    // saccades, blinks (including occasional double blinks), a springy idle
    // hop, pupil dilation, brow lifts, and a small head lean toward the gaze.
    var gazeX by remember { mutableFloatStateOf(0f) }
    var gazeY by remember { mutableFloatStateOf(0f) }
    var eyelid by remember { mutableFloatStateOf(0.27f) }
    var pupilScale by remember { mutableFloatStateOf(1f) }
    var browAmount by remember { mutableFloatStateOf(0.2f) }
    var hop by remember { mutableFloatStateOf(0f) }
    val latestActivity by rememberUpdatedState(activity)
    val latestGaze by rememberUpdatedState(gazeTarget)

    LaunchedEffect(Unit) {
        var lastNanos = 0L
        var time = 0f
        var targetX = 0f
        var targetY = 0f
        var jitterX = 0f
        var jitterY = 0f
        var nextSaccade = 0.4f
        var nextJitter = 0.7f
        var nextBlink = 2.6f
        var blinkStart = -100f
        var doubleBlink = false
        var nextHop = 7f
        var hopPosition = 0f
        var hopVelocity = 0f
        var lastMood = latestActivity
        var pupilTarget = 1f
        var browTarget = 0.2f

        while (true) {
            withFrameNanos { nanos ->
                if (lastNanos == 0L) lastNanos = nanos
                val dt = ((nanos - lastNanos) / 1_000_000_000.0)
                    .toFloat()
                    .coerceIn(0.001f, 0.05f)
                lastNanos = nanos
                time += dt
                val mood = latestActivity
                val baseLid = when (mood) {
                    BerryActivity.LISTENING -> 0.075f
                    BerryActivity.THINKING -> 0.31f
                    BerryActivity.SPEAKING -> 0.13f
                    BerryActivity.ERROR -> 0.24f
                    BerryActivity.HAPPY -> 1f
                    BerryActivity.SLEEPING -> 1f
                    BerryActivity.IDLE -> 0.27f
                }

                if (mood != lastMood) {
                    // Blink and give a tiny surprised hop on every mood change.
                    blinkStart = time
                    doubleBlink = false
                    if (mood != BerryActivity.IDLE && mood != BerryActivity.SLEEPING) hopVelocity += 95f
                    if (mood == BerryActivity.SLEEPING) nextHop = time + 1e9f
                    lastMood = mood
                }
                if (mood != BerryActivity.SLEEPING && nextHop > 1e8f) {
                    // Woken up: re-arm the idle hop timer.
                    nextHop = time + 3f
                }

                when (mood) {
                    BerryActivity.THINKING -> {
                        targetX = 0.60f + 0.07f * sinF(time * 1.25f)
                        targetY = -0.78f
                    }
                    BerryActivity.LISTENING -> {
                        targetX = 0.02f
                        targetY = -0.12f
                    }
                    BerryActivity.ERROR -> {
                        targetX = -0.48f
                        targetY = 0.10f
                    }
                    BerryActivity.HAPPY -> {
                        targetX = 0.10f
                        targetY = 0.12f
                    }
                    BerryActivity.SLEEPING -> {
                        // Eyes are drawn shut; a tiny drift keeps the frame alive.
                        targetX = 0.03f + 0.02f * sinF(time * 0.6f)
                        targetY = 0.05f
                    }
                    BerryActivity.SPEAKING -> {
                        if (time > nextSaccade) {
                            targetX = Random.nextFloat() * 0.55f - 0.18f
                            targetY = Random.nextFloat() * 0.34f - 0.12f
                            nextSaccade = time + Random.nextFloat() * 1.8f + 0.55f
                        }
                    }
                    BerryActivity.IDLE -> {
                        if (time > nextSaccade) {
                            targetX = Random.nextFloat() * 1.55f - 0.78f
                            targetY = Random.nextFloat() * 0.85f - 0.48f
                            nextSaccade = time + Random.nextFloat() * 1.8f + 0.65f
                        }
                    }
                }

                // A finger on the face gently pulls both eyes toward it.  This is
                // interactive rather than just a looping animation.
                val pointed = latestGaze
                if (pointed != null && mood != BerryActivity.SLEEPING) {
                    targetX = pointed.x.coerceIn(-1f, 1f) * 0.95f
                    targetY = pointed.y.coerceIn(-1f, 1f) * 0.72f
                }

                if (time > nextJitter) {
                    val amount = when (mood) {
                        BerryActivity.SPEAKING -> 0.065f
                        BerryActivity.THINKING -> 0.045f
                        BerryActivity.LISTENING -> 0.012f
                        BerryActivity.HAPPY -> 0.03f
                        BerryActivity.SLEEPING -> 0.006f
                        BerryActivity.ERROR -> 0.02f
                        BerryActivity.IDLE -> 0.022f
                    }
                    jitterX = (Random.nextFloat() * 2f - 1f) * amount
                    jitterY = (Random.nextFloat() * 2f - 1f) * amount
                    nextJitter = time + Random.nextFloat() * 1.1f + 0.45f
                }

                // Critically damped-ish eye spring; the eyes glance instead of sliding.
                val eyeEase = 1f - exp(-dt * 16f)
                gazeX += (targetX + jitterX - gazeX) * eyeEase
                gazeY += (targetY + jitterY - gazeY) * eyeEase

                pupilTarget = when (mood) {
                    BerryActivity.LISTENING -> 1.13f
                    BerryActivity.HAPPY -> 1.18f
                    BerryActivity.SLEEPING -> 1f
                    BerryActivity.THINKING -> 0.94f
                    BerryActivity.ERROR -> 0.92f
                    BerryActivity.SPEAKING -> 1.05f
                    BerryActivity.IDLE -> 1f
                }
                pupilScale += (pupilTarget - pupilScale) * (1f - exp(-dt * 8f))

                browTarget = when (mood) {
                    BerryActivity.LISTENING -> 1f
                    BerryActivity.HAPPY -> 0.92f
                    BerryActivity.SLEEPING -> 0.12f
                    BerryActivity.THINKING -> 0.55f
                    BerryActivity.SPEAKING -> 0.38f
                    BerryActivity.ERROR -> 0.08f
                    BerryActivity.IDLE -> 0.2f
                }
                browAmount += (browTarget - browAmount) * (1f - exp(-dt * 7f))

                if (time > nextBlink) {
                    blinkStart = time
                    doubleBlink = Random.nextFloat() < 0.24f
                    nextBlink = time + Random.nextFloat() * 3.2f + 2.3f
                }
                val p = (time - blinkStart) / 0.155f
                var closed = if (p in 0f..1f) sinF(PI_F * p) else 0f
                if (doubleBlink && p in 1.32f..2.32f) {
                    closed = max(closed, sinF(PI_F * (p - 1.32f)))
                }
                eyelid += (max(baseLid, closed) - eyelid) * (1f - exp(-dt * 30f))

                if (time > nextHop) {
                    val hopMuted = mood == BerryActivity.LISTENING || mood == BerryActivity.SLEEPING
                    if (hopPosition > -1f && !hopMuted) {
                        hopVelocity += Random.nextFloat() * 120f + 165f
                    }
                    nextHop = time + Random.nextFloat() * 7f + 7f
                }
                // Small springy hop, anchored so the face settles back down.
                val damping = 2f * sqrt(300f) * 0.34f
                hopVelocity += (300f * (0f - hopPosition) - damping * hopVelocity) * dt
                hopPosition += hopVelocity * dt
                if (hopPosition < -3f) {
                    hopPosition = -3f
                    hopVelocity = 0f
                }
                hop = hopPosition
            }
        }
    }

    val happy = activity == BerryActivity.HAPPY
    val sleeping = activity == BerryActivity.SLEEPING

    val description = when (activity) {
        BerryActivity.IDLE -> "BerryLink berry is awake"
        BerryActivity.LISTENING -> "BerryLink berry is listening"
        BerryActivity.THINKING -> "BerryLink berry is thinking"
        BerryActivity.SPEAKING -> "BerryLink berry is speaking"
        BerryActivity.HAPPY -> "BerryLink berry is happy"
        BerryActivity.SLEEPING -> "BerryLink berry is asleep. Tap him to wake him up."
        BerryActivity.ERROR -> "BerryLink berry looks concerned"
    }

    Canvas(modifier = modifier.semantics { contentDescription = description }) {
        val w = size.width
        val h = size.height
        if (w < 40f || h < 40f) return@Canvas

        val speaking = activity == BerryActivity.SPEAKING
        val listening = activity == BerryActivity.LISTENING
        val thinking = activity == BerryActivity.THINKING
        val error = activity == BerryActivity.ERROR
        val talk = when {
            speaking -> 0.56f + 0.44f * sinF(breathe * PI_F)
            listening -> level.coerceIn(0f, 1f) * 0.28f
            else -> 0f
        }
        val bounce = -talk * w * 0.016f + sinF(breathe * PI_F) * w * 0.004f
        // --- True semicircle geometry -----------------------------------------
        // The body is a half disc: a flat floor across the bottom edge and a
        // half-circle arc above it. Width drives the radius so the shape is an
        // exact circle, never an ellipse; the radius is clamped for the rare
        // wide aspect where the canvas is shorter than the dome.
        val radius = min(w * 0.5f, h)
        val domeTop = h - radius               // apex of the half-circle
        val eyeY = h - radius * 0.62f
        val eyeDX = radius * 0.37f
        val eyeW = radius * 0.45f
        val eyeH = min(w * 0.285f, radius * 0.60f)
        val navy = Color(0xFF1C1F66)
        val ink = Color(0xFF17151F)
        val bodyBrush = Brush.linearGradient(
            colors = listOf(
                Color(0xFFA9BCFF),
                Color(0xFF6C86F5),
                Color(0xFF4254D6),
                Color(0xFF2B2F8F),
            ),
            start = Offset(w * 0.24f, domeTop + radius * 0.08f),
            end = Offset(w * 0.78f, h),
        )

        // A quiet blue halo separates the berry from the night sky.
        drawCircle(
            brush = Brush.radialGradient(
                colors = listOf(Color(0x3F6C86F5), Color(0x146C86F5), Color.Transparent),
                center = Offset(w * 0.5f, h - radius * 0.5f),
                radius = w * 0.82f,
            ),
            radius = w * 0.82f,
            center = Offset(w * 0.5f, h - radius * 0.5f),
        )

        translate(top = bounce - hop) {
            rotate(degrees = -gazeX * 2.2f, pivot = Offset(w * 0.5f, h * 0.95f)) {
            // Flat floor across the bottom, then a perfect half-circle over the
            // top. The arc's bounding rect is square (2R x 2R) and centred on
            // the floor line, so a 180° sweep is a true circle, not an ellipse.
            val body = Path().apply {
                arcTo(
                    rect = Rect(
                        left = w * 0.5f - radius,
                        top = h - radius,
                        right = w * 0.5f + radius,
                        bottom = h + radius,
                    ),
                    startAngleDegrees = 180f,
                    sweepAngleDegrees = 180f,
                    forceMoveTo = true,
                )
                close()
            }

            // A slightly larger silhouette creates the soft glow at the rim.
            val glowRadius = radius + w * 0.022f
            val glow = Path().apply {
                arcTo(
                    rect = Rect(
                        left = w * 0.5f - glowRadius,
                        top = h - glowRadius,
                        right = w * 0.5f + glowRadius,
                        bottom = h + glowRadius,
                    ),
                    startAngleDegrees = 180f,
                    sweepAngleDegrees = 180f,
                    forceMoveTo = true,
                )
                close()
            }
            drawPath(glow, Color(0x386C86F5))

            drawPath(body, brush = bodyBrush)

            clipPath(body) {
                // broad, very soft shine from the upper left
                drawCircle(
                    brush = Brush.radialGradient(
                        colors = listOf(Color(0x66FFFFFF), Color(0x22FFFFFF), Color.Transparent),
                        center = Offset(w * 0.26f, domeTop + radius * 0.30f),
                        radius = w * 0.44f,
                    ),
                    radius = w * 0.44f,
                    center = Offset(w * 0.26f, domeTop + radius * 0.30f),
                )
                // small glossy berry highlight
                drawOval(
                    color = Color(0x55FFFFFF),
                    topLeft = Offset(w * 0.245f, domeTop + radius * 0.115f),
                    size = Size(w * 0.13f, w * 0.038f),
                )
                drawOval(
                    color = Color(0x28FFFFFF),
                    topLeft = Offset(w * 0.225f, domeTop + radius * 0.225f),
                    size = Size(w * 0.075f, w * 0.024f),
                )
            }

            // Five-point blueberry crown, sitting on the apex of the dome.
            val starCenter = Offset(w * 0.5f, domeTop + w * 0.030f)
            drawPath(
                starPath(
                    center = starCenter,
                    outer = w * 0.047f,
                    inner = w * 0.022f,
                    rotation = -0.06f,
                ),
                color = navy,
            )

            // Blush, softer than a flat circle thanks to a radial falloff.
            val blushStrength = when {
                happy -> 0.75f
                listening -> 0.55f
                speaking -> 0.38f
                else -> 0.27f
            }
            listOf(-1f, 1f).forEach { side ->
                val blushCenter = Offset(w * (0.5f + side * 0.305f), h - radius * 0.34f)
                drawOval(
                    brush = Brush.radialGradient(
                        colors = listOf(
                            Color(0xFFF3A6D8).copy(alpha = blushStrength),
                            Color(0x00F3A6D8),
                        ),
                        center = blushCenter,
                        radius = w * 0.115f,
                    ),
                    topLeft = Offset(blushCenter.x - w * 0.12f, blushCenter.y - w * 0.056f),
                    size = Size(w * 0.24f, w * 0.112f),
                )
            }

            if (happy) {
                // The reference's happy face: two closed, upward-curving eyes.
                listOf(-1f, 1f).forEach { side ->
                    val cx = w * 0.5f + side * eyeDX
                    val arc = Path().apply {
                        moveTo(cx - eyeW * 0.51f, eyeY + eyeH * 0.13f)
                        quadraticBezierTo(
                            cx,
                            eyeY - eyeH * 0.36f,
                            cx + eyeW * 0.51f,
                            eyeY + eyeH * 0.13f,
                        )
                    }
                    drawPath(
                        arc,
                        color = ink,
                        style = Stroke(width = eyeW * 0.13f, cap = StrokeCap.Round),
                    )
                }
            } else if (sleeping) {
                // Napping: two soft downward lid curves, no whites, no pupils.
                listOf(-1f, 1f).forEach { side ->
                    val cx = w * 0.5f + side * eyeDX
                    val shut = Path().apply {
                        moveTo(cx - eyeW * 0.47f, eyeY + eyeH * 0.02f)
                        quadraticBezierTo(
                            cx,
                            eyeY + eyeH * 0.17f,
                            cx + eyeW * 0.47f,
                            eyeY + eyeH * 0.02f,
                        )
                    }
                    drawPath(
                        shut,
                        color = ink,
                        style = Stroke(width = eyeW * 0.115f, cap = StrokeCap.Round),
                    )
                }
                // Three gentle Zzz glyphs drifting up and fading out.
                repeat(3) { index ->
                    val phase = (sparkle + index * 0.33f) % 1f
                    val alpha = (0.62f * sinF(PI_F * phase)).coerceIn(0f, 0.62f)
                    if (alpha > 0.02f) {
                        val size = w * (0.030f + index * 0.011f)
                        val zx = w * (0.80f + index * 0.062f)
                        val zy = domeTop - w * (0.012f + phase * (0.085f + index * 0.020f)) +
                            sinF(sparkle * PI_F * 2f + index) * w * 0.006f
                        val zzz = Path().apply {
                            moveTo(zx - size * 0.5f, zy - size * 0.5f)
                            lineTo(zx + size * 0.5f, zy - size * 0.5f)
                            lineTo(zx - size * 0.5f, zy + size * 0.5f)
                            lineTo(zx + size * 0.5f, zy + size * 0.5f)
                        }
                        drawPath(
                            zzz,
                            color = Color(0xFFBFD3FF).copy(alpha = alpha),
                            style = Stroke(width = w * 0.008f, cap = StrokeCap.Round),
                        )
                    }
                }
            } else {
                listOf(-1f, 1f).forEach { side ->
                    val cx = w * 0.5f + side * eyeDX
                    val squash = 1f - talk * 0.08f
                    val drawnEyeH = eyeH * squash
                    val top = eyeY - drawnEyeH / 2f
                    val eyePath = Path().apply {
                        addOval(
                            Rect(
                                left = cx - eyeW / 2f,
                                top = top,
                                right = cx + eyeW / 2f,
                                bottom = top + drawnEyeH,
                            ),
                        )
                    }
                    val lidFraction = eyelid.coerceIn(0f, 1f)
                    if (lidFraction > 0.82f) {
                        // A blink is just a soft lash line.
                        val shut = Path().apply {
                            moveTo(cx - eyeW * 0.47f, eyeY + eyeH * 0.06f)
                            quadraticBezierTo(
                                cx,
                                eyeY + eyeH * 0.19f,
                                cx + eyeW * 0.47f,
                                eyeY + eyeH * 0.06f,
                            )
                        }
                        drawPath(
                            shut,
                            color = ink,
                            style = Stroke(width = eyeW * 0.10f, cap = StrokeCap.Round),
                        )
                    } else {
                        drawPath(eyePath, Color(0xFFF9FBFF))
                        clipPath(eyePath) {
                            val pupilRadius = eyeW * 0.265f * pupilScale
                            val pupilX = cx + gazeX * eyeW * 0.17f + side * eyeW * 0.014f
                            val pupilY = eyeY + drawnEyeH * 0.055f + gazeY * drawnEyeH * 0.16f
                            drawCircle(
                                color = ink,
                                radius = pupilRadius,
                                center = Offset(pupilX, pupilY),
                            )
                            drawCircle(
                                color = Color(0xFFFFFFFF),
                                radius = pupilRadius * 0.36f,
                                center = Offset(
                                    pupilX - pupilRadius * 0.38f,
                                    pupilY - pupilRadius * 0.45f,
                                ),
                            )
                            drawCircle(
                                color = Color(0xD9FFFFFF),
                                radius = pupilRadius * 0.16f,
                                center = Offset(
                                    pupilX + pupilRadius * 0.38f,
                                    pupilY + pupilRadius * 0.34f,
                                ),
                            )

                            // Heavy upper lid: the same skin gradient is painted
                            // over the top of the white, exactly like the reference.
                            val lidHeight = drawnEyeH * lidFraction
                            if (lidHeight > 0.5f) {
                                drawRect(
                                    brush = bodyBrush,
                                    topLeft = Offset(cx - eyeW, top - 2f),
                                    size = Size(eyeW * 2f, lidHeight + 2f),
                                )
                            }
                        }
                        if (lidFraction > 0.035f) {
                            val lidY = top + drawnEyeH * lidFraction
                            val lidLine = Path().apply {
                                moveTo(cx - eyeW * 0.46f, lidY)
                                quadraticBezierTo(
                                    cx,
                                    lidY + eyeW * 0.014f,
                                    cx + eyeW * 0.46f,
                                    lidY,
                                )
                            }
                            drawPath(
                                lidLine,
                                color = navy.copy(alpha = 0.82f),
                                style = Stroke(width = eyeW * 0.036f, cap = StrokeCap.Round),
                            )
                        }
                    }
                }
            }

            // Thick, arched brows. Their lift is live and eased by the animator.
            val browLift = w * (0.005f + browAmount * 0.024f)
            listOf(-1f, 1f).forEach { side ->
                val cx = w * 0.5f + side * eyeDX
                val extraLift = if (thinking && side > 0) w * 0.028f else 0f
                val browY = eyeY - eyeH * 0.73f - browLift - extraLift
                val arch = Path().apply {
                    moveTo(cx - eyeW * 0.48f, browY + w * 0.020f)
                    quadraticBezierTo(
                        cx,
                        browY - w * 0.032f,
                        cx + eyeW * 0.48f,
                        browY + w * 0.020f,
                    )
                }
                if (error) {
                    // Concerned brows angle in at the centre.
                    val worried = Path().apply {
                        moveTo(cx - side * eyeW * 0.48f, browY - w * 0.004f)
                        quadraticBezierTo(
                            cx,
                            browY + w * 0.035f,
                            cx + side * eyeW * 0.48f,
                            browY + w * 0.026f,
                        )
                    }
                    drawPath(
                        worried,
                        color = navy,
                        style = Stroke(width = w * 0.017f, cap = StrokeCap.Round),
                    )
                } else {
                    drawPath(
                        arch,
                        color = navy,
                        style = Stroke(width = w * 0.017f, cap = StrokeCap.Round),
                    )
                }
            }

            // The little mouth-nose from the reference.
            val mouthY = h - radius * 0.26f
            val mouthW = w * 0.115f
            if (happy) {
                val smile = Path().apply {
                    moveTo(w * 0.5f - mouthW * 0.57f, mouthY - w * 0.018f)
                    quadraticBezierTo(
                        w * 0.5f,
                        mouthY + w * 0.075f,
                        w * 0.5f + mouthW * 0.57f,
                        mouthY - w * 0.018f,
                    )
                    close()
                }
                drawPath(smile, color = navy)
            } else if (error) {
                val frown = Path().apply {
                    moveTo(w * 0.5f - mouthW * 0.43f, mouthY + w * 0.025f)
                    quadraticBezierTo(
                        w * 0.5f,
                        mouthY - w * 0.020f,
                        w * 0.5f + mouthW * 0.43f,
                        mouthY + w * 0.025f,
                    )
                }
                drawPath(
                    frown,
                    color = navy,
                    style = Stroke(width = w * 0.014f, cap = StrokeCap.Round),
                )
            } else if (sleeping) {
                // A tiny mouth that slowly opens and closes with the breath.
                val breathMouthH = w * (0.040f + 0.022f * sinF(breathe * PI_F))
                drawOval(
                    color = navy,
                    topLeft = Offset(w * 0.5f - mouthW / 2f, mouthY - breathMouthH / 2f),
                    size = Size(mouthW, breathMouthH),
                )
            } else {
                val mouthH = w * 0.058f + talk * w * 0.13f
                drawOval(
                    color = navy,
                    topLeft = Offset(w * 0.5f - mouthW / 2f, mouthY - mouthH / 2f),
                    size = Size(mouthW, mouthH),
                )
                if (talk > 0.35f) {
                    drawOval(
                        color = Color(0xFFE58BC4),
                        topLeft = Offset(
                            w * 0.5f - mouthW * 0.24f,
                            mouthY + mouthH / 2f - mouthH * 0.36f,
                        ),
                        size = Size(mouthW * 0.48f, mouthH * 0.26f),
                    )
                }
            }

            if (thinking) {
                // Three pale thought dots float off the upper-right of his head.
                repeat(3) { index ->
                    val phase = (sparkle + index * 0.27f) % 1f
                    val alpha = (0.35f + 0.55f * sinF(PI_F * phase)).coerceIn(0.12f, 0.9f)
                    drawCircle(
                        color = Color(0xFFFFEDC9).copy(alpha = alpha),
                        radius = w * (0.014f + index * 0.004f),
                        center = Offset(
                            w * (0.80f + index * 0.052f),
                            domeTop + radius * 0.14f - index * w * 0.052f +
                                sinF(sparkle * PI_F * 2f + index) * w * 0.008f,
                        ),
                    )
                }
            }

            if (listening) {
                // Tiny sparkle near the crown; no extra UI, just attentiveness.
                val alpha = 0.4f + 0.45f * sparkle
                drawSparkle(
                    center = Offset(w * 0.80f, domeTop + radius * 0.06f),
                    radius = w * 0.024f,
                    color = Color(0xFFFFF3C4).copy(alpha = alpha),
                )
            }
            }
        }
    }
}

internal fun starPath(
    center: Offset,
    outer: Float,
    inner: Float,
    rotation: Float = 0f,
): Path {
    val path = Path()
    repeat(10) { index ->
        val radius = if (index % 2 == 0) outer else inner
        val angle = -PI_F / 2f + rotation + index * PI_F / 5f
        val x = center.x + cosF(angle) * radius
        val y = center.y + sinF(angle) * radius
        if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
    }
    path.close()
    return path
}

private fun DrawScope.drawSparkle(center: Offset, radius: Float, color: Color) {
    drawLine(
        color = color,
        start = Offset(center.x - radius, center.y),
        end = Offset(center.x + radius, center.y),
        strokeWidth = 1.6.dp.toPx(),
        cap = StrokeCap.Round,
    )
    drawLine(
        color = color,
        start = Offset(center.x, center.y - radius),
        end = Offset(center.x, center.y + radius),
        strokeWidth = 1.6.dp.toPx(),
        cap = StrokeCap.Round,
    )
}
