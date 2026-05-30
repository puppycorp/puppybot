package fi.puppycorp.puppybot.ble

import android.annotation.SuppressLint
import android.Manifest
import android.bluetooth.BluetoothAdapter
import android.bluetooth.BluetoothDevice
import android.bluetooth.BluetoothGatt
import android.bluetooth.BluetoothGattCallback
import android.bluetooth.BluetoothGattCharacteristic
import android.bluetooth.BluetoothGattService
import android.bluetooth.BluetoothManager
import android.bluetooth.BluetoothProfile
import android.bluetooth.BluetoothStatusCodes
import android.bluetooth.le.BluetoothLeScanner
import android.bluetooth.le.ScanCallback
import android.bluetooth.le.ScanFilter
import android.bluetooth.le.ScanResult
import android.bluetooth.le.ScanSettings
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import android.os.ParcelUuid
import android.util.Log
import fi.puppycorp.puppybot.control.PuppybotCommandSender
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.UUID

private const val TAG = "PuppybotBle"
private const val PROTOCOL_VERSION: Byte = 0x01
private const val CMD_PING: Int = 0x01
private const val CMD_DRIVE_MOTOR: Int = 0x02
private const val CMD_STOP_MOTOR: Int = 0x03
private const val CMD_STOP_ALL_MOTORS: Int = 0x04
private const val CMD_DRIVE_STEER: Int = 0x1B
private const val CMD_STOP_DRIVE: Int = 0x1C
private const val CMD_ARM_JOINT: Int = 0x1D
private const val CMD_ARM_POSE: Int = 0x1E
private const val CMD_ARM_STOP: Int = 0x1F
private const val CMD_SERVO_SET: Int = 0x20

private val SERVICE_UUID: UUID = UUID.fromString("000000FF-0000-1000-8000-00805F9B34FB")
private val CHARACTERISTIC_UUID: UUID = UUID.fromString("0000FF01-0000-1000-8000-00805F9B34FB")

sealed class BleState(open val device: PuppybotBleDevice?) {
    data class Disconnected(override val device: PuppybotBleDevice?, val reason: String? = null) : BleState(device)
    data class Connecting(override val device: PuppybotBleDevice) : BleState(device)
    data class Connected(override val device: PuppybotBleDevice) : BleState(device)
}

data class PuppybotBleDevice(
    val device: BluetoothDevice,
    val name: String,
    val address: String,
    val rssi: Int?
)

class PuppybotBleController(context: Context) : PuppybotCommandSender {
    private val appContext = context.applicationContext
    private val bluetoothManager = appContext.getSystemService(Context.BLUETOOTH_SERVICE) as BluetoothManager
    private val adapter: BluetoothAdapter? = bluetoothManager.adapter
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    private val _devices = MutableStateFlow<List<PuppybotBleDevice>>(emptyList())
    val devices: StateFlow<List<PuppybotBleDevice>> = _devices

    private val _state = MutableStateFlow<BleState>(BleState.Disconnected(null))
    val state: StateFlow<BleState> = _state

    private val _events = MutableSharedFlow<String>(extraBufferCapacity = 16, onBufferOverflow = BufferOverflow.DROP_OLDEST)
    val events: SharedFlow<String> = _events

    private var scanner: BluetoothLeScanner? = null
    private var scanCallback: ScanCallback? = null
    private var gatt: BluetoothGatt? = null
    private var controlCharacteristic: BluetoothGattCharacteristic? = null
    private val writeMutex = Mutex()

    private fun hasBluetoothConnectPermission(): Boolean {
        return Build.VERSION.SDK_INT < Build.VERSION_CODES.S ||
            appContext.checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED
    }

    private fun emitMissingBluetoothConnectPermission(operation: String) {
        scope.launch { _events.emit("Missing Bluetooth permission for $operation") }
    }

