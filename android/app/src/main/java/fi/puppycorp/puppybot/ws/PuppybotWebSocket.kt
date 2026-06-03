package fi.puppycorp.puppybot.ws

import android.util.Log
import fi.puppycorp.puppybot.control.PuppybotArmTelemetry
import fi.puppycorp.puppybot.control.PuppybotCommandSender
import fi.puppycorp.puppybot.control.PuppybotServoConfig
import fi.puppycorp.puppybot.mdns.PuppybotDevice
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import java.util.concurrent.TimeUnit

sealed class WebSocketState(open val device: PuppybotDevice?) {
    data class Disconnected(override val device: PuppybotDevice?, val reason: String? = null) : WebSocketState(device)
    data class Connecting(override val device: PuppybotDevice, val url: String) : WebSocketState(device)
    data class Connected(override val device: PuppybotDevice, val url: String) : WebSocketState(device)
}

class PuppybotWebSocket : PuppybotCommandSender {
    companion object {
        private const val TAG = "PuppybotWebSocket"
    }

    private val client: OkHttpClient = OkHttpClient.Builder()
        .pingInterval(30, TimeUnit.SECONDS)
        .build()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val _state = MutableStateFlow<WebSocketState>(WebSocketState.Disconnected(device = null))
    val state: StateFlow<WebSocketState> = _state

    private val _events = MutableSharedFlow<String>(extraBufferCapacity = 16)
    val events: SharedFlow<String> = _events

    private val _servoConfig = MutableStateFlow(PuppybotServoConfig())
    val servoConfig: StateFlow<PuppybotServoConfig> = _servoConfig

    private val _armTelemetryEnabled = MutableStateFlow(false)
    val armTelemetryEnabled: StateFlow<Boolean> = _armTelemetryEnabled

    private val _armTelemetry = MutableStateFlow<PuppybotArmTelemetry?>(null)
    val armTelemetry: StateFlow<PuppybotArmTelemetry?> = _armTelemetry

    @Volatile
    private var webSocket: WebSocket? = null
    @Volatile
    private var currentDevice: PuppybotDevice? = null

    fun connectTo(device: PuppybotDevice) {
        val url = buildWsUrl(device) ?: run {
            Log.w(TAG, "Cannot build WS URL for ${device.name}")
            return
        }

        connectToUrl(device, url)
    }

    fun connectToHost(rawHost: String, port: Int) {
        val target = parseManualTarget(rawHost, port) ?: run {
            Log.w(TAG, "Cannot build manual WS URL for '$rawHost'")
            return
        }
        val device = PuppybotDevice("manual ${target.host}", null, target.port)
        connectToUrl(device, target.url)
    }

