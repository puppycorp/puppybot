package fi.puppycorp.puppybot

import android.os.Bundle
import android.view.MotionEvent
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.SliderDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.ExperimentalComposeUiApi
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.input.pointer.consumeAllChanges
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.input.pointer.pointerInteropFilter
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import fi.puppycorp.puppybot.mdns.PuppybotMdns
import fi.puppycorp.puppybot.mdns.PuppybotDevice
import fi.puppycorp.puppybot.ui.theme.PuppybotTheme
import fi.puppycorp.puppybot.ws.PuppybotWebSocket
import fi.puppycorp.puppybot.ws.WebSocketState
import kotlinx.coroutines.delay
import kotlin.math.absoluteValue
import kotlin.math.roundToInt

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
    var mode by remember { mutableStateOf(ControlMode.Buttons) }

    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            ModeSelectionButton(
                label = "Buttons",
                selected = mode == ControlMode.Buttons,
                onClick = { mode = ControlMode.Buttons }
            )

            ModeSelectionButton(
                label = "Joystick",
                selected = mode == ControlMode.Joystick,
                onClick = { mode = ControlMode.Joystick }
            )
        }

        when (mode) {
            ControlMode.Buttons -> ButtonsControlPanel(ws)
            ControlMode.Joystick -> JoystickControlPanel(ws)
        }
    }
}

