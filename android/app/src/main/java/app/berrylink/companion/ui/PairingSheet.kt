package app.berrylink.companion.ui

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusDirection
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.berrylink.companion.model.DiscoveredDesktop
import app.berrylink.companion.security.Fingerprint
import app.berrylink.companion.ui.theme.BerryBlue
import app.berrylink.companion.ui.theme.BerryLight
import app.berrylink.companion.ui.theme.Butter
import app.berrylink.companion.ui.theme.Coral
import app.berrylink.companion.ui.theme.NightSoft
import app.berrylink.companion.ui.theme.Panel
import app.berrylink.companion.ui.theme.TextMain
import app.berrylink.companion.ui.theme.TextMuted

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PairingSheet(
    desktops: List<DiscoveredDesktop>,
    discovering: Boolean,
    discoveryMessage: String,
    pairingBusy: Boolean,
    pairingError: String?,
    savedFingerprint: String?,
    onRefresh: () -> Unit,
    onClearError: () -> Unit,
    onPair: (DiscoveredDesktop, String) -> Unit,
    onConnect: (DiscoveredDesktop) -> Unit,
    onConnectCodeless: (DiscoveredDesktop) -> Unit,
    onDismiss: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val focus = LocalFocusManager.current
    var selectedName by remember { mutableStateOf<String?>(null) }
    var manualSelection by remember { mutableStateOf<DiscoveredDesktop?>(null) }
    var code by remember { mutableStateOf("") }
    var manualOpen by remember { mutableStateOf(false) }
    var manualHost by remember { mutableStateOf("") }
    var manualPort by remember { mutableStateOf("8765") }
    var manualFingerprint by remember { mutableStateOf("") }
    var manualError by remember { mutableStateOf<String?>(null) }

    val selected = manualSelection ?: desktops.firstOrNull { it.serviceName == selectedName }

    LaunchedEffect(desktops.size) {
        if (manualSelection == null && selectedName == null && desktops.size == 1) {
            selectedName = desktops.first().serviceName
        }
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
                    Text(
                        text = "Pair your desktop",
                        style = MaterialTheme.typography.headlineMedium,
                    )
                    Spacer(Modifier.height(4.dp))
                    Text(
                        text = "Run BerryLink on Kali Linux, choose “Pair a phone”, then select it here.",
                        style = MaterialTheme.typography.bodySmall,
                        color = TextMuted,
                    )
                }
                IconButton(onClick = onDismiss, enabled = !pairingBusy) {
                    Icon(Icons.Outlined.Close, contentDescription = "Close pairing", tint = TextMuted)
                }
            }

            Surface(
                shape = RoundedCornerShape(18.dp),
                color = Panel.copy(alpha = 0.72f),
                border = BorderStroke(1.dp, Color.White.copy(alpha = 0.07f)),
            ) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(10.dp),
                ) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            text = "Desktops on this Wi-Fi",
                            style = MaterialTheme.typography.titleMedium,
                            modifier = Modifier.weight(1f),
                        )
                        TextButton(onClick = onRefresh, enabled = !pairingBusy) {
                            Icon(
                                Icons.Outlined.Refresh,
                                contentDescription = null,
                                modifier = Modifier.size(16.dp),
                            )
                            Spacer(Modifier.size(5.dp))
                            Text("Refresh")
                        }
                    }
                    Text(
                        text = discoveryMessage,
                        style = MaterialTheme.typography.bodySmall,
                        color = TextMuted,
                    )
                    if (desktops.isEmpty()) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(10.dp),
                        ) {
                            if (discovering) {
                                CircularProgressIndicator(
                                    modifier = Modifier.size(16.dp),
                                    color = BerryBlue,
                                    strokeWidth = 2.dp,
                                )
                            }
                            Text(
                                text = if (discovering) {
                                    "Searching with mDNS…"
                                } else {
                                    "No desktops found yet."
                                },
                                style = MaterialTheme.typography.bodyMedium,
                                color = TextMuted,
                            )
                        }
                    } else {
                        Column(
                            modifier = Modifier
                                .heightIn(max = 188.dp)
                                .verticalScroll(rememberScrollState()),
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            desktops.forEach { desktop ->
                                val isSelected = selected == desktop && manualSelection == null
                                Surface(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clickable(enabled = !pairingBusy) {
                                            selectedName = desktop.serviceName
                                            manualSelection = null
                                            onClearError()
                                        },
                                    shape = RoundedCornerShape(14.dp),
                                    color = if (isSelected) BerryBlue.copy(alpha = 0.16f) else Color.White.copy(alpha = 0.035f),
                                    border = BorderStroke(
                                        1.dp,
                                        if (isSelected) BerryBlue.copy(alpha = 0.68f) else Color.White.copy(alpha = 0.06f),
                                    ),
                                ) {
                                    Row(
                                        modifier = Modifier.padding(horizontal = 13.dp, vertical = 11.dp),
                                        verticalAlignment = Alignment.CenterVertically,
                                    ) {
                                        Column(Modifier.weight(1f)) {
                                            Text(
                                                text = desktop.displayName,
                                                style = MaterialTheme.typography.titleMedium,
                                                color = TextMain,
                                                maxLines = 1,
                                                overflow = TextOverflow.Ellipsis,
                                            )
                                            Text(
                                                text = "${desktop.host}:${desktop.port}",
                                                style = MaterialTheme.typography.bodySmall,
                                                color = TextMuted,
                                                maxLines = 1,
                                                overflow = TextOverflow.Ellipsis,
                                            )
                                        }
                                        Text(
                                            text = Fingerprint.short(desktop.fingerprint),
                                            style = MaterialTheme.typography.labelSmall,
                                            color = if (isSelected) BerryLight else TextMuted,
                                        )
                                    }
                                }
                            }
                        }
                    }
                }
            }

            TextButton(
                onClick = {
                    manualOpen = !manualOpen
                    manualError = null
                    onClearError()
                },
                enabled = !pairingBusy,
            ) {
                Text(if (manualOpen) "Hide manual address" else "Can’t find it? Enter the address")
            }

            AnimatedVisibility(visible = manualOpen) {
                Surface(
                    shape = RoundedCornerShape(18.dp),
                    color = Panel.copy(alpha = 0.58f),
                    border = BorderStroke(1.dp, Color.White.copy(alpha = 0.06f)),
                ) {
                    Column(
                        modifier = Modifier.padding(14.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        OutlinedTextField(
                            value = manualHost,
                            onValueChange = { manualHost = it; manualError = null; onClearError() },
                            modifier = Modifier.fillMaxWidth(),
                            label = { Text("Desktop IP or hostname") },
                            singleLine = true,
                            enabled = !pairingBusy,
                            keyboardOptions = KeyboardOptions(
                                keyboardType = KeyboardType.Uri,
                                imeAction = ImeAction.Next,
                            ),
                            keyboardActions = KeyboardActions(
                                onNext = { focus.moveFocus(FocusDirection.Down) },
                            ),
                            shape = RoundedCornerShape(14.dp),
                        )
                        OutlinedTextField(
                            value = manualPort,
                            onValueChange = { value ->
                                manualPort = value.filter(Char::isDigit).take(5)
                                manualError = null
                            },
                            modifier = Modifier.fillMaxWidth(),
                            label = { Text("Port") },
                            singleLine = true,
                            enabled = !pairingBusy,
                            keyboardOptions = KeyboardOptions(
                                keyboardType = KeyboardType.Number,
                                imeAction = ImeAction.Next,
                            ),
                            keyboardActions = KeyboardActions(
                                onNext = { focus.moveFocus(FocusDirection.Down) },
                            ),
                            shape = RoundedCornerShape(14.dp),
                        )
                        OutlinedTextField(
                            value = manualFingerprint,
                            onValueChange = {
                                manualFingerprint = it.take(160)
                                manualError = null
                                onClearError()
                            },
                            modifier = Modifier.fillMaxWidth(),
                            label = { Text("TLS certificate SHA-256") },
                            supportingText = {
                                Text("Copy it from the desktop’s Pair a phone dialog.")
                            },
                            minLines = 2,
                            enabled = !pairingBusy,
                            keyboardOptions = KeyboardOptions(
                                keyboardType = KeyboardType.Ascii,
                                imeAction = ImeAction.Done,
                            ),
                            keyboardActions = KeyboardActions(
                                onDone = {
                                    focus.clearFocus()
                                },
                            ),
                            shape = RoundedCornerShape(14.dp),
                        )
                        if (manualError != null) {
                            Text(
                                text = manualError.orEmpty(),
                                style = MaterialTheme.typography.bodySmall,
                                color = Coral,
                            )
                        }
                        Button(
                            onClick = {
                                val port = manualPort.toIntOrNull()
                                val pin = Fingerprint.normalize(manualFingerprint)
                                when {
                                    manualHost.isBlank() -> manualError = "Enter the desktop IP or hostname."
                                    port == null || port !in 1..65535 -> manualError = "Enter a port from 1 to 65535."
                                    pin == null -> manualError = "The TLS pin must contain 64 hexadecimal characters."
                                    else -> {
                                        val manual = DiscoveredDesktop(
                                            serviceName = "manual",
                                            displayName = manualHost.trim(),
                                            host = manualHost.trim(),
                                            port = port,
                                            fingerprint = pin,
                                        )
                                        manualSelection = manual
                                        selectedName = null
                                        manualError = null
                                        onClearError()
                                    }
                                }
                            },
                            modifier = Modifier.fillMaxWidth(),
                            enabled = !pairingBusy,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = BerryBlue,
                                contentColor = Color.White,
                            ),
                        ) {
                            Text("Use this desktop")
                        }
                    }
                }
            }

            Surface(
                shape = RoundedCornerShape(18.dp),
                color = BerryBlue.copy(alpha = 0.09f),
                border = BorderStroke(1.dp, BerryBlue.copy(alpha = 0.22f)),
            ) {
                val selectedPin = selected?.let { Fingerprint.normalize(it.fingerprint) }
                val alreadyPaired = selectedPin != null && selectedPin == savedFingerprint
                Column(
                    modifier = Modifier.padding(15.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(
                        text = if (alreadyPaired) {
                            "Connect to ${selected?.displayName}"
                        } else if (selected != null) {
                            "Pairing with ${selected.displayName}"
                        } else {
                            "Choose a desktop above"
                        },
                        style = MaterialTheme.typography.titleMedium,
                        color = if (selected != null) BerryLight else TextMuted,
                    )
                    if (alreadyPaired) {
                        Button(
                            onClick = {
                                focus.clearFocus()
                                if (selected != null) onConnect(selected)
                            },
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(52.dp),
                            enabled = !pairingBusy,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = BerryBlue,
                                contentColor = Color.White,
                            ),
                            shape = RoundedCornerShape(15.dp),
                        ) {
                            Text("Connect — already paired", fontWeight = FontWeight.SemiBold)
                        }
                        Text(
                            text = "A new code is only needed if pairing was reset on the desktop.",
                            style = MaterialTheme.typography.labelSmall,
                            color = TextMuted,
                        )
                    }
                    if (!alreadyPaired) {
                        Button(
                            onClick = {
                                focus.clearFocus()
                                if (selected != null) onConnectCodeless(selected)
                            },
                            modifier = Modifier
                                .fillMaxWidth()
                                .height(52.dp),
                            enabled = selected != null && !pairingBusy,
                            colors = ButtonDefaults.buttonColors(
                                containerColor = BerryBlue,
                                contentColor = Color.White,
                            ),
                            shape = RoundedCornerShape(15.dp),
                        ) {
                            Text("Connect — the desktop will ask you", fontWeight = FontWeight.SemiBold)
                        }
                    }
                    OutlinedTextField(
                        value = code,
                        onValueChange = { value ->
                            code = value.filter(Char::isDigit).take(6)
                            onClearError()
                        },
                        modifier = Modifier.fillMaxWidth(),
                        label = { Text("Six-digit pairing code") },
                        placeholder = { Text("000000") },
                        singleLine = true,
                        enabled = selected != null && !pairingBusy,
                        keyboardOptions = KeyboardOptions(
                            keyboardType = KeyboardType.Number,
                            imeAction = ImeAction.Done,
                        ),
                        keyboardActions = KeyboardActions(
                            onDone = {
                                focus.clearFocus()
                                if (selected != null && code.length == 6 && !pairingBusy) {
                                    onPair(selected, code)
                                }
                            },
                        ),
                        shape = RoundedCornerShape(14.dp),
                    )
                    if (pairingError != null) {
                        Text(
                            text = pairingError,
                            style = MaterialTheme.typography.bodySmall,
                            color = Coral,
                        )
                    }
                    Button(
                        onClick = {
                            focus.clearFocus()
                            if (selected != null) onPair(selected, code)
                        },
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(52.dp),
                        enabled = selected != null && code.length == 6 && !pairingBusy,
                        colors = ButtonDefaults.buttonColors(
                            containerColor = BerryBlue,
                            contentColor = Color.White,
                            disabledContainerColor = Color(0xFF2B3556),
                            disabledContentColor = Color(0xFF7682A6),
                        ),
                        shape = RoundedCornerShape(15.dp),
                    ) {
                        if (pairingBusy) {
                            CircularProgressIndicator(
                                modifier = Modifier.size(20.dp),
                                color = Color.White,
                                strokeWidth = 2.dp,
                            )
                        } else {
                            Text("Pair securely", fontWeight = FontWeight.SemiBold)
                        }
                    }
                    Text(
                        text = "The certificate pin is checked before the code is sent. The phone stores only an encrypted device token.",
                        style = MaterialTheme.typography.labelSmall,
                        color = TextMuted,
                    )
                }
            }

            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Surface(
                    shape = RoundedCornerShape(6.dp),
                    color = Butter.copy(alpha = 0.12f),
                ) {
                    Text(
                        text = "TLS",
                        modifier = Modifier.padding(horizontal = 7.dp, vertical = 3.dp),
                        style = MaterialTheme.typography.labelSmall,
                        color = Butter,
                    )
                }
                Text(
                    text = "Certificates are pinned exactly; the app never uses a trust-all TLS fallback.",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextMuted,
                )
            }
        }
    }
}