    private fun connectToUrl(device: PuppybotDevice, url: String) {
        if (currentDevice?.name == device.name &&
            (_state.value is WebSocketState.Connecting || _state.value is WebSocketState.Connected)
        ) {
            Log.d(TAG, "Already connecting/connected to ${device.name}, skipping")
            return
        }

        closeInternal("Switching target")

        currentDevice = device
        _state.value = WebSocketState.Connecting(device, url)
        Log.i(TAG, "Connecting to $url")

        val request = Request.Builder().url(url).build()
        val listener = object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                if (!isCurrentSocket(webSocket)) return
                Log.i(TAG, "WebSocket opened -> ${device.name}")
                _state.value = WebSocketState.Connected(device, url)
                scope.launch { _events.emit("Connected to ${device.name}") }
                sendPing(webSocket)
                requestServoConfig()
                if (_armTelemetryEnabled.value) {
                    sendArmTelemetrySubscription(webSocket, enabled = true)
                }
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                if (!isCurrentSocket(webSocket)) return
                Log.d(TAG, "WS text <- $text")
                scope.launch { _events.emit("Text: $text") }
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                if (!isCurrentSocket(webSocket)) return
                handleBinaryMessage(bytes)
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                if (!isCurrentSocket(webSocket)) return
                Log.i(TAG, "WebSocket closed ($code): $reason")
                _state.value = WebSocketState.Disconnected(device, reason.ifBlank { null })
                scope.launch { _events.emit("Closed: $reason") }
                cleanup(webSocket)
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                if (!isCurrentSocket(webSocket)) return
                Log.i(TAG, "WebSocket closing ($code): $reason")
                webSocket.close(code, reason)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                if (!isCurrentSocket(webSocket)) return
                Log.e(TAG, "WebSocket failure", t)
                _state.value = WebSocketState.Disconnected(device, t.message)
                scope.launch { _events.emit("Failure: ${t.message}") }
                cleanup(webSocket)
            }
        }

        webSocket = client.newWebSocket(request, listener)
    }

    val isActive: Boolean
        get() = webSocket != null

    fun disconnect(reason: String? = null) {
        val previous = currentDevice
        closeInternal(reason ?: "Manual disconnect")
        _state.value = WebSocketState.Disconnected(previous, reason)
    }

    fun shutdown() {
        disconnect("Shutdown")
        client.dispatcher.executorService.shutdown()
        client.connectionPool.evictAll()
    }

    fun sendPing() {
        webSocket?.let { sendPing(it) }
    }

    override fun driveMotor(motorId: Int, speed: Int) {
        val payload = PuppybotProtocol.drivePayload(motorId, speed, pulses = 0, stepMicros = 0)
        sendCommand(PuppybotProtocol.CMD_DRIVE_MOTOR, payload)
    }

    override fun runMotorPulses(motorId: Int, speed: Int, pulses: Int, stepMicros: Int) {
        val payload = PuppybotProtocol.drivePayload(motorId, speed, pulses, stepMicros)
        sendCommand(PuppybotProtocol.CMD_DRIVE_MOTOR, payload)
    }

    override fun stopMotor(motorId: Int) {
        sendCommand(PuppybotProtocol.CMD_STOP_MOTOR, byteArrayOf((motorId and 0xFF).toByte()))
    }

    override fun stopAllMotors() {
        sendCommand(PuppybotProtocol.CMD_STOP_ALL_MOTORS, byteArrayOf())
    }

    override fun turnServo(servoId: Int, angle: Int, durationMs: Int?) {
        val payload = PuppybotProtocol.servoSetPayload(servoId, angle, durationMs ?: 0)
        sendCommand(PuppybotProtocol.CMD_SERVO_SET, payload)
    }

    override fun driveSteer(throttle: Int, steering: Int) {
        sendCommand(
            PuppybotProtocol.CMD_DRIVE_STEER,
            byteArrayOf(
                throttle.coerceIn(-100, 100).toByte(),
                steering.coerceIn(-100, 100).toByte()
            )
        )
    }

    override fun stopDrive() {
        sendCommand(PuppybotProtocol.CMD_STOP_DRIVE, byteArrayOf())
    }

    override fun armJog(joint: Int, direction: Int, speed: Int) {
        sendCommand(PuppybotProtocol.CMD_ARM_JOG, PuppybotProtocol.armJogPayload(joint, direction, speed))
    }

    override fun armStopJoint(joint: Int) {
        sendCommand(PuppybotProtocol.CMD_ARM_STOP_JOINT, PuppybotProtocol.armStopJointPayload(joint))
    }

    override fun armJoint(joint: Int, angleDeg: Int, speed: Int) {
        sendCommand(PuppybotProtocol.CMD_ARM_JOINT, PuppybotProtocol.armJointPayload(joint, angleDeg, speed))
    }

    override fun armPose(x: Float, y: Float, z: Float, wristDeg: Float, speed: Int) {
        val payload = PuppybotProtocol.armPosePayload(x, y, z, wristDeg, speed)
        sendCommand(PuppybotProtocol.CMD_ARM_POSE, payload)
    }

    override fun armStop() {
        sendCommand(PuppybotProtocol.CMD_ARM_STOP, byteArrayOf())
    }

    override fun requestServoConfig() {
        sendCommand(PuppybotProtocol.CMD_CONFIG_GET, byteArrayOf())
    }

    override fun setServoConfig(config: PuppybotServoConfig) {
        sendCommand(PuppybotProtocol.CMD_CONFIG_SET, PuppybotProtocol.configSetPayload(config))
    }

    override fun setArmTelemetryEnabled(enabled: Boolean) {
        _armTelemetryEnabled.value = enabled
        if (!enabled) {
            _armTelemetry.value = null
        }
        webSocket?.let { sendArmTelemetrySubscription(it, enabled) }
    }

    private fun sendPing(socket: WebSocket) {
        if (!socket.send(ByteString.of(*PuppybotProtocol.PING_FRAME))) {
            Log.w(TAG, "Failed to send CMD_PING")
        } else {
            scope.launch { _events.emit("-> CMD_PING") }
        }
    }

    private fun sendArmTelemetrySubscription(socket: WebSocket, enabled: Boolean) {
        sendCommand(
            socket,
            PuppybotProtocol.CMD_SUBSCRIBE,
            PuppybotProtocol.armTelemetrySubscriptionPayload(enabled)
        )
    }

    private fun handleBinaryMessage(bytes: ByteString) {
        val data = bytes.toByteArray()
        val hex = bytes.hex().chunked(2).joinToString(" ")
        Log.d(TAG, "WS bin <- $hex")

        PuppybotProtocol.parseConfigState(data)?.let { config ->
            _servoConfig.value = config
            scope.launch { _events.emit("Config: steering=${config.steeringServoId} arm=${config.armServoIds.joinToString(",")}") }
            return
        }

        PuppybotProtocol.parseArmTelemetry(data)?.let { telemetry ->
            _armTelemetry.value = telemetry
            return
        }

        scope.launch { _events.emit("Binary: $hex") }
    }

    private fun sendCommand(cmd: Byte, payload: ByteArray) {
        val socket = webSocket ?: run {
            Log.w(TAG, "Attempted to send command $cmd while socket is null")
            return
        }

        sendCommand(socket, cmd, payload)
    }

    private fun sendCommand(socket: WebSocket, cmd: Byte, payload: ByteArray) {
        val frame = PuppybotProtocol.commandFrame(cmd, payload)
        if (!socket.send(ByteString.of(*frame))) {
            Log.w(TAG, "Failed to send command $cmd")
        } else {
            scope.launch { _events.emit("-> cmd=$cmd len=${payload.size}") }
        }
    }

    private fun closeInternal(reason: String?) {
        val ws = webSocket
        if (ws != null) {
            Log.i(TAG, "Closing existing WebSocket: ${reason ?: "no reason"}")
            ws.close(1000, reason)
            cleanup(ws)
        }
        webSocket = null
    }

    private fun isCurrentSocket(socket: WebSocket): Boolean = webSocket == socket

    private fun cleanup(socket: WebSocket) {
        if (webSocket == socket) {
            webSocket = null
            currentDevice = null
        }
    }

    private fun buildWsUrl(device: PuppybotDevice): String? {
        val rawHost = device.host?.hostAddress?.substringBefore('%') ?: return null
        return "ws://${formatWsHost(rawHost)}:${device.port}/ws"
    }

    private fun parseManualTarget(rawHost: String, port: Int): ManualTarget? {
        var host = rawHost.trim()
            .removePrefix("ws://")
            .removePrefix("http://")
            .substringBefore("/")
            .trim()
        if (host.isBlank()) return null

        var parsedPort = port.coerceIn(1, 65535)
        if (host.startsWith("[") && "]" in host) {
            val closing = host.indexOf(']')
            val bracketedHost = host.substring(1, closing)
            val rest = host.substring(closing + 1)
            host = bracketedHost
            if (rest.startsWith(":")) {
                parsedPort = rest.drop(1).toIntOrNull()?.coerceIn(1, 65535) ?: parsedPort
            }
        } else if (host.count { it == ':' } == 1) {
            val rawParsedPort = host.substringAfter(":").toIntOrNull()
            host = host.substringBefore(":")
            if (rawParsedPort != null) {
                parsedPort = rawParsedPort.coerceIn(1, 65535)
            }
        }

        if (host.isBlank()) return null
        return ManualTarget(host, parsedPort, "ws://${formatWsHost(host)}:$parsedPort/ws")
    }

    private fun formatWsHost(rawHost: String): String {
        val host = rawHost.substringBefore('%')
        return if (":" in host && !host.startsWith("[")) "[$host]" else host
    }

    private data class ManualTarget(val host: String, val port: Int, val url: String)
}
