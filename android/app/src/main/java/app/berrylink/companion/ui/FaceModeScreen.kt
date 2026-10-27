package app.berrylink.companion.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.layout.windowInsetsPadding
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.berrylink.companion.model.BerryActivity
import app.berrylink.companion.model.LinkPhase
import app.berrylink.companion.model.UiState
import app.berrylink.companion.ui.theme.Coral
import app.berrylink.companion.ui.theme.Night
import app.berrylink.companion.ui.theme.NightDeep
import app.berrylink.companion.ui.theme.Panel
import app.berrylink.companion.ui.theme.Panel
import app.berrylink.companion.ui.theme.TextMain
import app.berrylink.companion.ui.theme.TextMuted
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.util.Locale

/**
 * The paired-phone experience: a full-bleed face, no dashboard chrome.
 *
 * Touch and hold the face to talk. A short tap makes Berry smile and dismisses
 * the current speech bubble. While a finger is down the eyes follow it; the
 * rest of the time they follow the PC cursor streamed by the desktop. The
 * small settings button is the only persistent control on the phone; the
 * emergency STOP lives on the Linux desktop.
 */
@Composable
fun FaceModeScreen(
    state: UiState,
    onAttemptStartTalk: () -> Boolean,
    onReleaseTalk: () -> Unit,
    onCancelTalk: () -> Unit,
    onOpenSettings: () -> Unit,
    onWake: () -> Unit = {},
    onRetry: () -> Boolean = { false },
) {
    val scope = rememberCoroutineScope()
    val haptics = LocalHapticFeedback.current
    val latestRetry by rememberUpdatedState(onRetry)
    // Only typed asks can be retried verbatim (voice retries would re-record),
    // so expose the button whenever the last typed ask is still on screen.
    val retryable = state.lastAsk.isNotBlank()
    val latestStart by rememberUpdatedState(onAttemptStartTalk)
    val latestRelease by rememberUpdatedState(onReleaseTalk)
    val latestCancel by rememberUpdatedState(onCancelTalk)
    val latestWake by rememberUpdatedState(onWake)

    var gaze by remember { mutableStateOf<Offset?>(null) }
    var smiling by remember { mutableStateOf(false) }
    var bubbleDismissed by remember { mutableStateOf(false) }
    var showHint by rememberSaveable { mutableStateOf(true) }
    var smileJob by remember { mutableStateOf<Job?>(null) }
    var gazeJob by remember { mutableStateOf<Job?>(null) }

    LaunchedEffect(Unit) {
        delay(7200)
        showHint = false
    }
    LaunchedEffect(state.reply, state.error, state.notice) {
        bubbleDismissed = false
    }

    val faceActivity = when {
        state.recording || state.busy -> state.activity
        smiling -> BerryActivity.HAPPY
        else -> state.activity
    }
    val napping = state.activity == BerryActivity.SLEEPING && !state.recording && !state.busy
    val noticeAsBubble = state.error == null &&
        state.reply.isBlank() &&
        !state.busy &&
        !state.notice.isNullOrBlank()
    val bubble = when {
        !state.error.isNullOrBlank() -> state.error.orEmpty()
        state.busy -> "Thinking it over…"
        state.reply.isNotBlank() -> state.reply
        noticeAsBubble -> state.notice.orEmpty()
        else -> ""
    }
    val showBubble = !state.recording && !bubbleDismissed && bubble.isNotBlank()

    fun smile() {
        showHint = false
        bubbleDismissed = true
        smiling = true
        smileJob?.cancel()
        smileJob = scope.launch {
            delay(1500)
            smiling = false
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.verticalGradient(
                    colors = listOf(NightDeep, Night, Color(0xFF111936), NightDeep),
                ),
            ),
    ) {
        StarField()
        BoxWithConstraints(
            modifier = Modifier
                .fillMaxSize()
                .windowInsetsPadding(WindowInsets.safeDrawing),
        ) {
            // Full-bleed berry: with the true-semicircle body (radius = width/2,
            // clamped by height), letting the canvas use the whole screen width
            // makes the dome fill the display edge-to-edge instead of sitting
            // in a narrow column. 2026-10-24: pulled in by 5% — the full-bleed
            // face felt oversized on the Lava display.
            val faceWidth = maxWidth * 0.95f
            val sideWidth = 190.dp
            // Height of the dome from the bottom of the screen (radius = width/2
            // as long as width < height, which holds in portrait).
            val domeHeight = faceWidth * 0.5f

            Box(
                modifier = Modifier
                    .align(Alignment.Center)
                    .fillMaxHeight()
                    .width(faceWidth)
                    .semantics {
                        contentDescription =
                            "Berry's face. Hold to talk. Tap to make her smile or wake her up."
                    }
                    .pointerInput(Unit) {
                        awaitEachGesture {
                            val down = awaitFirstDown()
                            down.consume()
                            showHint = false
                            gaze = normalizedGaze(down.position, size.width.toFloat(), size.height.toFloat())
                            gazeJob?.cancel()

                            var talkStarted = false
                            val holdJob = scope.launch {
                                delay(280)
                                if (latestStart()) {
                                    talkStarted = true
                                    haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                                }
                            }

                            var released = false
                            while (true) {
                                val event = awaitPointerEvent()
                                val change = event.changes.firstOrNull { it.id == down.id } ?: break
                                if (!change.pressed) {
                                    change.consume()
                                    released = true
                                    break
                                }
                                if (change.position != down.position) {
                                    gaze = normalizedGaze(
                                        change.position,
                                        size.width.toFloat(),
                                        size.height.toFloat(),
                                    )
                                    change.consume()
                                }
                            }

                            holdJob.cancel()
                            if (talkStarted) {
                                if (released) {
                                    haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                                    latestRelease()
                                } else {
                                    latestCancel()
                                }
                            } else if (released) {
                                haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                                // A tap on a napping berry wakes him (swallowing
                                // the smile is fine: waking already beams).
                                latestWake()
                                smile()
                            }
                            gazeJob = scope.launch {
                                delay(1400)
                                gaze = null
                            }
                        }
                    },
            ) {
                BerryFace(
                    activity = faceActivity,
                    level = if (state.recording) state.inputLevel else 0f,
                    gazeTarget = gaze ?: state.cursorGaze?.let { Offset(it.x, it.y) },
                    modifier = Modifier.fillMaxSize(),
                )
            }

            if (state.busy) {
                // Thinking dots hover just above Berry's head: the face goes
                // pensive and the floating dots make the wait unmistakable.
                Box(
                    modifier = Modifier
                        .align(Alignment.BottomCenter)
                        .padding(bottom = domeHeight + 26.dp),
                ) {
                    ThinkingDots()
                }
            }

            if (showBubble) {
                Column(
                    modifier = Modifier
                        .align(Alignment.CenterStart)
                        .padding(start = 16.dp)
                        .widthIn(max = sideWidth),
                ) {
                    SpeechBubble(
                        text = bubble,
                        provider = if (state.error != null || noticeAsBubble) null else state.replyProvider,
                        notice = if (state.error == null && !noticeAsBubble) state.notice else null,
                        isError = state.error != null,
                        isThinking = state.busy,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    if (state.error != null && !state.busy && retryable) {
                        Surface(
                            onClick = {
                                if (latestRetry()) {
                                    haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                                }
                            },
                            shape = RoundedCornerShape(20.dp),
                            color = Panel.copy(alpha = 0.94f),
                            border = BorderStroke(1.dp, Coral.copy(alpha = 0.5f)),
                            modifier = Modifier
                                .padding(top = 8.dp)
                                .align(Alignment.CenterHorizontally),
                        ) {
                            Text(
                                text = "Try again",
                                style = MaterialTheme.typography.labelLarge,
                                color = Color(0xFFFFC9D1),
                                modifier = Modifier.padding(horizontal = 18.dp, vertical = 9.dp),
                            )
                        }
                    }
                }
            }

            if (state.recording) {
                RecordingPill(
                    seconds = state.recordingSeconds,
                    speechText = state.speechText,
                    modifier = Modifier
                        .align(Alignment.CenterEnd)
                        .padding(end = 18.dp)
                        .widthIn(max = sideWidth.coerceAtMost(230.dp)),
                )
            } else if (state.phase != LinkPhase.CONNECTED) {
                ConnectionPill(
                    phase = state.phase,
                    modifier = Modifier
                        .align(Alignment.CenterEnd)
                        .padding(end = 18.dp)
                        .widthIn(max = sideWidth.coerceAtMost(230.dp)),
                )
            } else if (napping) {
                // Gentle nudge so the night-night gesture stays discoverable.
                Surface(
                    shape = RoundedCornerShape(20.dp),
                    color = Panel.copy(alpha = 0.82f),
                    border = androidx.compose.foundation.BorderStroke(
                        1.dp,
                        Color.White.copy(alpha = 0.08f),
                    ),
                    modifier = Modifier
                        .align(Alignment.CenterEnd)
                        .padding(end = 18.dp)
                        .widthIn(max = 230.dp),
                ) {
                    Text(
                        text = "Napping · tap him to wake him up",
                        style = MaterialTheme.typography.labelMedium,
                        color = TextMuted,
                        modifier = Modifier.padding(horizontal = 15.dp, vertical = 11.dp),
                    )
                }
            }

            IconButton(
                onClick = onOpenSettings,
                modifier = Modifier
                    .align(Alignment.TopEnd)
                    .padding(top = 2.dp, end = 2.dp)
                    .size(44.dp)
                    .background(Color.White.copy(alpha = 0.045f), CircleShape),
            ) {
                Icon(
                    imageVector = Icons.Outlined.Settings,
                    contentDescription = "BerryLink settings",
                    tint = TextMuted.copy(alpha = 0.62f),
                    modifier = Modifier.size(21.dp),
                )
            }

            AnimatedVisibility(
                visible = showHint && !state.recording,
                enter = fadeIn(),
                exit = fadeOut(),
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .padding(bottom = 8.dp),
            ) {
                Surface(
                    shape = RoundedCornerShape(50),
                    color = Panel.copy(alpha = 0.82f),
                    border = androidx.compose.foundation.BorderStroke(
                        1.dp,
                        Color.White.copy(alpha = 0.08f),
                    ),
                ) {
                    Text(
                        text = "Hold the face to talk · tap for a smile",
                        style = MaterialTheme.typography.labelMedium,
                        color = TextMuted,
                        modifier = Modifier.padding(horizontal = 18.dp, vertical = 9.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun RecordingPill(seconds: Float, speechText: String, modifier: Modifier = Modifier) {
    val value = seconds.toInt().coerceAtLeast(0)
    val time = String.format(Locale.US, "%d:%02d", value / 60, value % 60)
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(20.dp),
        color = Coral.copy(alpha = 0.13f),
        border = androidx.compose.foundation.BorderStroke(1.dp, Coral.copy(alpha = 0.45f)),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 15.dp, vertical = 11.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(9.dp),
        ) {
            MicGlyph(modifier = Modifier.size(18.dp), color = Coral)
            Column {
                Text(
                    text = "Listening  $time",
                    style = MaterialTheme.typography.labelMedium,
                    color = TextMain,
                    fontWeight = FontWeight.SemiBold,
                )
                Text(
                    text = if (speechText.isNotBlank()) speechText else "release to send",
                    style = MaterialTheme.typography.labelSmall,
                    color = if (speechText.isNotBlank()) TextMain else TextMuted,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.widthIn(max = 180.dp),
                )
            }
        }
    }
}

@Composable
private fun ConnectionPill(phase: LinkPhase, modifier: Modifier = Modifier) {
    val label = when (phase) {
        LinkPhase.CONNECTING -> "Reconnecting…"
        LinkPhase.PAIRING -> "Pairing…"
        LinkPhase.ERROR -> "Desktop offline"
        LinkPhase.OFFLINE -> "Desktop offline"
        LinkPhase.CONNECTED -> "Connected"
    }
    val accent = if (phase == LinkPhase.CONNECTING || phase == LinkPhase.PAIRING) {
        Color(0xFFFFD37A)
    } else {
        Coral
    }
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(18.dp),
        color = accent.copy(alpha = 0.10f),
        border = androidx.compose.foundation.BorderStroke(1.dp, accent.copy(alpha = 0.30f)),
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                color = TextMain,
                textAlign = TextAlign.Center,
            )
            Text(
                text = "Settings can reconnect",
                style = MaterialTheme.typography.labelSmall,
                color = TextMuted,
                textAlign = TextAlign.Center,
            )
        }
    }
}

private fun normalizedGaze(position: Offset, width: Float, height: Float): Offset {
    if (width <= 0f || height <= 0f) return Offset.Zero
    return Offset(
        x = ((position.x / width) * 2f - 1f).coerceIn(-1f, 1f),
        y = ((position.y / height) * 2f - 1f).coerceIn(-1f, 1f),
    )
}
