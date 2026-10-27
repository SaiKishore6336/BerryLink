package app.berrylink.companion.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Settings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
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
import androidx.compose.foundation.layout.systemBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import app.berrylink.companion.BerryViewModel
import app.berrylink.companion.model.BerryActivity
import app.berrylink.companion.model.LinkPhase
import app.berrylink.companion.model.UiState
import app.berrylink.companion.ui.theme.BerryBlue
import app.berrylink.companion.ui.theme.BerryLight
import app.berrylink.companion.ui.theme.Butter
import app.berrylink.companion.ui.theme.Coral
import app.berrylink.companion.ui.theme.Ink
import app.berrylink.companion.ui.theme.Lavender
import app.berrylink.companion.ui.theme.Mint
import app.berrylink.companion.ui.theme.Night
import app.berrylink.companion.ui.theme.NightDeep
import app.berrylink.companion.ui.theme.Panel
import app.berrylink.companion.ui.theme.TextMain
import app.berrylink.companion.ui.theme.TextMuted
import java.util.Locale

@Composable
fun BerryLinkApp(viewModel: BerryViewModel) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val haptics = LocalHapticFeedback.current
    val faceMode = state.paired != null
    CompanionWindowMode(faceMode = faceMode)
    var showPairing by rememberSaveable { mutableStateOf(false) }
    var showSettings by rememberSaveable { mutableStateOf(false) }
    var showTextAsk by rememberSaveable { mutableStateOf(false) }
    var showMicDialog by rememberSaveable { mutableStateOf(false) }
    var micGranted by remember {
        mutableStateOf(
            ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED,
        )
    }

    val micLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission(),
    ) { granted ->
        micGranted = granted
        showMicDialog = !granted
    }

    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                micGranted = ContextCompat.checkSelfPermission(
                    context,
                    Manifest.permission.RECORD_AUDIO,
                ) == PackageManager.PERMISSION_GRANTED
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }

    LaunchedEffect(state.paired?.deviceId) {
        if (state.paired != null) {
            showPairing = false
        }
    }

    val startTalk = {
        if (state.phase != LinkPhase.CONNECTED) {
            if (state.paired == null) {
                viewModel.refreshDiscovery()
                showPairing = true
            }
        } else if (!micGranted) {
            micLauncher.launch(Manifest.permission.RECORD_AUDIO)
        } else if (!state.busy) {
            haptics.performHapticFeedback(HapticFeedbackType.LongPress)
            viewModel.startRecording()
        }
    }
    val releaseTalk = {
        if (state.recording) {
            haptics.performHapticFeedback(HapticFeedbackType.LongPress)
        }
        viewModel.finishRecordingAndAsk()
    }
    val cancelTalk = {
        viewModel.cancelRecording()
    }
    // Delayed by FaceModeScreen so a short tap can make Berry smile instead of
    // opening a permission prompt. Returning true means recording actually
    // started and the caller should send the release/cancel callback.
    val attemptFaceTalk = {
        if (state.phase == LinkPhase.CONNECTED && !state.busy && !state.recording) {
            if (!micGranted) {
                micLauncher.launch(Manifest.permission.RECORD_AUDIO)
                false
            } else {
                viewModel.startRecording()
            }
        } else {
            false
        }
    }

    if (faceMode) {
        FaceModeScreen(
            state = state,
            onAttemptStartTalk = attemptFaceTalk,
            onReleaseTalk = viewModel::finishRecordingAndAsk,
            onCancelTalk = viewModel::cancelRecording,
            onOpenSettings = { showSettings = true },
            onWake = viewModel::wakeFromSleep,
            onRetry = viewModel::retryLastAsk,
        )
    } else {
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
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .systemBarsPadding()
                    .padding(horizontal = 20.dp),
            ) {
                BerryHeader(
                    state = state,
                    onSettings = { showSettings = true },
                    onPair = {
                        viewModel.refreshDiscovery()
                        showPairing = true
                    },
                    onReconnect = viewModel::reconnect,
                )

                Spacer(Modifier.height(12.dp))

                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .weight(1f),
                ) {
                    SpeechBubble(
                        text = bubbleText(state),
                        provider = if (state.error == null && state.phase == LinkPhase.CONNECTED) state.replyProvider else null,
                        notice = if (state.error == null) state.notice else null,
                        isError = state.error != null,
                        isThinking = state.busy && state.activity == BerryActivity.THINKING,
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Box(
                        modifier = Modifier
                            .fillMaxWidth()
                            .weight(1f)
                            .padding(top = 4.dp, bottom = 2.dp),
                        contentAlignment = Alignment.Center,
                    ) {
                        BerryFace(
                            activity = state.activity,
                            level = if (state.recording) state.inputLevel else 0f,
                            modifier = Modifier.fillMaxSize(),
                        )
                    }
                }

                Spacer(Modifier.height(2.dp))

                Column(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    HoldToTalkButton(
                        recording = state.recording,
                        enabled = state.phase == LinkPhase.CONNECTED && !state.busy,
                        level = state.inputLevel,
                        onStart = startTalk,
                        onRelease = releaseTalk,
                        onCancel = cancelTalk,
                    )
                    Text(
                        text = talkLabel(state),
                        style = MaterialTheme.typography.titleMedium,
                        color = if (state.recording) Coral else if (state.phase == LinkPhase.CONNECTED) TextMain else TextMuted,
                        modifier = Modifier.padding(top = 2.dp),
                        textAlign = TextAlign.Center,
                    )
                    Row(
                        modifier = Modifier.height(40.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(4.dp),
                    ) {
                        if (state.phase == LinkPhase.CONNECTED) {
                            TextButton(onClick = { showTextAsk = true }, enabled = !state.busy && !state.recording) {
                                Text("Type instead", color = BerryLight)
                            }
                        } else {
                            Button(
                                onClick = viewModel::connectNearest,
                                enabled = !state.pairingBusy,
                                colors = ButtonDefaults.buttonColors(
                                    containerColor = BerryBlue,
                                    contentColor = Color.White,
                                ),
                                shape = RoundedCornerShape(15.dp),
                            ) {
                                Text(
                                    if (state.pairingBusy) "Connecting…" else "Connect",
                                    fontWeight = FontWeight.SemiBold,
                                )
                            }
                            Spacer(Modifier.width(6.dp))
                            TextButton(
                                onClick = {
                                    viewModel.refreshDiscovery()
                                    showPairing = true
                                },
                            ) {
                                Text(
                                    when {
                                        state.paired == null -> "Pair a desktop"
                                        state.retryBlocked -> "Pair again"
                                        else -> "More options"
                                    },
                                    color = BerryLight,
                                )
                            }
                        }
                    }
                    Text(
                        text = "Mic only while held · Gemini key stays on your Linux desktop",
                        style = MaterialTheme.typography.labelSmall,
                        color = TextMuted.copy(alpha = 0.82f),
                        textAlign = TextAlign.Center,
                        modifier = Modifier.padding(bottom = 8.dp),
                    )
                    if (state.pairingLoadIssue != null) {
                        Text(
                            text = state.pairingLoadIssue.orEmpty(),
                            style = MaterialTheme.typography.labelSmall,
                            color = Coral,
                            textAlign = TextAlign.Center,
                            modifier = Modifier.padding(horizontal = 24.dp)
                                .padding(bottom = 6.dp),
                        )
                    }
                }
            }
        }
    }

    if (showPairing) {
        PairingSheet(
            desktops = state.discovered,
            discovering = state.discovering,
            discoveryMessage = state.discoveryMessage,
            pairingBusy = state.pairingBusy,
            pairingError = state.pairingError,
            savedFingerprint = state.paired?.fingerprint,
            onRefresh = viewModel::refreshDiscovery,
            onClearError = viewModel::clearPairingError,
            onPair = { desktop, code -> viewModel.pairDesktop(desktop, code) },
            onConnect = { desktop ->
                if (viewModel.connectToDesktop(desktop)) {
                    showPairing = false
                    viewModel.stopDiscovery()
                }
            },
            onConnectCodeless = { desktop ->
                if (viewModel.pairCodelessDesktop(desktop)) {
                    showPairing = false
                    viewModel.stopDiscovery()
                }
            },
            onDismiss = {
                if (!state.pairingBusy) {
                    showPairing = false
                    viewModel.stopDiscovery()
                    viewModel.clearPairingError()
                }
            },
        )
    }

    if (showSettings) {
        SettingsSheet(
            state = state,
            onDismiss = { showSettings = false },
            onToggleTts = viewModel::setTtsEnabled,
            onReconnect = viewModel::reconnect,
            onClearConversation = viewModel::resetConversation,
            onTypeQuestion = {
                showSettings = false
                showTextAsk = true
            },
            onForget = {
                showSettings = false
                viewModel.forgetDesktop()
            },
            onPairAnother = {
                showSettings = false
                viewModel.refreshDiscovery()
                showPairing = true
            },
        )
    }

    if (showTextAsk) {
        TextAskDialog(
            onDismiss = { showTextAsk = false },
            onSend = { text ->
                if (viewModel.askText(text)) showTextAsk = false
            },
        )
    }

    if (showMicDialog) {
        AlertDialog(
            onDismissRequest = { showMicDialog = false },
            title = { Text("Microphone permission") },
            text = {
                Text(
                    "Hold-to-talk needs the microphone. BerryLink records only while you hold the button. You can still use “Type instead” without it.",
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        showMicDialog = false
                        micLauncher.launch(Manifest.permission.RECORD_AUDIO)
                    },
                ) {
                    Text("Try again", color = BerryLight)
                }
            },
            dismissButton = {
                Row {
                    TextButton(
                        onClick = {
                            showMicDialog = false
                            context.startActivity(
                                Intent(
                                    Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                                    Uri.parse("package:${context.packageName}"),
                                ),
                            )
                        },
                    ) {
                        Text("App settings", color = TextMuted)
                    }
                    TextButton(onClick = { showMicDialog = false }) {
                        Text("Not now", color = TextMuted)
                    }
                }
            },
            containerColor = Panel,
            titleContentColor = TextMain,
            textContentColor = TextMuted,
        )
    }
}

