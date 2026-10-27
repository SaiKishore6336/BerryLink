package app.berrylink.companion.ui

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.berrylink.companion.model.LinkPhase
import app.berrylink.companion.model.UiState
import app.berrylink.companion.security.Fingerprint
import app.berrylink.companion.ui.theme.BerryBlue
import app.berrylink.companion.ui.theme.BerryLight
import app.berrylink.companion.ui.theme.Coral
import app.berrylink.companion.ui.theme.Mint
import app.berrylink.companion.ui.theme.NightSoft
import app.berrylink.companion.ui.theme.Panel
import app.berrylink.companion.ui.theme.TextMain
import app.berrylink.companion.ui.theme.TextMuted

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsSheet(
    state: UiState,
    onDismiss: () -> Unit,
    onToggleTts: (Boolean) -> Unit,
    onReconnect: () -> Unit,
    onClearConversation: () -> Unit,
    onTypeQuestion: () -> Unit,
    onForget: () -> Unit,
    onPairAnother: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val clipboard = LocalClipboardManager.current
    var confirmForget by remember { mutableStateOf(false) }
    var copied by remember { mutableStateOf(false) }
    val pairing = state.paired
    val statusColor = when (state.phase) {
        LinkPhase.CONNECTED -> Mint
        LinkPhase.CONNECTING, LinkPhase.PAIRING -> Color(0xFFFFD37A)
        LinkPhase.ERROR -> Coral
        LinkPhase.OFFLINE -> TextMuted
    }
    val statusText = when (state.phase) {
        LinkPhase.CONNECTED -> "Connected"
        LinkPhase.CONNECTING -> "Connecting"
        LinkPhase.PAIRING -> "Pairing"
        LinkPhase.ERROR -> "Needs attention"
        LinkPhase.OFFLINE -> "Offline"
    }

    if (confirmForget) {
        AlertDialog(
            onDismissRequest = { confirmForget = false },
            title = { Text("Forget this desktop?") },
            text = {
                Text(
                    "The encrypted pairing token and pinned certificate will be deleted from this phone. You will need the desktop’s six-digit code to pair again.",
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        confirmForget = false
                        onForget()
                    },
                ) {
                    Text("Forget", color = Coral)
                }
            },
            dismissButton = {
                TextButton(onClick = { confirmForget = false }) { Text("Cancel") }
            },
            containerColor = NightSoft,
            titleContentColor = TextMain,
            textContentColor = TextMuted,
        )
    }

    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheetState,
        containerColor = NightSoft,
        contentColor = TextMain,
        scrimColor = Color(0xAA02040B),
        dragHandle = null,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .verticalScroll(rememberScrollState())
                .imePadding()
                .navigationBarsPadding()
                .padding(horizontal = 22.dp)
                .padding(top = 18.dp, bottom = 26.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Row(verticalAlignment = Alignment.Top) {
                Column(Modifier.weight(1f)) {
                    Text("Settings", style = MaterialTheme.typography.headlineMedium)
                    Text(
                        "Connection, voice, and privacy",
                        style = MaterialTheme.typography.bodySmall,
                        color = TextMuted,
                    )
                }
                IconButton(onClick = onDismiss) {
                    Icon(Icons.Outlined.Close, contentDescription = "Close settings", tint = TextMuted)
                }
            }

            Surface(
                shape = RoundedCornerShape(22.dp),
                color = Panel.copy(alpha = 0.68f),
                border = BorderStroke(1.dp, Color.White.copy(alpha = 0.07f)),
            ) {
                Column(
                    modifier = Modifier.padding(17.dp),
                    verticalArrangement = Arrangement.spacedBy(11.dp),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text(
                                text = pairing?.desktopName ?: "No desktop paired",
                                style = MaterialTheme.typography.titleLarge,
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                            Text(
                                text = if (pairing != null) "${pairing.host}:${pairing.port}" else "Pair from the home screen",
                                style = MaterialTheme.typography.bodySmall,
                                color = TextMuted,
                            )
                        }
                        StatusPill(text = statusText, color = statusColor)
                    }
                    Text(
                        text = state.connectionDetail,
                        style = MaterialTheme.typography.bodySmall,
                        color = if (state.phase == LinkPhase.ERROR) Coral else TextMuted,
                        maxLines = 3,
                        overflow = TextOverflow.Ellipsis,
                    )
                    if (pairing != null) {
                        HorizontalDivider(color = Color.White.copy(alpha = 0.07f))
                        Text(
                            text = "PINNED CERTIFICATE",
                            style = MaterialTheme.typography.labelSmall.copy(letterSpacing = 1.1.sp),
                            color = TextMuted,
                        )
                        SelectionContainer {
                            Text(
                                text = Fingerprint.pretty(pairing.fingerprint),
                                style = MaterialTheme.typography.bodySmall.copy(
                                    fontFamily = FontFamily.Monospace,
                                    fontSize = MaterialTheme.typography.bodySmall.fontSize,
                                ),
                                color = BerryLight,
                            )
                        }
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            OutlinedButton(
                                onClick = {
                                    clipboard.setText(AnnotatedString(pairing.fingerprint))
                                    copied = true
                                },
                                modifier = Modifier.weight(1f),
                                shape = RoundedCornerShape(12.dp),
                                border = BorderStroke(1.dp, Color.White.copy(alpha = 0.12f)),
                            ) {
                                Text(if (copied) "Copied" else "Copy fingerprint", color = TextMain)
                            }
                            OutlinedButton(
                                onClick = onReconnect,
                                modifier = Modifier.weight(1f),
                                enabled = state.phase != LinkPhase.CONNECTING && !state.pairingBusy,
                                shape = RoundedCornerShape(12.dp),
                                border = BorderStroke(1.dp, Color.White.copy(alpha = 0.12f)),
                            ) {
                                Icon(
                                    Icons.Outlined.Refresh,
                                    contentDescription = null,
                                    modifier = Modifier.size(16.dp),
                                )
                                Spacer(Modifier.size(5.dp))
                                Text("Reconnect")
                            }
                        }
                    }
                }
            }

            Surface(
                shape = RoundedCornerShape(22.dp),
                color = Panel.copy(alpha = 0.55f),
                border = BorderStroke(1.dp, Color.White.copy(alpha = 0.065f)),
            ) {
                Column(
                    modifier = Modifier.padding(17.dp),
                    verticalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    Text("Voice & conversation", style = MaterialTheme.typography.titleMedium)
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("Speak replies aloud", style = MaterialTheme.typography.bodyLarge)
                            Text(
                                "Uses the phone’s installed text-to-speech voice.",
                                style = MaterialTheme.typography.bodySmall,
                                color = TextMuted,
                            )
                        }
                        Switch(
                            checked = state.ttsEnabled,
                            onCheckedChange = onToggleTts,
                            colors = SwitchDefaults.colors(
                                checkedThumbColor = Color.White,
                                checkedTrackColor = BerryBlue,
                                uncheckedThumbColor = Color(0xFFB7C0D8),
                                uncheckedTrackColor = Color(0xFF2A3350),
                            ),
                        )
                    }
                    OutlinedButton(
                        onClick = onTypeQuestion,
                        enabled = state.phase == LinkPhase.CONNECTED && !state.busy && !state.recording,
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                        border = BorderStroke(1.dp, Color.White.copy(alpha = 0.12f)),
                    ) {
                        Text("Ask by typing")
                    }
                    OutlinedButton(
                        onClick = onClearConversation,
                        enabled = state.phase == LinkPhase.CONNECTED,
                        modifier = Modifier.fillMaxWidth(),
                        shape = RoundedCornerShape(12.dp),
                        border = BorderStroke(1.dp, Color.White.copy(alpha = 0.12f)),
                    ) {
                        Text("Start a fresh conversation")
                    }
                }
            }

            Surface(
                shape = RoundedCornerShape(22.dp),
                color = Panel.copy(alpha = 0.55f),
                border = BorderStroke(1.dp, Color.White.copy(alpha = 0.065f)),
            ) {
                Column(
                    modifier = Modifier.padding(17.dp),
                    verticalArrangement = Arrangement.spacedBy(9.dp),
                ) {
                    Text("Safety & privacy", style = MaterialTheme.typography.titleMedium)
                    Bullet("The Gemini API key lives only on the Linux desktop. This phone never stores one.")
                    Bullet("Click and type control starts off on the desktop. Enabling it is a separate, visible step.")
                    Bullet("Emergency stop is always in the desktop header and sidebar; Ctrl+Alt+S works globally. The phone is not a recording device in this MVP.")
                    Bullet("Meeting recording and notes are not part of this release.")
                }
            }

            if (pairing != null) {
                Button(
                    onClick = onPairAnother,
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = BerryBlue.copy(alpha = 0.16f),
                        contentColor = BerryLight,
                    ),
                    shape = RoundedCornerShape(14.dp),
                ) {
                    Text("Pair a different desktop")
                }
                TextButton(
                    onClick = { confirmForget = true },
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text("Forget this desktop", color = Coral, fontWeight = FontWeight.SemiBold)
                }
            }
        }
    }
}

@Composable
private fun Bullet(text: String) {
    Row(horizontalArrangement = Arrangement.spacedBy(9.dp)) {
        Text("•", style = MaterialTheme.typography.bodyMedium, color = BerryBlue)
        Text(text, style = MaterialTheme.typography.bodySmall, color = TextMuted)
    }
}
