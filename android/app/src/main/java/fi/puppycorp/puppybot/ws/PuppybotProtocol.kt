package fi.puppycorp.puppybot.ws

import fi.puppycorp.puppybot.control.PuppybotArmCoords
import fi.puppycorp.puppybot.control.PuppybotArmJointTelemetry
import fi.puppycorp.puppybot.control.PuppybotArmTelemetry
import fi.puppycorp.puppybot.control.PuppybotServoConfig
import java.nio.ByteBuffer
import java.nio.ByteOrder

internal object PuppybotProtocol {
    const val PROTOCOL_VERSION: Byte = 0x01

    const val CMD_PING: Byte = 0x01
    const val CMD_DRIVE_MOTOR: Byte = 0x02
    const val CMD_STOP_MOTOR: Byte = 0x03
    const val CMD_STOP_ALL_MOTORS: Byte = 0x04
    const val CMD_ARM_JOG: Byte = 0x0D
    const val CMD_ARM_STOP_JOINT: Byte = 0x0E
    const val CMD_CONFIG_GET: Byte = 0x19
    const val CMD_CONFIG_SET: Byte = 0x1A
    const val CMD_DRIVE_STEER: Byte = 0x1B
    const val CMD_STOP_DRIVE: Byte = 0x1C
    const val CMD_ARM_JOINT: Byte = 0x1D
    const val CMD_ARM_POSE: Byte = 0x1E
    const val CMD_ARM_STOP: Byte = 0x1F
    const val CMD_SERVO_SET: Byte = 0x20
    const val CMD_SUBSCRIBE: Byte = 0x21

    const val SUBSCRIPTION_ARM_STATE: Byte = 0x01

    const val MSG_ARM_STATE: Int = 0x07
    const val MSG_CONFIG_STATE: Int = 0x08
    const val CONFIG_VERSION: Byte = 0x01

    val PING_FRAME: ByteArray = commandFrame(CMD_PING, byteArrayOf())

    fun commandFrame(cmd: Byte, payload: ByteArray): ByteArray {
        val frame = ByteArray(4 + payload.size)
        frame[0] = PROTOCOL_VERSION
        frame[1] = cmd
        frame[2] = (payload.size and 0xFF).toByte()
        frame[3] = ((payload.size shr 8) and 0xFF).toByte()
        payload.copyInto(frame, destinationOffset = 4)
        return frame
    }