@Composable
private fun BerryHeader(
    state: UiState,
    onSettings: () -> Unit,
    onPair: () -> Unit,
    onReconnect: () -> Unit,
) {
    Column {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 6.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Surface(
                shape = RoundedCornerShape(15.dp),
                color = Color.White.copy(alpha = 0.045f),
                border = androidx.compose.foundation.BorderStroke(1.dp, Color.White.copy(alpha = 0.06f)),
            ) {
                Box(Modifier.padding(5.dp)) {
                    MiniBerryMark(size = 40.dp)
                }
            }
            Spacer(Modifier.width(11.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    text = "BerryLink",
                    style = MaterialTheme.typography.headlineLarge,
                    color = TextMain,
                )
                Text(
                    text = "YOUR LINUX DESKTOP COMPANION",
                    style = MaterialTheme.typography.labelSmall.copy(letterSpacing = 1.15.sp),
                    color = TextMuted,
                )
            }
            IconButton(
                onClick = onSettings,
                modifier = Modifier
                    .size(46.dp)
                    .background(Color.White.copy(alpha = 0.045f), CircleShape),
            ) {
                Icon(
                    Icons.Outlined.Settings,
                    contentDescription = "Settings",
                    tint = TextMuted,
                )
            }
        }

        Spacer(Modifier.height(13.dp))

        val status = statusPresentation(state)
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            StatusPill(text = status.first, color = status.second)
            Spacer(Modifier.width(10.dp))
            if (state.phase == LinkPhase.CONNECTING || state.phase == LinkPhase.PAIRING) {
                CircularProgressIndicator(
                    modifier = Modifier.size(13.dp),
                    strokeWidth = 1.8.dp,
                    color = status.second,
                )
                Spacer(Modifier.width(7.dp))
            }
            Text(
                text = state.connectionDetail,
                style = MaterialTheme.typography.bodySmall,
                color = if (state.phase == LinkPhase.ERROR) Coral else TextMuted,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            when {
                state.paired == null -> {
                    TextButton(onClick = onPair) {
                        Text("Pair", color = BerryLight, fontWeight = FontWeight.SemiBold)
                    }
                }
                state.phase != LinkPhase.CONNECTED &&
                    state.phase != LinkPhase.CONNECTING &&
                    state.phase != LinkPhase.PAIRING -> {
                    TextButton(onClick = onReconnect) {
                        Text("Reconnect", color = BerryLight, fontWeight = FontWeight.SemiBold)
                    }
                }
            }
        }
    }
}

