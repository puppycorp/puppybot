package fi.puppycorp.puppybot.ws

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Test
import java.nio.ByteBuffer
import java.nio.ByteOrder

class PuppybotProtocolTest {
    @Test
    fun commandConstantsMatchRustProtocolTable() {
        assertEquals(0x01, PuppybotProtocol.CMD_PING.unsigned())
        assertEquals(0x0D, PuppybotProtocol.CMD_ARM_JOG.unsigned())
        assertEquals(0x0E, PuppybotProtocol.CMD_ARM_STOP_JOINT.unsigned())
        assertEquals(0x19, PuppybotProtocol.CMD_CONFIG_GET.unsigned())
        assertEquals(0x1A, PuppybotProtocol.CMD_CONFIG_SET.unsigned())
        assertEquals(0x1B, PuppybotProtocol.CMD_DRIVE_STEER.unsigned())
        assertEquals(0x1C, PuppybotProtocol.CMD_STOP_DRIVE.unsigned())
        assertEquals(0x1D, PuppybotProtocol.CMD_ARM_JOINT.unsigned())
        assertEquals(0x1E, PuppybotProtocol.CMD_ARM_POSE.unsigned())
        assertEquals(0x1F, PuppybotProtocol.CMD_ARM_STOP.unsigned())
        assertEquals(0x20, PuppybotProtocol.CMD_SERVO_SET.unsigned())
        assertEquals(0x21, PuppybotProtocol.CMD_SUBSCRIBE.unsigned())
        assertEquals(0x07, PuppybotProtocol.MSG_ARM_STATE)
        assertEquals(0x08, PuppybotProtocol.MSG_CONFIG_STATE)
    }

    @Test
    fun parsesConfigStateFrame() {
        val frame = byteArrayOf(0x01, 0x00, 0x08, 0x01, 0x05, 0x02, 0x03, 0x04, 0x06)

        val config = PuppybotProtocol.parseConfigState(frame)
        assertNotNull(config)

        assertEquals(5, config!!.steeringServoId)
        assertEquals(listOf(2, 3, 4, 6), config.armServoIds)
    }

    @Test
    fun parsesArmTelemetryFrame() {
        val fault = "Stall".toByteArray(Charsets.UTF_8)
        val frame = ByteBuffer.allocate(4 + 25 + fault.size + 13)
            .order(ByteOrder.LITTLE_ENDIAN)
            .put(0x01)
            .put(0x00)
            .put(PuppybotProtocol.MSG_ARM_STATE.toByte())
            .put(0x01)
            .put(0x02)
            .put(0x0B)
            .putInt(1234)
            .putInt(1500)
            .putShort((-250).toShort())
            .putInt(-100)
            .putInt(4200)
            .putFloat(45.5f)
            .put(fault.size.toByte())
            .put(fault)
            .put(0x01)
            .putFloat(10.0f)
            .putFloat(20.0f)
            .putFloat(30.0f)
            .array()

        val telemetry = PuppybotProtocol.parseArmTelemetry(frame)
        assertNotNull(telemetry)

        assertEquals(1, telemetry!!.joints.size)
        val joint = telemetry.joints.single()
        assertEquals(2, joint.servoId)
        assertEquals(true, joint.online)
        assertEquals(true, joint.hasFeedback)
        assertEquals(1234, joint.tick)
        assertEquals(1500, joint.targetTick)
        assertEquals(-250, joint.speed)
        assertEquals(-100, joint.limitMin)
        assertEquals(4200, joint.limitMax)
        assertEquals(45.5f, joint.angleDeg ?: 0.0f, 0.001f)
        assertEquals("Stall", joint.fault)
        assertEquals(10.0f, telemetry.coords?.x ?: 0.0f, 0.001f)
        assertEquals(20.0f, telemetry.coords?.y ?: 0.0f, 0.001f)
        assertEquals(30.0f, telemetry.coords?.z ?: 0.0f, 0.001f)
    }

    @Test
    fun jogPressReleaseSendsJogThenStop() {
        val frames = PuppybotProtocol.jogPressReleaseFrames(joint = 2, direction = -1, speed = 300)

        assertEquals(2, frames.size)
        assertArrayEquals(
            byteArrayOf(0x01, 0x0D, 0x04, 0x00, 0x02, 0xFF.toByte(), 0x2C, 0x01),
            frames[0]
        )
        assertArrayEquals(
            byteArrayOf(0x01, 0x0E, 0x01, 0x00, 0x02),
            frames[1]
        )
    }

    private fun Byte.unsigned(): Int = toInt() and 0xFF
}
