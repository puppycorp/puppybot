package fi.puppycorp.puppybot

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import fi.puppycorp.puppybot.mdns.PuppybotMdns
import fi.puppycorp.puppybot.mdns.PuppybotDevice
import fi.puppycorp.puppybot.ui.theme.PuppybotTheme
import fi.puppycorp.puppybot.ws.PuppybotWebSocket
import fi.puppycorp.puppybot.ws.WebSocketState
import kotlinx.coroutines.delay
import android.view.MotionEvent
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.input.pointer.pointerInteropFilter

class MainActivity : ComponentActivity() {
    private lateinit var mdns: PuppybotMdns
    private lateinit var ws: PuppybotWebSocket

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        mdns = PuppybotMdns(this)
        ws = PuppybotWebSocket()
        setContent {
            PuppybotTheme {
                val devices by mdns.devices.collectAsState(initial = emptyList())
                val wsState by ws.state.collectAsState()
                val lastEvent by ws.events.collectAsState(initial = "")

                LaunchedEffect(devices, wsState) {
                    val first = devices.firstOrNull()
                    if (first == null) {
                        if (ws.isActive) {
                            ws.disconnect("No PuppyBots discovered")
                        }
                        return@LaunchedEffect
                    }

                    val stateDevice = wsState.device
                    val alreadyConnecting = wsState is WebSocketState.Connecting && stateDevice?.name == first.name
                    val alreadyConnected = wsState is WebSocketState.Connected && stateDevice?.name == first.name

                    if (!alreadyConnecting && !alreadyConnected) {
                        ws.connectTo(first)
                    }
                }

                LaunchedEffect(wsState) {
                    if (wsState is WebSocketState.Connected) {
                        ws.turnServo(CENTER_ANGLE)
                    }
                }

                Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
                    PuppybotScreen(
                        modifier = Modifier.padding(innerPadding),
                        devices = devices,
                        wsState = wsState,
                        lastEvent = lastEvent.takeIf { it.isNotBlank() },
                        ws = ws
                    )
                }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        mdns.start()
    }

    override fun onStop() {
        super.onStop()
        mdns.stop()
        ws.disconnect("Activity stopped")
    }

    override fun onDestroy() {
        super.onDestroy()
        ws.shutdown()
    }
}

@Composable
private fun PuppybotScreen(
    modifier: Modifier = Modifier,
    devices: List<PuppybotDevice>,
    wsState: WebSocketState,
    lastEvent: String?,
    ws: PuppybotWebSocket
) {
    Column(modifier = modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        val stateText = when (wsState) {
            is WebSocketState.Connected -> "Connected to ${wsState.device?.name}"
            is WebSocketState.Connecting -> "Connecting to ${wsState.device?.name}..."
            is WebSocketState.Disconnected -> wsState.reason?.let { reason ->
                if (wsState.device != null) "Disconnected from ${wsState.device.name}: $reason"
                else reason
            }
        }

        stateText?.let {
            Text(it, style = MaterialTheme.typography.titleMedium)
        }

        lastEvent?.let {
            Text("Last event: $it", style = MaterialTheme.typography.bodySmall)
        }

        if (devices.isEmpty()) {
            Text("Searching for PuppyBots on _ws._tcp...", style = MaterialTheme.typography.bodyLarge)
        } else {
            Text("Found ${devices.size} PuppyBot(s):", style = MaterialTheme.typography.titleMedium)
            for (d in devices) {
                val host = d.host?.hostAddress ?: "?"
                val fw = d.attributes["fw"] ?: "?"
                Text("• ${d.name} @ $host:${d.port} (fw $fw)")
            }
        }

        val connected = wsState is WebSocketState.Connected
        if (connected) {
            ControlPanel(ws = ws)
        }
    }
}