private fun statusPresentation(state: UiState): Pair<String, Color> = when (state.phase) {
    LinkPhase.CONNECTED -> "Connected" to Mint
    LinkPhase.CONNECTING -> "Connecting" to Butter
    LinkPhase.PAIRING -> "Pairing" to Lavender
    LinkPhase.ERROR -> "Needs attention" to Coral
    LinkPhase.OFFLINE -> if (state.paired == null) "Not paired" to TextMuted else "Offline" to Coral
}

private fun bubbleText(state: UiState): String = when {
    state.error != null -> state.error.orEmpty()
    state.recording -> "Listening… release when you’re done."
    state.busy -> "Thinking it over…"
    state.reply.isNotBlank() -> state.reply
    state.phase == LinkPhase.CONNECTING -> "Waking up a secure connection to your desktop…"
    state.phase == LinkPhase.CONNECTED && state.paired == null -> "Connected. Hold the button and ask me something."
    state.phase == LinkPhase.CONNECTED -> "I’m ready. Hold the button and ask, or ask me to point at something."
    state.paired == null -> "Hi, I’m Berry. Pair me with your Linux desktop and I’ll point things out on screen."
    else -> "I’m offline. Check that BerryLink is running on the desktop, then reconnect."
}

private fun talkLabel(state: UiState): String = when {
    state.recording -> {
        val seconds = state.recordingSeconds.toInt()
        val time = String.format(Locale.US, "%d:%02d", seconds / 60, seconds % 60)
        "Listening $time · release to send"
    }
    state.busy -> "Thinking it over…"
    state.phase == LinkPhase.CONNECTED -> "Hold to talk"
    state.paired == null -> "Pair a desktop to start"
    else -> "Desktop offline"
}

