package fi.puppycorp.puppybot.control

data class PuppybotServoConfig(
    val steeringServoId: Int = 0,
    val armServoIds: List<Int> = listOf(1, 2, 3, 4)
)

interface PuppybotCommandSender {
    fun driveMotor(motorId: Int, speed: Int)
    fun stopMotor(motorId: Int)
    fun stopAllMotors()
    fun turnServo(servoId: Int, angle: Int, durationMs: Int? = null)
    fun runMotorPulses(motorId: Int, speed: Int, pulses: Int, stepMicros: Int)
    fun driveSteer(throttle: Int, steering: Int) {}
    fun stopDrive() {}
    fun armJoint(joint: Int, angleDeg: Int, speed: Int) {}
    fun armPose(x: Float, y: Float, z: Float, wristDeg: Float, speed: Int) {}
    fun armStop() {}
    fun requestServoConfig() {}
    fun setServoConfig(config: PuppybotServoConfig) {}
}
