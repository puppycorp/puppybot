export type Bot = {
	id: string
	version: string
	variant: string
	connected: boolean
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
	pollStatus?: boolean
	pwm?: MotorPwmConfig
	smart?: SmartServoBusConfig
	hbridge?: MotorHBridgeConfig
	analog?: MotorAnalogFeedbackConfig
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

type UpdateConfig = {
	type: "updateConfig"
	botId: string
	motors: MotorConfig[]
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
	| SmartbusScan
	| SmartbusSetId
	| UpdateConfig

export type BotConnected = {
	type: "botConnected"
	botId: string
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
}

export type Ping = {
	type: "ping"
}

export type ConfigBroadcast = {
	type: "config"
	botId: string
	motors: MotorConfig[]
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

export type MsgToUi =
	| BotConnected
	| BotDisconnected
	| BotInfo
	| ConfigBroadcast
	| MotorStateBroadcast
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

export type MsgToBot =
	| Omit<DriveMotor, "botId">
	| Omit<Stop, "botId">
	| Ping
	| StopAllMotors
	| Omit<TurnServo, "botId">
	| Omit<SmartbusScan, "botId">
	| Omit<SmartbusSetId, "botId">
	| SetMotorPoll
	| ApplyConfig

// export type MyInfo = {
// 	type: "myInfo"
// 	version: string
// }

// export type Pong = {
// 	type: "pong"
// }

// export type MsgFromBot = MyInfo | Pong
