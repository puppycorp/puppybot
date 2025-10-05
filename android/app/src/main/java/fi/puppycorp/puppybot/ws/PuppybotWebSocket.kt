package fi.puppycorp.puppybot.ws

import android.util.Log
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

class PuppybotWebSocket {
    companion object {
        private const val TAG = "PuppybotWebSocket"
        private const val PROTOCOL_VERSION: Byte = 0x01
        private const val CMD_PING: Byte = 0x01
        private const val CMD_DRIVE_MOTOR: Byte = 0x02
        private const val CMD_STOP_MOTOR: Byte = 0x03
        private const val CMD_STOP_ALL_MOTORS: Byte = 0x04
        private const val CMD_TURN_SERVO: Byte = 0x05
        private val PING_FRAME = byteArrayOf(
            PROTOCOL_VERSION,
            CMD_PING,
            0x00,
            0x00
        )
    }

    private val client: OkHttpClient = OkHttpClient.Builder()
        .pingInterval(30, TimeUnit.SECONDS)
        .build()

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val _state = MutableStateFlow<WebSocketState>(WebSocketState.Disconnected(device = null))
    val state: StateFlow<WebSocketState> = _state

    private val _events = MutableSharedFlow<String>(extraBufferCapacity = 16)
    val events: SharedFlow<String> = _events

    @Volatile
    private var webSocket: WebSocket? = null
    @Volatile
    private var currentDevice: PuppybotDevice? = null

    fun connectTo(device: PuppybotDevice) {
        val url = buildWsUrl(device) ?: run {
            Log.w(TAG, "Cannot build WS URL for ${device.name}")
            return
        }

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
                Log.i(TAG, "WebSocket opened -> ${device.name}")
                _state.value = WebSocketState.Connected(device, url)
                scope.launch { _events.emit("Connected to ${device.name}") }
                sendPing(webSocket)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                Log.d(TAG, "WS text <- $text")
                scope.launch { _events.emit("Text: $text") }
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                val hex = bytes.hex().chunked(2).joinToString(" ")
                Log.d(TAG, "WS bin <- $hex")
                scope.launch { _events.emit("Binary: $hex") }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.i(TAG, "WebSocket closed ($code): $reason")
                _state.value = WebSocketState.Disconnected(device, reason.ifBlank { null })
                scope.launch { _events.emit("Closed: $reason") }
                cleanup(webSocket)
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                Log.i(TAG, "WebSocket closing ($code): $reason")
                webSocket.close(code, reason)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
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

    fun driveMotor(motorId: Int, speed: Int) {
        val payload = byteArrayOf(
            (motorId and 0xFF).toByte(),
            speed.coerceIn(-128, 127).toByte()
        )
        sendCommand(CMD_DRIVE_MOTOR, payload)
    }

    fun stopMotor(motorId: Int) {
        sendCommand(CMD_STOP_MOTOR, byteArrayOf((motorId and 0xFF).toByte()))
    }

    fun stopAllMotors() {
        sendCommand(CMD_STOP_ALL_MOTORS, byteArrayOf())
    }

    fun turnServo(angle: Int) {
        val sanitized = angle.coerceIn(0, 180)
        val payload = byteArrayOf(
            (sanitized and 0xFF).toByte(),
            ((sanitized shr 8) and 0xFF).toByte()
        )
        sendCommand(CMD_TURN_SERVO, payload)
    }

    private fun sendPing(socket: WebSocket) {
        if (!socket.send(ByteString.of(*PING_FRAME))) {
            Log.w(TAG, "Failed to send CMD_PING")
        } else {
            scope.launch { _events.emit("-> CMD_PING") }
        }
    }

    private fun sendCommand(cmd: Byte, payload: ByteArray) {
        val socket = webSocket ?: run {
            Log.w(TAG, "Attempted to send command $cmd while socket is null")
            return
        }

        val frame = ByteArray(4 + payload.size)
        frame[0] = PROTOCOL_VERSION
        frame[1] = cmd
        frame[2] = (payload.size and 0xFF).toByte()
        frame[3] = ((payload.size shr 8) and 0xFF).toByte()
        payload.copyInto(frame, destinationOffset = 4)

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

    private fun cleanup(socket: WebSocket) {
        if (webSocket == socket) {
            webSocket = null
            currentDevice = null
        }
    }

    private fun buildWsUrl(device: PuppybotDevice): String? {
        val rawHost = device.host?.hostAddress?.substringBefore('%') ?: return null
        val host = if (":" in rawHost) "[$rawHost]" else rawHost
        return "ws://$host:${device.port}/ws"
    }
}
