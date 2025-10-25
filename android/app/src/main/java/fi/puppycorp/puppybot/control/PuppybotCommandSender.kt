package fi.puppycorp.puppybot.control

interface PuppybotCommandSender {
    fun driveMotor(motorId: Int, speed: Int)
    fun stopMotor(motorId: Int)
    fun stopAllMotors()
    fun turnServo(servoId: Int, angle: Int, durationMs: Int? = null)
    fun runMotorPulses(motorId: Int, speed: Int, pulses: Int, stepMicros: Int)
}