@Composable
private fun TextAskDialog(
    onDismiss: () -> Unit,
    onSend: (String) -> Unit,
) {
    var text by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("Ask by typing") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    "This uses the same desktop gateway as voice, including local mock mode when no Gemini key is configured.",
                    style = MaterialTheme.typography.bodySmall,
                    color = TextMuted,
                )
                OutlinedTextField(
                    value = text,
                    onValueChange = { text = it.take(1000) },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 2,
                    maxLines = 5,
                    placeholder = { Text("Point at the search bar…") },
                    shape = RoundedCornerShape(14.dp),
                    keyboardOptions = androidx.compose.foundation.text.KeyboardOptions(
                        imeAction = ImeAction.Send,
                    ),
                    keyboardActions = androidx.compose.foundation.text.KeyboardActions(
                        onSend = {
                            if (text.isNotBlank()) onSend(text)
                        },
                    ),
                )
            }
        },
        confirmButton = {
            Button(
                onClick = { if (text.isNotBlank()) onSend(text) },
                enabled = text.isNotBlank(),
                colors = ButtonDefaults.buttonColors(containerColor = BerryBlue, contentColor = Color.White),
                shape = RoundedCornerShape(12.dp),
            ) {
                Text("Send")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text("Cancel", color = TextMuted) }
        },
        containerColor = Panel,
        titleContentColor = TextMain,
        textContentColor = TextMuted,
    )
}