    @SuppressLint("MissingPermission")
    fun startScan() {
        val adapter = adapter ?: run {
            Log.w(TAG, "Bluetooth adapter unavailable")
            return
        }
        if (!adapter.isEnabled) {
            Log.w(TAG, "Bluetooth disabled")
            return
        }
        if (scanCallback != null) return

        scanner = adapter.bluetoothLeScanner ?: run {
            Log.w(TAG, "BluetoothLeScanner unavailable")
            return
        }

        val filter = ScanFilter.Builder()
            .setServiceUuid(ParcelUuid(SERVICE_UUID))
            .build()
        val settings = ScanSettings.Builder()
            .setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY)
            .build()

        val callback = object : ScanCallback() {
            override fun onScanResult(callbackType: Int, result: ScanResult) {
                handleScanResult(result)
            }

            override fun onBatchScanResults(results: MutableList<ScanResult>) {
                results.forEach { handleScanResult(it) }
            }

            override fun onScanFailed(errorCode: Int) {
                scope.launch { _events.emit("Scan failed: $errorCode") }
                stopScan()
            }
        }

        scanCallback = callback
        scanner?.startScan(listOf(filter), settings, callback)
        scope.launch { _events.emit("BLE scan started") }
    }

    @SuppressLint("MissingPermission")
    fun stopScan() {
        val callback = scanCallback ?: return
        scanner?.stopScan(callback)
        scanCallback = null
        scope.launch { _events.emit("BLE scan stopped") }
    }

    fun shutdown() {
        try {
            stopScan()
        } catch (t: SecurityException) {
            Log.w(TAG, "stopScan without permission", t)
        }
        try {
            disconnect("Shutdown")
        } catch (t: SecurityException) {
            Log.w(TAG, "disconnect without permission", t)
        }
        scope.cancel()
    }

    @SuppressLint("MissingPermission")
    fun connectTo(target: PuppybotBleDevice) {
        val current = _state.value.device
        if (current?.address == target.address && _state.value is BleState.Connected) {
            return
        }
        disconnect("Switching target")
        stopScan()
        _state.value = BleState.Connecting(target)
        scope.launch { _events.emit("Connecting to ${target.name}") }
        openGatt(target.device)
    }

    @SuppressLint("MissingPermission")
    fun disconnect(reason: String? = null) {
        val prev = _state.value.device
        gatt?.close()
        gatt = null
        controlCharacteristic = null
        if (_state.value !is BleState.Disconnected || reason != null) {
            _state.value = BleState.Disconnected(prev, reason)
        }
    }

    val isConnected: Boolean
        get() = _state.value is BleState.Connected

    fun sendPing() {
        sendCommand(CMD_PING, byteArrayOf())
    }

    override fun driveMotor(motorId: Int, speed: Int) {
        val payload = buildDrivePayload(motorId, speed, pulses = 0, stepMicros = 0)
        sendCommand(CMD_DRIVE_MOTOR, payload)
    }

    override fun stopMotor(motorId: Int) {
        sendCommand(CMD_STOP_MOTOR, byteArrayOf((motorId and 0xFF).toByte()))
    }

    override fun stopAllMotors() {
        sendCommand(CMD_STOP_ALL_MOTORS, byteArrayOf())
    }

    override fun turnServo(servoId: Int, angle: Int, durationMs: Int?) {
        val payload = buildServoSetPayload(servoId, angle, durationMs ?: 0)
        sendCommand(CMD_SERVO_SET, payload)
    }

    override fun runMotorPulses(motorId: Int, speed: Int, pulses: Int, stepMicros: Int) {
        val payload = buildDrivePayload(motorId, speed, pulses, stepMicros)
        sendCommand(CMD_DRIVE_MOTOR, payload)
    }

    override fun driveSteer(throttle: Int, steering: Int) {
        sendCommand(
            CMD_DRIVE_STEER,
            byteArrayOf(
                throttle.coerceIn(-100, 100).toByte(),
                steering.coerceIn(-100, 100).toByte()
            )
        )
    }

    override fun stopDrive() {
        sendCommand(CMD_STOP_DRIVE, byteArrayOf())
    }

    override fun armJoint(joint: Int, angleDeg: Int, speed: Int) {
        val payload = ByteArray(5)
        payload[0] = (joint.coerceIn(0, 3) and 0xFF).toByte()
        writeI16Le(payload, 1, angleDeg.coerceIn(-180, 180))
        writeU16Le(payload, 3, speed.coerceIn(0, 0xFFFF))
        sendCommand(CMD_ARM_JOINT, payload)
    }

    override fun armPose(x: Float, y: Float, z: Float, wristDeg: Float, speed: Int) {
        val payload = ByteBuffer.allocate(18)
            .order(ByteOrder.LITTLE_ENDIAN)
            .putFloat(x)
            .putFloat(y)
            .putFloat(z)
            .putFloat(wristDeg)
            .putShort(speed.coerceIn(0, 0xFFFF).toShort())
            .array()
        sendCommand(CMD_ARM_POSE, payload)
    }

    override fun armStop() {
        sendCommand(CMD_ARM_STOP, byteArrayOf())
    }

    private fun buildDrivePayload(
        motorId: Int,
        speed: Int,
        pulses: Int,
        stepMicros: Int,
        angle: Int = 0
    ): ByteArray {
        val sanitizedMotor = motorId.coerceIn(0, 255)
        val sanitizedSpeed = speed.coerceIn(-128, 127)
        val sanitizedPulses = pulses.coerceIn(0, 0xFFFF)
        val sanitizedStepMicros = stepMicros.coerceIn(0, 0xFFFF)
        val sanitizedAngle = angle.coerceIn(0, 0xFFFF)
        return byteArrayOf(
            (sanitizedMotor and 0xFF).toByte(),
            0x00,
            sanitizedSpeed.toByte(),
            (sanitizedPulses and 0xFF).toByte(),
            ((sanitizedPulses shr 8) and 0xFF).toByte(),
            (sanitizedStepMicros and 0xFF).toByte(),
            ((sanitizedStepMicros shr 8) and 0xFF).toByte(),
            (sanitizedAngle and 0xFF).toByte(),
            ((sanitizedAngle shr 8) and 0xFF).toByte()
        )
    }

    private fun buildServoSetPayload(servoId: Int, angle: Int, durationMs: Int): ByteArray {
        val payload = ByteArray(5)
        payload[0] = (servoId.coerceIn(0, 255) and 0xFF).toByte()
        writeU16Le(payload, 1, angle.coerceIn(0, 180))
        writeU16Le(payload, 3, durationMs.coerceIn(0, 0xFFFF))
        return payload
    }

    private fun writeI16Le(payload: ByteArray, offset: Int, value: Int) {
        payload[offset] = (value and 0xFF).toByte()
        payload[offset + 1] = ((value shr 8) and 0xFF).toByte()
    }

    private fun writeU16Le(payload: ByteArray, offset: Int, value: Int) {
        payload[offset] = (value and 0xFF).toByte()
        payload[offset + 1] = ((value shr 8) and 0xFF).toByte()
    }

    private fun sendCommand(cmd: Int, payload: ByteArray) {
        if (_state.value !is BleState.Connected) {
            scope.launch { _events.emit("Cannot send cmd=$cmd while disconnected") }
            return
        }
        val frame = ByteArray(4 + payload.size)
        frame[0] = PROTOCOL_VERSION
        frame[1] = cmd.toByte()
        frame[2] = (payload.size and 0xFF).toByte()
        frame[3] = ((payload.size shr 8) and 0xFF).toByte()
        payload.copyInto(frame, destinationOffset = 4)
        scope.launch {
            writeFrame(frame)
            _events.emit("-> BLE cmd=$cmd len=${payload.size}")
        }
    }

    @SuppressLint("MissingPermission")
    private fun openGatt(device: BluetoothDevice) {
        gatt = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            device.connectGatt(appContext, false, gattCallback, BluetoothDevice.TRANSPORT_LE)
        } else {
            device.connectGatt(appContext, false, gattCallback)
        }
    }

    private val gattCallback = object : BluetoothGattCallback() {
        @SuppressLint("MissingPermission")
        override fun onConnectionStateChange(gatt: BluetoothGatt, status: Int, newState: Int) {
            when (newState) {
                BluetoothProfile.STATE_CONNECTED -> {
                    if (!hasBluetoothConnectPermission()) {
                        emitMissingBluetoothConnectPermission("service discovery")
                        val device = _state.value.device
                        _state.value = BleState.Disconnected(device, "Bluetooth permission missing")
                        cleanupGatt()
                        return
                    }
                    scope.launch { _events.emit("Gatt connected, discovering services") }
                    try {
                        gatt.discoverServices()
                    } catch (t: SecurityException) {
                        Log.w(TAG, "discoverServices without permission", t)
                        val device = _state.value.device
                        _state.value = BleState.Disconnected(device, "Bluetooth permission missing")
                        cleanupGatt()
                    }
                }
                BluetoothProfile.STATE_DISCONNECTED -> {
                    scope.launch { _events.emit("Gatt disconnected: status=$status") }
                    val device = _state.value.device
                    _state.value = BleState.Disconnected(device, "Disconnected")
                    cleanupGatt()
                }
            }
        }

        override fun onServicesDiscovered(gatt: BluetoothGatt, status: Int) {
            if (status != BluetoothGatt.GATT_SUCCESS) {
                scope.launch { _events.emit("Service discovery failed: $status") }
                val device = _state.value.device
                _state.value = BleState.Disconnected(device, "Service discovery failed")
                cleanupGatt()
                return
            }

            val service: BluetoothGattService? = gatt.getService(SERVICE_UUID)
            val characteristic: BluetoothGattCharacteristic? = service?.getCharacteristic(CHARACTERISTIC_UUID)
            if (service == null || characteristic == null) {
                scope.launch { _events.emit("Control characteristic missing") }
                val device = _state.value.device
                _state.value = BleState.Disconnected(device, "Characteristic missing")
                cleanupGatt()
                return
            }

            controlCharacteristic = characteristic
            _state.value.device?.let { _state.value = BleState.Connected(it) }
            scope.launch { _events.emit("BLE connected") }
        }

        override fun onCharacteristicWrite(gatt: BluetoothGatt, characteristic: BluetoothGattCharacteristic, status: Int) {
            if (status != BluetoothGatt.GATT_SUCCESS) {
                scope.launch { _events.emit("Write failed: $status") }
            }
        }
    }

    @SuppressLint("MissingPermission")
    private fun cleanupGatt() {
        if (!hasBluetoothConnectPermission()) {
            gatt = null
            controlCharacteristic = null
            return
        }
        try {
            gatt?.close()
        } catch (t: SecurityException) {
            Log.w(TAG, "close without permission", t)
        }
        gatt = null
        controlCharacteristic = null
    }

    @SuppressLint("MissingPermission")
    private fun handleScanResult(result: ScanResult) {
        val device = result.device ?: return
        val name = result.scanRecord?.deviceName
            ?: if (hasBluetoothConnectPermission()) device.name else null
            ?: device.address
        val updated = _devices.value.toMutableList()
        val index = updated.indexOfFirst { it.address == device.address }
        val entry = PuppybotBleDevice(device, name, device.address, result.rssi)
        if (index >= 0) {
            updated[index] = entry
        } else {
            updated += entry
        }
        _devices.value = updated.sortedBy { it.name.lowercase() }
    }

    @SuppressLint("MissingPermission")
    private suspend fun writeFrame(frame: ByteArray) {
        if (!hasBluetoothConnectPermission()) {
            _events.emit("Missing Bluetooth permission for Gatt write")
            return
        }
        val gatt = gatt ?: run {
            _events.emit("writeFrame while gatt null")
            return
        }
        val characteristic = controlCharacteristic ?: run {
            _events.emit("writeFrame while characteristic null")
            return
        }

        writeMutex.withLock {
            characteristic.writeType = BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT
            val success = try {
                if (Build.VERSION.SDK_INT >= 33) {
                    gatt.writeCharacteristic(characteristic, frame, BluetoothGattCharacteristic.WRITE_TYPE_DEFAULT) == BluetoothStatusCodes.SUCCESS
                } else {
                    @Suppress("DEPRECATION")
                    characteristic.value = frame
                    @Suppress("DEPRECATION")
                    gatt.writeCharacteristic(characteristic)
                }
            } catch (t: SecurityException) {
                Log.w(TAG, "writeCharacteristic without permission", t)
                false
            }
            if (!success) {
                _events.emit("Gatt write enqueue failed")
            }
        }
    }
}
