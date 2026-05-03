export type Bot = {
	id: string
	version: string
	variant: string
	connected: boolean
	name?: string
	ip?: string
	clientId?: string
}

export type MotorPwmConfig = {
	pin: number
	channel: number
	freqHz: number
	minUs: number
	maxUs: number
	neutralUs?: number
	invert?: boolean
}

export type SmartServoBusConfig = {
	uartPort: number
	txPin: number
	rxPin: number
	baudRate?: number
}

export type MotorHBridgeConfig = {
	in1: number
	in2: number
	brakeMode?: boolean
}

export type MotorAnalogFeedbackConfig = {
	adcPin: number
	adcMin: number
	adcMax: number
	degMin: number
	degMax: number
}

export type MotorConfig = {
	nodeId: number
	type: "angle" | "continuous" | "hbridge" | "smart"
	name?: string
	timeoutMs?: number
	maxSpeed?: number
	limitDegMin?: number
	limitDegMax?: number
	pollStatus?: boolean
	pwm?: MotorPwmConfig
	smart?: SmartServoBusConfig
	hbridge?: MotorHBridgeConfig
	analog?: MotorAnalogFeedbackConfig
}

export type ArmJointConfig = {
	motorId: number
	sign?: number
	offsetDeg?: number
}

export type ArmConfig = {
	jointCount: number
	l1: number
	l2: number
	z0: number
	joints?: ArmJointConfig[]
}

type DriveMotor = {
	type: "drive"
	botId: string
	motorId: number
	speed: number
	motorType?: "dc" | "servo"
	steps?: number
	stepTimeMicros?: number
	angle?: number
}

type Stop = {
	type: "stop"
	botId: string
}

type StopAllMotors = {
	type: "stopAllMotors"
	botId: string
}

type TurnServo = {
	type: "turnServo"
	botId: string
	servoId: number
	angle: number
	durationMs?: number
}

type ArmMove = {
	type: "armMove"
	botId: string
	x: number
	y: number
	z: number
	elbowUp?: boolean
	durationMs?: number
}

export type ArmJointState = {
	servoId: number
	online: boolean
	hasFeedback: boolean
	limitReached: boolean
	hasTarget: boolean
	hasFault: boolean
	tick: number
	targetTick: number | null
	speed: number
	limitMin: number
	limitMax: number
	angleDeg: number | null
	fault: string
}

export type ArmState = {
	joints: ArmJointState[]
	poseValid: boolean
	coordsMm: { x: number; y: number; z: number } | null
}

type ArmSetSpeed = {
	type: "armSetSpeed"
	botId: string
	speed: number
}

type ArmJog = {
	type: "armJog"
	botId: string
	joint: number
	direction: -1 | 0 | 1
	speed: number
}

type ArmStopJoint = {
	type: "armStopJoint"
	botId: string
	joint: number
}

type ArmStopAll = {
	type: "armStopAll"
	botId: string
}

type ArmGotoTicks = {
	type: "armGotoTicks"
	botId: string
	speed: number
	ticks: [number, number, number, number]
}

type ArmGotoAngles = {
	type: "armGotoAngles"
	botId: string
	speed: number
	anglesDeg: [number, number, number, number]
}

type ArmGotoCoords = {
	type: "armGotoCoords"
	botId: string
	speed: number
	x: number
	y: number
	z: number
}

type ArmHold = {
	type: "armHold"
	botId: string
	speed: number
}

type ArmSetJointTick = {
	type: "armSetJointTick"
	botId: string
	joint: number
	speed: number
	tick: number
}

type ArmSetTickLimits = {
	type: "armSetTickLimits"
	botId: string
	joint: number
	min: number
	max: number
}

type ArmSetTickLimitsEnabled = {
	type: "armSetTickLimitsEnabled"
	botId: string
	joint: number
	enabled: boolean
}

type ArmMoveRelative = {
	type: "armMoveRelative"
	botId: string
	speed: number
	dx: number
	dy: number
}

type ArmClearFaults = {
	type: "armClearFaults"
	botId: string
	joint?: number
}