@Composable
private fun ButtonsControlPanel(ws: PuppybotWebSocket) {
    var speed by remember { mutableStateOf(DEFAULT_SPEED.toFloat()) }

    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
        Text("Drive speed: ${speed.toInt()}", style = MaterialTheme.typography.bodyLarge)
        Slider(
            value = speed,
            onValueChange = { speed = it },
            valueRange = MIN_SPEED.toFloat()..MAX_SPEED.toFloat(),
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
private fun ModeSelectionButton(label: String, selected: Boolean, onClick: () -> Unit) {
    if (selected) {
        Button(
            onClick = onClick
        ) {
            Text(label)
        }
    } else {
        OutlinedButton(
            onClick = onClick
        ) {
            Text(label)
        }
    }
}

@Composable
private fun JoystickControlPanel(ws: PuppybotWebSocket) {
    var throttle by remember { mutableStateOf(0f) }
    var throttleActive by remember { mutableStateOf(false) }
    var steering by remember { mutableStateOf(0f) }
    var steeringActive by remember { mutableStateOf(false) }

    DisposableEffect(Unit) {
        onDispose {
            ws.stopAllMotors()
            ws.turnServo(CENTER_ANGLE)
        }
    }

    LaunchedEffect(throttleActive, throttle) {
        if (!throttleActive || throttle.absoluteValue < JOYSTICK_DEAD_ZONE) {
            ws.stopAllMotors()
        } else {
            while (true) {
                val active = throttleActive
                val value = throttle
                if (!active || value.absoluteValue < JOYSTICK_DEAD_ZONE) {
                    ws.stopAllMotors()
                    break
                }

                val magnitude = throttleToMagnitude(value)
                if (value > 0f) {
                    ws.driveMotor(DRIVE_LEFT, magnitude)
                    ws.driveMotor(DRIVE_RIGHT, -magnitude)
                } else {
                    ws.driveMotor(DRIVE_LEFT, -magnitude)
                    ws.driveMotor(DRIVE_RIGHT, magnitude)
                }

                delay(JOYSTICK_COMMAND_INTERVAL)
            }
        }
    }

    LaunchedEffect(steeringActive, steering) {
        if (!steeringActive || steering.absoluteValue < 0.05f) {
            ws.turnServo(CENTER_ANGLE)
        } else {
            ws.turnServo(servoAngleFromInput(steering))
        }
    }

    Column(verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("Landscape joystick mode", style = MaterialTheme.typography.titleMedium)
        Text(
            "Hold your phone horizontally and rest your thumbs on the pads to steer and drive.",
            style = MaterialTheme.typography.bodyMedium
        )

        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text("Throttle", style = MaterialTheme.typography.titleMedium)
                VerticalThumbPad(
                    value = throttle,
                    active = throttleActive,
                    onValueChanged = { value, active ->
                        throttle = value
                        throttleActive = active
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .aspectRatio(0.6f)
                )

                val throttleLabel = when {
                    !throttleActive || throttle.absoluteValue < JOYSTICK_DEAD_ZONE -> "Idle"
                    throttle > 0f -> "Forward ${(throttle * 100).roundToInt()}%"
                    else -> "Reverse ${(throttle.absoluteValue * 100).roundToInt()}%"
                }
                Text(throttleLabel, style = MaterialTheme.typography.bodySmall)
            }

            Column(
                modifier = Modifier.weight(1f),
                verticalArrangement = Arrangement.spacedBy(8.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text("Steering", style = MaterialTheme.typography.titleMedium)
                HorizontalThumbPad(
                    value = steering,
                    active = steeringActive,
                    onValueChanged = { value, active ->
                        steering = value
                        steeringActive = active
                    },
                    modifier = Modifier
                        .fillMaxWidth()
                        .aspectRatio(1.4f)
                )

                val steeringLabel = when {
                    !steeringActive || steering.absoluteValue < 0.05f -> "Centered"
                    steering < 0f -> "Turning left"
                    else -> "Turning right"
                }
                Text(steeringLabel, style = MaterialTheme.typography.bodySmall)
            }
        }

        OutlinedButton(
            onClick = {
                throttle = 0f
                throttleActive = false
                steering = 0f
                steeringActive = false
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
private fun VerticalThumbPad(
    value: Float,
    active: Boolean,
    onValueChanged: (Float, Boolean) -> Unit,
    modifier: Modifier = Modifier
) {
    val density = LocalDensity.current
    val cornerRadius = with(density) { 24.dp.toPx() }
    val outlineStroke = with(density) { 2.dp.toPx() }
    val palette = MaterialTheme.colorScheme
    val indicatorColor = if (active) palette.primary else palette.primary.copy(alpha = 0.6f)
    val outlineColor = palette.outline

    Box(
        modifier = modifier
            .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(24.dp))
            .pointerInput(Unit) {
                detectDragGestures(
                    onDragStart = { offset ->
                        val normalized = verticalToNormalized(offset.y, size.height.toFloat())
                        onValueChanged(normalized, true)
                    },
                    onDrag = { change, _ ->
                        val normalized = verticalToNormalized(change.position.y, size.height.toFloat())
                        onValueChanged(normalized, true)
                        change.consumeAllChanges()
                    },
                    onDragEnd = {
                        onValueChanged(0f, false)
                    },
                    onDragCancel = {
                        onValueChanged(0f, false)
                    }
                )
            }
    ) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            drawRoundRect(
                color = outlineColor,
                cornerRadius = androidx.compose.ui.geometry.CornerRadius(cornerRadius, cornerRadius),
                style = Stroke(width = outlineStroke)
            )

            val clamped = value.coerceIn(-1f, 1f)
            val centerX = size.width / 2f
            val centerY = size.height / 2f - clamped * (size.height / 2f)
            val radius = size.minDimension / 6f

            drawCircle(color = indicatorColor, radius = radius, center = Offset(centerX, centerY))
        }
    }
}

@Composable
private fun HorizontalThumbPad(
    value: Float,
    active: Boolean,
    onValueChanged: (Float, Boolean) -> Unit,
    modifier: Modifier = Modifier
) {
    val density = LocalDensity.current
    val cornerRadius = with(density) { 24.dp.toPx() }
    val outlineStroke = with(density) { 2.dp.toPx() }
    val palette = MaterialTheme.colorScheme
    val indicatorColor = if (active) palette.primary else palette.primary.copy(alpha = 0.6f)
    val outlineColor = palette.outline

    Box(
        modifier = modifier
            .background(MaterialTheme.colorScheme.surfaceVariant, RoundedCornerShape(24.dp))
            .pointerInput(Unit) {
                detectDragGestures(
                    onDragStart = { offset ->
                        val normalized = horizontalToNormalized(offset.x, size.width.toFloat())
                        onValueChanged(normalized, true)
                    },
                    onDrag = { change, _ ->
                        val normalized = horizontalToNormalized(change.position.x, size.width.toFloat())
                        onValueChanged(normalized, true)
                        change.consumeAllChanges()
                    },
                    onDragEnd = {
                        onValueChanged(0f, false)
                    },
                    onDragCancel = {
                        onValueChanged(0f, false)
                    }
                )
            }
    ) {
        Canvas(modifier = Modifier.fillMaxSize()) {
            drawRoundRect(
                color = outlineColor,
                cornerRadius = androidx.compose.ui.geometry.CornerRadius(cornerRadius, cornerRadius),
                style = Stroke(width = outlineStroke)
            )

            val clamped = value.coerceIn(-1f, 1f)
            val centerY = size.height / 2f
            val centerX = size.width / 2f + clamped * (size.width / 2f)
            val radius = size.minDimension / 6f

            drawCircle(color = indicatorColor, radius = radius, center = Offset(centerX, centerY))
        }
    }
}

private fun verticalToNormalized(position: Float, height: Float): Float {
    if (height <= 0f) return 0f
    val fraction = (position / height).coerceIn(0f, 1f)
    return (0.5f - fraction) * 2f
}

private fun horizontalToNormalized(position: Float, width: Float): Float {
    if (width <= 0f) return 0f
    val fraction = (position / width).coerceIn(0f, 1f)
    return (fraction - 0.5f) * 2f
}

private fun throttleToMagnitude(throttle: Float): Int {
    val normalized = throttle.absoluteValue.coerceIn(0f, 1f)
    return (MIN_SPEED + (MAX_SPEED - MIN_SPEED) * normalized).roundToInt()
}

private fun servoAngleFromInput(input: Float): Int {
    val clamped = input.coerceIn(-1f, 1f)
    return if (clamped >= 0f) {
        lerpInt(CENTER_ANGLE, RIGHT_ANGLE, clamped)
    } else {
        lerpInt(CENTER_ANGLE, LEFT_ANGLE, -clamped)
    }
}

private fun lerpInt(start: Int, stop: Int, fraction: Float): Int {
    return (start + (stop - start) * fraction).roundToInt()
}

private enum class ControlMode {
    Buttons,
    Joystick
}

private const val JOYSTICK_COMMAND_INTERVAL = 200L
private const val JOYSTICK_DEAD_ZONE = 0.1f
private const val MIN_SPEED = 40
private const val MAX_SPEED = 120

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
    var activePointerId by remember { mutableStateOf<Int?>(null) }

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
            activePointerId = null
        }
    }

    Button(
        onClick = {},
        modifier = modifier
            .pointerInteropFilter { event ->
                fun releaseIfActive(): Boolean {
                    if (isPressed) {
                        isPressed = false
                        onRelease()
                    }
                    activePointerId = null
                    return true
                }

                when (event.actionMasked) {
                    MotionEvent.ACTION_DOWN, MotionEvent.ACTION_POINTER_DOWN -> {
                        if (activePointerId == null) {
                            activePointerId = event.getPointerId(event.actionIndex)
                            isPressed = true
                        }
                        true
                    }
                    MotionEvent.ACTION_UP -> releaseIfActive()
                    MotionEvent.ACTION_POINTER_UP -> {
                        val pointerId = event.getPointerId(event.actionIndex)
                        if (pointerId == activePointerId) {
                            releaseIfActive()
                        }
                        true
                    }
                    MotionEvent.ACTION_CANCEL -> releaseIfActive()
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