    fun drivePayload(
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

    fun servoSetPayload(servoId: Int, angle: Int, durationMs: Int): ByteArray {
        val payload = ByteArray(5)
        payload[0] = (servoId.coerceIn(0, 255) and 0xFF).toByte()
        writeU16Le(payload, 1, angle.coerceIn(0, 180))
        writeU16Le(payload, 3, durationMs.coerceIn(0, 0xFFFF))
        return payload
    }

    fun armJogPayload(joint: Int, direction: Int, speed: Int): ByteArray {
        val payload = ByteArray(4)
        payload[0] = (joint.coerceIn(0, 3) and 0xFF).toByte()
        payload[1] = direction.coerceIn(-1, 1).toByte()
        writeU16Le(payload, 2, speed.coerceIn(0, 0xFFFF))
        return payload
    }

    fun armStopJointPayload(joint: Int): ByteArray {
        return byteArrayOf((joint.coerceIn(0, 3) and 0xFF).toByte())
    }

    fun armJointPayload(joint: Int, angleDeg: Int, speed: Int): ByteArray {
        val payload = ByteArray(5)
        payload[0] = (joint.coerceIn(0, 3) and 0xFF).toByte()
        writeI16Le(payload, 1, angleDeg.coerceIn(-180, 180))
        writeU16Le(payload, 3, speed.coerceIn(0, 0xFFFF))
        return payload
    }

    fun armPosePayload(x: Float, y: Float, z: Float, wristDeg: Float, speed: Int): ByteArray {
        return ByteBuffer.allocate(18)
            .order(ByteOrder.LITTLE_ENDIAN)
            .putFloat(x)
            .putFloat(y)
            .putFloat(z)
            .putFloat(wristDeg)
            .putShort(speed.coerceIn(0, 0xFFFF).toShort())
            .array()
    }

    fun configSetPayload(config: PuppybotServoConfig): ByteArray {
        val armIds = (config.armServoIds + listOf(1, 2, 3, 4)).take(4)
        return byteArrayOf(
            CONFIG_VERSION,
            (config.steeringServoId.coerceIn(0, 255) and 0xFF).toByte(),
            (armIds[0].coerceIn(0, 255) and 0xFF).toByte(),
            (armIds[1].coerceIn(0, 255) and 0xFF).toByte(),
            (armIds[2].coerceIn(0, 255) and 0xFF).toByte(),
            (armIds[3].coerceIn(0, 255) and 0xFF).toByte()
        )
    }

    fun armTelemetrySubscriptionPayload(enabled: Boolean): ByteArray {
        return byteArrayOf(SUBSCRIPTION_ARM_STATE, (if (enabled) 1 else 0).toByte())
    }

    fun jogPressReleaseFrames(joint: Int, direction: Int, speed: Int): List<ByteArray> {
        return listOf(
            commandFrame(CMD_ARM_JOG, armJogPayload(joint, direction, speed)),
            commandFrame(CMD_ARM_STOP_JOINT, armStopJointPayload(joint))
        )
    }

    fun parseConfigState(data: ByteArray): PuppybotServoConfig? {
        if (data.size < 9) return null
        if ((data[2].toInt() and 0xFF) != MSG_CONFIG_STATE || data[3] != CONFIG_VERSION) return null
        return PuppybotServoConfig(
            steeringServoId = data[4].toInt() and 0xFF,
            armServoIds = listOf(
                data[5].toInt() and 0xFF,
                data[6].toInt() and 0xFF,
                data[7].toInt() and 0xFF,
                data[8].toInt() and 0xFF
            )
        )
    }

    fun parseArmTelemetry(data: ByteArray): PuppybotArmTelemetry? {
        return try {
            if (data.size < 4 || (data[2].toInt() and 0xFF) != MSG_ARM_STATE) return null

            val buffer = ByteBuffer.wrap(data).order(ByteOrder.LITTLE_ENDIAN)
            buffer.position(3)
            val jointCount = buffer.get().toInt() and 0xFF
            val joints = mutableListOf<PuppybotArmJointTelemetry>()
            repeat(jointCount) {
                if (buffer.remaining() < 25) return null
                val servoId = buffer.get().toInt() and 0xFF
                val flags = buffer.get().toInt() and 0xFF
                val tick = buffer.int
                val targetTick = buffer.int
                val speed = buffer.short.toInt()
                val limitMin = buffer.int
                val limitMax = buffer.int
                val angleDeg = buffer.float
                val faultLength = buffer.get().toInt() and 0xFF
                if (buffer.remaining() < faultLength) return null
                val faultBytes = ByteArray(faultLength)
                buffer.get(faultBytes)
                val hasFeedback = (flags and 0x02) != 0
                val hasTarget = (flags and 0x08) != 0
                joints += PuppybotArmJointTelemetry(
                    servoId = servoId,
                    online = (flags and 0x01) != 0,
                    hasFeedback = hasFeedback,
                    limitReached = (flags and 0x04) != 0,
                    tick = if (hasFeedback) tick else null,
                    targetTick = if (hasTarget) targetTick else null,
                    speed = speed,
                    limitMin = limitMin,
                    limitMax = limitMax,
                    angleDeg = if (hasFeedback) angleDeg else null,
                    fault = String(faultBytes, Charsets.UTF_8)
                )
            }

            val coords = if (buffer.remaining() >= 13) {
                val poseFlags = buffer.get().toInt() and 0xFF
                val x = buffer.float
                val y = buffer.float
                val z = buffer.float
                if ((poseFlags and 0x01) != 0) PuppybotArmCoords(x, y, z) else null
            } else {
                null
            }

            PuppybotArmTelemetry(joints = joints, coords = coords)
        } catch (_: RuntimeException) {
            null
        }
    }

    private fun writeI16Le(payload: ByteArray, offset: Int, value: Int) {
        payload[offset] = (value and 0xFF).toByte()
        payload[offset + 1] = ((value shr 8) and 0xFF).toByte()
    }

    private fun writeU16Le(payload: ByteArray, offset: Int, value: Int) {
        payload[offset] = (value and 0xFF).toByte()
        payload[offset + 1] = ((value shr 8) and 0xFF).toByte()
    }
}
