package fi.puppycorp.puppybot.control

data class PuppybotServoConfig(
    val steeringServoId: Int = 0,
    val armServoIds: List<Int> = listOf(1, 2, 3, 4)
)

data class PuppybotArmTelemetry(
    val joints: List<PuppybotArmJointTelemetry>,
    val coords: PuppybotArmCoords?
)

data class PuppybotArmJointTelemetry(
    val servoId: Int,
    val online: Boolean,
    val hasFeedback: Boolean,
    val limitReached: Boolean,
    val tick: Int?,
    val targetTick: Int?,
    val speed: Int,
    val limitMin: Int,
    val limitMax: Int,
    val angleDeg: Float?,
    val fault: String
)

data class PuppybotArmCoords(
    val x: Float,
    val y: Float,
    val z: Float
)

interface PuppybotCommandSender {
    fun driveMotor(motorId: Int, speed: Int)
    fun stopMotor(motorId: Int)
    fun stopAllMotors()
    fun turnServo(servoId: Int, angle: Int, durationMs: Int? = null)
    fun runMotorPulses(motorId: Int, speed: Int, pulses: Int, stepMicros: Int)
    fun driveSteer(throttle: Int, steering: Int) {}
    fun stopDrive() {}
    fun armJog(joint: Int, direction: Int, speed: Int) {}
    fun armStopJoint(joint: Int) {}
    fun armJoint(joint: Int, angleDeg: Int, speed: Int) {}
    fun armPose(x: Float, y: Float, z: Float, wristDeg: Float, speed: Int) {}
    fun armStop() {}
    fun requestServoConfig() {}
    fun setServoConfig(config: PuppybotServoConfig) {}
    fun setArmTelemetryEnabled(enabled: Boolean) {}
}