type UpdateConfig = {
	type: "updateConfig"
	botId: string
	motors: MotorConfig[]
	arm?: ArmConfig | null
	templateKey?: string | null
}

type SmartbusScan = {
	type: "smartbusScan"
	botId: string
	uartPort: number
	startId: number
	endId: number
}

type SmartbusSetId = {
	type: "smartbusSetId"
	botId: string
	uartPort: number
	oldId: number
	newId: number
}

export type MsgToServer =
	| DriveMotor
	| Stop
	| StopAllMotors
	| TurnServo
	| ArmMove
	| ArmSetSpeed
	| ArmJog
	| ArmStopJoint
	| ArmStopAll
	| ArmGotoTicks
	| ArmGotoAngles
	| ArmGotoCoords
	| ArmHold
	| ArmSetJointTick
	| ArmSetTickLimits
	| ArmSetTickLimitsEnabled
	| ArmMoveRelative
	| ArmClearFaults
	| SmartbusScan
	| SmartbusSetId
	| UpdateConfig

export type BotConnected = {
	type: "botConnected"
	botId: string
	clientId?: string
}

export type BotDisconnected = {
	type: "botDisconnected"
	botId: string
}

export type BotInfo = {
	type: "botInfo"
	botId: string
	version: string
	variant: string
	name: string
	ip: string
	clientId: string
}

export type Ping = {
	type: "ping"
}

export type ConfigBroadcast = {
	type: "config"
	botId: string
	motors: MotorConfig[]
	arm?: ArmConfig | null
	templateKey?: string | null
}

export type MotorStateEntry = {
	motorId: number
	valid: boolean
	wheelMode: boolean
	positionDeg: number | null
	positionRaw: number | null
}

export type MotorStateBroadcast = {
	type: "motorState"
	botId: string
	motors: MotorStateEntry[]
}

export type SmartbusScanBroadcast = {
	type: "smartbusScan"
	botId: string
	uartPort: number
	startId: number
	endId: number
	foundIds: number[]
}

export type SmartbusSetIdBroadcast = {
	type: "smartbusSetId"
	botId: string
	uartPort: number
	oldId: number
	newId: number
	status: number
}

export type ArmStateBroadcast = {
	type: "armState"
	botId: string
	state: ArmState
}

export type MsgToUi =
	| BotConnected
	| BotDisconnected
	| BotInfo
	| ConfigBroadcast
	| MotorStateBroadcast
	| ArmStateBroadcast
	| SmartbusScanBroadcast
	| SmartbusSetIdBroadcast
type ApplyConfig = {
	type: "applyConfig"
	blob: Uint8Array
}

type SetMotorPoll = {
	type: "setMotorPoll"
	ids: number[]
}

type SetBotId = {
	type: "setBotId"
	id: string
}

export type MsgToBot =
	| Omit<DriveMotor, "botId">
	| Omit<Stop, "botId">
	| Ping
	| StopAllMotors
	| Omit<TurnServo, "botId">
	| Omit<ArmMove, "botId">
	| Omit<ArmSetSpeed, "botId">
	| Omit<ArmJog, "botId">
	| Omit<ArmStopJoint, "botId">
	| Omit<ArmStopAll, "botId">
	| Omit<ArmGotoTicks, "botId">
	| Omit<ArmGotoAngles, "botId">
	| Omit<ArmGotoCoords, "botId">
	| Omit<ArmHold, "botId">
	| Omit<ArmSetJointTick, "botId">
	| Omit<ArmSetTickLimits, "botId">
	| Omit<ArmSetTickLimitsEnabled, "botId">
	| Omit<ArmMoveRelative, "botId">
	| Omit<ArmClearFaults, "botId">
	| Omit<SmartbusScan, "botId">
	| Omit<SmartbusSetId, "botId">
	| SetMotorPoll
	| SetBotId
	| ApplyConfig

// export type MyInfo = {
// 	type: "myInfo"
// 	version: string
// }

// export type Pong = {
// 	type: "pong"
// }

// export type MsgFromBot = MyInfo | Pong