@Composable
private fun ControlPanel(ws: PuppybotWebSocket) {
    var speed by remember { mutableStateOf(DEFAULT_SPEED.toFloat()) }

    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Drive speed: ${speed.toInt()}", style = MaterialTheme.typography.bodyLarge)
        Slider(
            value = speed,
            onValueChange = { speed = it },
            valueRange = 40f..120f,
            steps = 0,
            colors = SliderDefaults.colors()
        )

        HoldRepeatButton(
            label = "Forward",
            modifier = Modifier.fillMaxWidth(),
            onRepeat = {
                val magnitude = speed.toInt()
                ws.driveMotor(DRIVE_LEFT, magnitude)
                ws.driveMotor(DRIVE_RIGHT, -magnitude)
            },
            onRelease = {
                ws.stopAllMotors()
                ws.turnServo(CENTER_ANGLE)
            }
        )

        Row(horizontalArrangement = Arrangement.spacedBy(12.dp), modifier = Modifier.fillMaxWidth()) {
            HoldRepeatButton(
                label = "Left",
                modifier = Modifier.weight(1f),
                onRepeat = { ws.turnServo(LEFT_ANGLE) },
                onRelease = { ws.turnServo(CENTER_ANGLE) }
            )

            Button(
                onClick = {
                    ws.stopAllMotors()
                    ws.turnServo(CENTER_ANGLE)
                },
                modifier = Modifier.weight(1f)
            ) {
                Text("Center")
            }

            HoldRepeatButton(
                label = "Right",
                modifier = Modifier.weight(1f),
                onRepeat = { ws.turnServo(RIGHT_ANGLE) },
                onRelease = { ws.turnServo(CENTER_ANGLE) }
            )
        }

        HoldRepeatButton(
            label = "Backward",
            modifier = Modifier.fillMaxWidth(),
            onRepeat = {
                val magnitude = speed.toInt()
                ws.driveMotor(DRIVE_LEFT, -magnitude)
                ws.driveMotor(DRIVE_RIGHT, magnitude)
            },
            onRelease = {
                ws.stopAllMotors()
                ws.turnServo(CENTER_ANGLE)
            }
        )

        OutlinedButton(
            onClick = {
                ws.stopAllMotors()
                ws.turnServo(CENTER_ANGLE)
            },
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("Emergency Stop")
        }
    }
}

@Composable
@OptIn(ExperimentalComposeUiApi::class)
private fun HoldRepeatButton(
    label: String,
    modifier: Modifier = Modifier,
    repeatIntervalMs: Long = 200L,
    onRepeat: () -> Unit,
    onRelease: () -> Unit
) {
    var isPressed by remember { mutableStateOf(false) }

    LaunchedEffect(isPressed) {
        if (isPressed) {
            onRepeat()
            while (isPressed) {
                delay(repeatIntervalMs)
                if (isPressed) {
                    onRepeat()
                }
            }
        }
    }

    DisposableEffect(Unit) {
        onDispose {
            if (isPressed) {
                isPressed = false
                onRelease()
            }
        }
    }

    Button(
        onClick = {},
        modifier = modifier
            .pointerInteropFilter { event ->
                when (event.action) {
                    MotionEvent.ACTION_DOWN -> {
                        isPressed = true
                        true
                    }
                    MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                        if (isPressed) {
                            isPressed = false
                            onRelease()
                        }
                        true
                    }
                    else -> false
                }
            }
    ) {
        Text(label)
    }
}

private const val DRIVE_LEFT = 1
private const val DRIVE_RIGHT = 2
private const val CENTER_ANGLE = 88
private const val LEFT_ANGLE = 50
private const val RIGHT_ANGLE = 150
private const val DEFAULT_SPEED = 80

@Preview(showBackground = true)
@Composable
private fun PuppybotScreenPreview() {
    PuppybotTheme {
        PuppybotScreen(
            devices = listOf(
                PuppybotDevice("puppybot", null, 80)
            ),
            wsState = WebSocketState.Connected(device = PuppybotDevice("puppybot", null, 80), url = "ws://example/ws"),
            lastEvent = "-> cmd=2 len=2",
            ws = PuppybotWebSocket()
        )
    }
}
