import type { ArmJointState, ArmState, MsgToBot } from "./types"

enum MsgToBotType {
	Ping = 1,
	DriveMotor = 2,
	StopMotor = 3,
	StopAllMotors = 4,
	ApplyConfig = 6,
	SmartbusScan = 7,
	SmartbusSetId = 8,
	SetMotorPoll = 9,
	SetBotId = 10,
	ArmMove = 11,
	ArmSetSpeed = 12,
	ArmJog = 13,
	ArmStopJoint = 14,
	ArmStopAll = 15,
	ArmGotoTicks = 16,
	ArmGotoAngles = 17,
	ArmGotoCoords = 18,
	ArmHold = 19,
	ArmSetJointTick = 20,
	ArmSetTickLimits = 21,
	ArmSetTickLimitsEnabled = 22,
	ArmMoveRelative = 23,
	ArmClearFaults = 24,
	Subscribe = 33,
}

const SUBSCRIPTION_TOPIC_ARM_STATE = 1

export enum MsgFromBotType {
	Pong = 1,
	MyInfo = 2,
	MotorState = 3,
	SmartbusScanResult = 4,
	SmartbusSetIdResult = 5,
	ConfigBlob = 6,
	ArmState = 7,
}

enum InstructionType {
	Sleep = 1,
	Stop = 2,
	DoUntil = 3,
	Drive = 4,
}

enum Operator {
	Equal = 1,
	NotEqual = 2,
	GreaterThan = 3,
	LessThan = 4,
	GreaterThanOrEqual = 5,
	LessThanOrEqual = 6,
	And = 7,
	Or = 8,
	Forever = 9,
}

type ConditionFrame = {
	targetId: number
	fieldId: number
	operator: Operator
	value: number
}

type DoUntilCondition = {
	type: InstructionType.DoUntil
	targetId: number
	instruction: InstructionType.Drive
}

type StopAll = {
	type: MsgToBotType.StopAllMotors
}

type Command = StopAll

export type PongMsg = {
	type: MsgFromBotType.Pong
	protocolVersion: number
}

export type MyInfoMsg = {
	type: MsgFromBotType.MyInfo
	protocolVersion: number
	firmwareVersion: string
	variant: string
	deviceName: string
	botId: string
}

export type MotorStateEntry = {
	motorId: number
	valid: boolean
	wheelMode: boolean
	positionDeg: number | null
	positionRaw: number | null
}

export type MotorStateMsg = {
	type: MsgFromBotType.MotorState
	protocolVersion: number
	motors: MotorStateEntry[]
}

export type SmartbusScanResultMsg = {
	type: MsgFromBotType.SmartbusScanResult
	protocolVersion: number
	uartPort: number
	startId: number
	endId: number
	foundIds: number[]
}

export type SmartbusSetIdResultMsg = {
	type: MsgFromBotType.SmartbusSetIdResult
	protocolVersion: number
	uartPort: number
	oldId: number
	newId: number
	status: number
}

export type ConfigBlobMsg = {
	type: MsgFromBotType.ConfigBlob
	protocolVersion: number
	blob: Uint8Array
}

export type ArmStateMsg = {
	type: MsgFromBotType.ArmState
	protocolVersion: number
	state: ArmState
}

export type MsgFromBot =
	| PongMsg
	| MyInfoMsg
	| MotorStateMsg
	| SmartbusScanResultMsg
	| SmartbusSetIdResultMsg
	| ConfigBlobMsg
	| ArmStateMsg

const DC_MOTOR = 0
const SERVO_MOTOR = 1

const createHeader = (
	commandType: MsgToBotType,
	payloadLength: number,
): Buffer => {
	const headerLength = 4
	const headerBuffer = Buffer.alloc(headerLength)
	// Byte 0: Start Byte (always 0xAA)
	headerBuffer.writeUInt8(0xaa, 0)
	// Byte 1: Command Type
	headerBuffer.writeUInt8(commandType, 1)
	// Bytes 2-3: Payload length in little-endian
	headerBuffer.writeUInt16LE(payloadLength, 2)
	return headerBuffer
}

const DRIVE_PAYLOAD_LENGTH = 9
const ARM_MOVE_PAYLOAD_LENGTH = 15
const ARM_GOTO_TICKS_PAYLOAD_LENGTH = 18
const ARM_GOTO_ANGLES_PAYLOAD_LENGTH = 18
const ARM_GOTO_COORDS_PAYLOAD_LENGTH = 14
const ARM_MOVE_RELATIVE_PAYLOAD_LENGTH = 10

type DrivePayloadInput = {
	motorId?: number
	motorType?: "dc" | "servo"
	speed?: number
	steps?: number
	stepTimeMicros?: number
	angle?: number
}

const clampInt = (value: number | undefined, min: number, max: number) => {
	const safeValue = Number.isFinite(value ?? 0) ? (value ?? 0) : 0
	return Math.max(min, Math.min(max, Math.round(safeValue)))
}

const createSetBotIdPayload = (id: string): Buffer => {
	const idBuffer = Buffer.from(id ?? "", "utf8")
	const idLength = Math.min(255, idBuffer.length)
	const payload = Buffer.alloc(1 + idLength)
	payload.writeUInt8(idLength, 0)
	idBuffer.copy(payload, 1, 0, idLength)
	return payload
}

const createDrivePayload = (input: DrivePayloadInput): Buffer => {
	const payload = Buffer.alloc(DRIVE_PAYLOAD_LENGTH)
	payload.writeUInt8(clampInt(input.motorId, 0, 0xff), 0)
	const typeBits = input.motorType === "servo" ? SERVO_MOTOR : DC_MOTOR
	payload.writeUInt8(typeBits, 1)
	payload.writeInt8(clampInt(input.speed, -128, 127), 2)
	payload.writeUInt16LE(clampInt(input.steps, 0, 0xffff), 3)
	payload.writeUInt16LE(clampInt(input.stepTimeMicros, 0, 0xffff), 5)
	payload.writeUInt16LE(clampInt(input.angle, 0, 0xffff), 7)
	return payload
}

const createArmMovePayload = (input: {
	x: number
	y: number
	z: number
	elbowUp?: boolean
	durationMs?: number
}): Buffer => {
	const payload = Buffer.alloc(ARM_MOVE_PAYLOAD_LENGTH)
	payload.writeFloatLE(Number.isFinite(input.x) ? input.x : 0, 0)
	payload.writeFloatLE(Number.isFinite(input.y) ? input.y : 0, 4)
	payload.writeFloatLE(Number.isFinite(input.z) ? input.z : 0, 8)
	payload.writeUInt8(input.elbowUp ? 1 : 0, 12)
	payload.writeUInt16LE(clampInt(input.durationMs, 0, 0xffff), 13)
	return payload
}

const createArmSpeedPayload = (speed: number): Buffer => {
	const payload = Buffer.alloc(2)
	payload.writeUInt16LE(clampInt(speed, 0, 1000), 0)
	return payload
}

const createArmJogPayload = (input: {
	joint: number
	direction: number
	speed: number
}): Buffer => {
	const payload = Buffer.alloc(4)
	payload.writeUInt8(clampInt(input.joint, 0, 0xff), 0)
	payload.writeInt8(clampInt(input.direction, -1, 1), 1)
	payload.writeUInt16LE(clampInt(input.speed, 0, 1000), 2)
	return payload
}

const createArmGotoTicksPayload = (input: {
	speed: number
	ticks: readonly number[]
}): Buffer => {
	const payload = Buffer.alloc(ARM_GOTO_TICKS_PAYLOAD_LENGTH)
	payload.writeUInt16LE(clampInt(input.speed, 0, 1000), 0)
	for (let i = 0; i < 4; i++) {
		payload.writeInt32LE(
			clampInt(input.ticks[i], -0x80000000, 0x7fffffff),
			2 + i * 4,
		)
	}
	return payload
}

const createArmGotoAnglesPayload = (input: {
	speed: number
	anglesDeg: readonly number[]
}): Buffer => {
	const payload = Buffer.alloc(ARM_GOTO_ANGLES_PAYLOAD_LENGTH)
	payload.writeUInt16LE(clampInt(input.speed, 0, 1000), 0)
	for (let i = 0; i < 4; i++) {
		const angle = Number.isFinite(input.anglesDeg[i])
			? input.anglesDeg[i]
			: 0
		payload.writeFloatLE(angle, 2 + i * 4)
	}
	return payload
}

const createArmGotoCoordsPayload = (input: {
	speed: number
	x: number
	y: number
	z: number
}): Buffer => {
	const payload = Buffer.alloc(ARM_GOTO_COORDS_PAYLOAD_LENGTH)
	payload.writeUInt16LE(clampInt(input.speed, 0, 1000), 0)
	payload.writeFloatLE(Number.isFinite(input.x) ? input.x : 0, 2)
	payload.writeFloatLE(Number.isFinite(input.y) ? input.y : 0, 6)
	payload.writeFloatLE(Number.isFinite(input.z) ? input.z : 0, 10)
	return payload
}

const createArmSetJointTickPayload = (input: {
	joint: number
	speed: number
	tick: number
}): Buffer => {
	const payload = Buffer.alloc(7)
	payload.writeUInt8(clampInt(input.joint, 0, 0xff), 0)
	payload.writeUInt16LE(clampInt(input.speed, 0, 1000), 1)
	payload.writeInt32LE(clampInt(input.tick, -0x80000000, 0x7fffffff), 3)
	return payload
}

const createArmSetTickLimitsPayload = (input: {
	joint: number
	min: number
	max: number
}): Buffer => {
	const payload = Buffer.alloc(9)
	payload.writeUInt8(clampInt(input.joint, 0, 0xff), 0)
	payload.writeInt32LE(clampInt(input.min, -0x80000000, 0x7fffffff), 1)
	payload.writeInt32LE(clampInt(input.max, -0x80000000, 0x7fffffff), 5)
	return payload
}

const createArmSetTickLimitsEnabledPayload = (input: {
	joint: number
	enabled: boolean
}): Buffer => {
	const payload = Buffer.alloc(2)
	payload.writeUInt8(clampInt(input.joint, 0, 0xff), 0)
	payload.writeUInt8(input.enabled ? 1 : 0, 1)
	return payload
}

const createArmMoveRelativePayload = (input: {
	speed: number
	dx: number
	dy: number
}): Buffer => {
	const payload = Buffer.alloc(ARM_MOVE_RELATIVE_PAYLOAD_LENGTH)
	payload.writeUInt16LE(clampInt(input.speed, 0, 1000), 0)
	payload.writeFloatLE(Number.isFinite(input.dx) ? input.dx : 0, 2)
	payload.writeFloatLE(Number.isFinite(input.dy) ? input.dy : 0, 6)
	return payload
}

const packet = (commandType: MsgToBotType, payload: Buffer = Buffer.alloc(0)) =>
	Buffer.concat([createHeader(commandType, payload.length), payload])

const header = (cmd: Command) => {}

type Instruction = {
	type: InstructionType
	args: any[]
}

const block = (instructions: Instruction[]) => {}

export const encodeBotMsg = (msg: MsgToBot): Buffer => {
	switch (msg.type) {
		case "drive": {
			const payload = createDrivePayload({
				motorId: msg.motorId,
				motorType: msg.motorType,
				speed: msg.speed,
				steps: msg.steps,
				stepTimeMicros: msg.stepTimeMicros,
				angle: msg.angle,
			})
			const header = createHeader(
				MsgToBotType.DriveMotor,
				DRIVE_PAYLOAD_LENGTH,
			)
			return Buffer.concat([header, payload])
		}
		case "stop": {
			const commandType = MsgToBotType.StopMotor
			const payloadLength = 1
			const payload = Buffer.alloc(payloadLength)

			// Set payload field for MotorID
			payload.writeUInt8(0, 0)

			const header = createHeader(commandType, payloadLength)
			return Buffer.concat([header, payload])
		}
		case "stopAllMotors": {
			const commandType = MsgToBotType.StopAllMotors
			const payloadLength = 0
			const payload = Buffer.alloc(payloadLength)

			const header = createHeader(commandType, payloadLength)
			return Buffer.concat([header, payload])
		}
		case "turnServo": {
			const payload = createDrivePayload({
				motorId: msg.servoId,
				motorType: "servo",
				speed: 0,
				steps: msg.durationMs,
				stepTimeMicros: 0,
				angle: msg.angle,
			})
			const header = createHeader(
				MsgToBotType.DriveMotor,
				DRIVE_PAYLOAD_LENGTH,
			)
			return Buffer.concat([header, payload])
		}
		case "armMove": {
			const payload = createArmMovePayload({
				x: msg.x,
				y: msg.y,
				z: msg.z,
				elbowUp: msg.elbowUp,
				durationMs: msg.durationMs,
			})
			const header = createHeader(
				MsgToBotType.ArmMove,
				ARM_MOVE_PAYLOAD_LENGTH,
			)
			return Buffer.concat([header, payload])
		}
		case "armSetSpeed":
			return packet(
				MsgToBotType.ArmSetSpeed,
				createArmSpeedPayload(msg.speed),
			)
		case "armJog":
			return packet(MsgToBotType.ArmJog, createArmJogPayload(msg))
		case "armStopJoint": {
			const payload = Buffer.from([clampInt(msg.joint, 0, 0xff)])
			return packet(MsgToBotType.ArmStopJoint, payload)
		}
		case "armStopAll":
			return packet(MsgToBotType.ArmStopAll)
		case "armGotoTicks":
			return packet(
				MsgToBotType.ArmGotoTicks,
				createArmGotoTicksPayload(msg),
			)
		case "armGotoAngles":
			return packet(
				MsgToBotType.ArmGotoAngles,
				createArmGotoAnglesPayload(msg),
			)
		case "armGotoCoords":
			return packet(
				MsgToBotType.ArmGotoCoords,
				createArmGotoCoordsPayload(msg),
			)
		case "armHold":
			return packet(MsgToBotType.ArmHold, createArmSpeedPayload(msg.speed))
		case "armSetJointTick":
			return packet(
				MsgToBotType.ArmSetJointTick,
				createArmSetJointTickPayload(msg),
			)
		case "armSetTickLimits":
			return packet(
				MsgToBotType.ArmSetTickLimits,
				createArmSetTickLimitsPayload(msg),
			)
		case "armSetTickLimitsEnabled":
			return packet(
				MsgToBotType.ArmSetTickLimitsEnabled,
				createArmSetTickLimitsEnabledPayload(msg),
			)
		case "armMoveRelative":
			return packet(
				MsgToBotType.ArmMoveRelative,
				createArmMoveRelativePayload(msg),
			)
		case "armClearFaults": {
			const joint = msg.joint === undefined ? 255 : msg.joint
			const payload = Buffer.from([clampInt(joint, 0, 0xff)])
			return packet(MsgToBotType.ArmClearFaults, payload)
		}
		case "applyConfig": {
			const payload = Buffer.from(msg.blob)
			const header = createHeader(
				MsgToBotType.ApplyConfig,
				payload.length,
			)
			return Buffer.concat([header, payload])
		}
		case "smartbusScan": {
			const payload = Buffer.alloc(3)
			payload.writeUInt8(clampInt(msg.uartPort, 0, 0xff), 0)
			payload.writeUInt8(clampInt(msg.startId, 0, 0xff), 1)
			payload.writeUInt8(clampInt(msg.endId, 0, 0xff), 2)
			const header = createHeader(
				MsgToBotType.SmartbusScan,
				payload.length,
			)
			return Buffer.concat([header, payload])
		}
		case "smartbusSetId": {
			const payload = Buffer.alloc(3)
			payload.writeUInt8(clampInt(msg.uartPort, 0, 0xff), 0)
			payload.writeUInt8(clampInt(msg.oldId, 0, 0xff), 1)
			payload.writeUInt8(clampInt(msg.newId, 0, 0xff), 2)
			const header = createHeader(
				MsgToBotType.SmartbusSetId,
				payload.length,
			)
			return Buffer.concat([header, payload])
		}
		case "setMotorPoll": {
			const ids = (msg.ids ?? []).filter(
				(id) => Number.isFinite(id) && id >= 0 && id <= 255,
			)
			const count = Math.min(32, ids.length)
			const payload = Buffer.alloc(1 + count)
			payload.writeUInt8(count, 0)
			for (let i = 0; i < count; i++) {
				payload.writeUInt8(clampInt(ids[i], 0, 0xff), 1 + i)
			}
			const header = createHeader(
				MsgToBotType.SetMotorPoll,
				payload.length,
			)
			return Buffer.concat([header, payload])
		}
		case "subscribe": {
			const payload = Buffer.alloc(2)
			payload.writeUInt8(subscriptionTopicId(msg.topic), 0)
			payload.writeUInt8(msg.enabled ? 1 : 0, 1)
			const header = createHeader(MsgToBotType.Subscribe, payload.length)
			return Buffer.concat([header, payload])
		}
		case "setBotId": {
			const payload = createSetBotIdPayload(msg.id)
			const header = createHeader(MsgToBotType.SetBotId, payload.length)
			return Buffer.concat([header, payload])
		}
		case "ping":
			return createHeader(MsgToBotType.Ping, 0)
		default:
			throw new Error("Unknown message type")
	}
}

const subscriptionTopicId = (topic: string): number => {
	switch (topic) {
		case "armState":
			return SUBSCRIPTION_TOPIC_ARM_STATE
		default:
			return 0
	}
}

export const decodeBotMsg = (buffer: Buffer): MsgFromBot => {
	if (buffer.length < 3) {
		throw new Error("Invalid message from bot: too short")
	}
	const protocolVersion = buffer.readUInt16LE(0)
	const cmd = buffer.readUInt8(2)
	switch (cmd) {
		case MsgFromBotType.Pong: {
			return { type: MsgFromBotType.Pong, protocolVersion }
		}
		case MsgFromBotType.MyInfo: {
			let offset = 3
			const readString = () => {
				if (offset >= buffer.length) return ""
				const length = buffer.readUInt8(offset)
				offset += 1
				const available = Math.min(length, buffer.length - offset)
				const value = buffer
					.subarray(offset, offset + available)
					.toString("utf8")
				offset += available
				return value
			}

			const firmwareVersion = readString()
			const variant = readString()
			const deviceName = readString()
			const botId = offset < buffer.length ? readString() : ""

			return {
				type: MsgFromBotType.MyInfo,
				protocolVersion,
				firmwareVersion,
				variant,
				deviceName,
				botId,
			}
		}
		case MsgFromBotType.MotorState: {
			if (buffer.length < 4) {
				throw new Error("Invalid motor state message: too short")
			}
			const count = buffer.readUInt8(3)
			let offset = 4
			const motors: MotorStateEntry[] = []
			for (let i = 0; i < count; i++) {
				if (offset + 6 > buffer.length) break
				const motorId = buffer.readUInt8(offset)
				const flags = buffer.readUInt8(offset + 1)
				const degX10 = buffer.readInt16LE(offset + 2)
				const raw = buffer.readUInt16LE(offset + 4)
				offset += 6
				const valid = (flags & 0x01) !== 0
				const wheelMode = (flags & 0x02) !== 0
				motors.push({
					motorId,
					valid,
					wheelMode,
					positionDeg: valid ? degX10 / 10 : null,
					positionRaw: valid ? raw : null,
				})
			}
			return { type: MsgFromBotType.MotorState, protocolVersion, motors }
		}
		case MsgFromBotType.SmartbusScanResult: {
			if (buffer.length < 7) {
				throw new Error("Invalid smartbus scan result: too short")
			}
			const uartPort = buffer.readUInt8(3)
			const startId = buffer.readUInt8(4)
			const endId = buffer.readUInt8(5)
			const count = buffer.readUInt8(6)
			const foundIds: number[] = []
			let offset = 7
			for (let i = 0; i < count && offset < buffer.length; i++) {
				foundIds.push(buffer.readUInt8(offset))
				offset += 1
			}
			return {
				type: MsgFromBotType.SmartbusScanResult,
				protocolVersion,
				uartPort,
				startId,
				endId,
				foundIds,
			}
		}
		case MsgFromBotType.SmartbusSetIdResult: {
			if (buffer.length < 7) {
				throw new Error("Invalid smartbus set-id result: too short")
			}
			const uartPort = buffer.readUInt8(3)
			const oldId = buffer.readUInt8(4)
			const newId = buffer.readUInt8(5)
			const status = buffer.readUInt8(6)
			return {
				type: MsgFromBotType.SmartbusSetIdResult,
				protocolVersion,
				uartPort,
				oldId,
				newId,
				status,
			}
		}
		case MsgFromBotType.ConfigBlob: {
			if (buffer.length < 5) {
				throw new Error("Invalid config blob message: too short")
			}
			const length = buffer.readUInt16LE(3)
			if (buffer.length < 5 + length) {
				throw new Error("Invalid config blob message: truncated")
			}
			const blob = buffer.subarray(5, 5 + length)
			return {
				type: MsgFromBotType.ConfigBlob,
				protocolVersion,
				blob,
			}
		}
		case MsgFromBotType.ArmState: {
			if (buffer.length < 4) {
				throw new Error("Invalid arm state message: too short")
			}
			const count = buffer.readUInt8(3)
			let offset = 4
			const joints: ArmJointState[] = []
			for (let i = 0; i < count; i++) {
				if (offset + 25 > buffer.length) break
				const servoId = buffer.readUInt8(offset)
				const flags = buffer.readUInt8(offset + 1)
				const tick = buffer.readInt32LE(offset + 2)
				const targetTickRaw = buffer.readInt32LE(offset + 6)
				const speed = buffer.readInt16LE(offset + 10)
				const limitMin = buffer.readInt32LE(offset + 12)
				const limitMax = buffer.readInt32LE(offset + 16)
				const angleDegRaw = buffer.readFloatLE(offset + 20)
				const faultLength = buffer.readUInt8(offset + 24)
				offset += 25
				const available = Math.min(faultLength, buffer.length - offset)
				const fault = buffer
					.subarray(offset, offset + available)
					.toString("utf8")
				offset += available
				const hasFeedback = (flags & 0x02) !== 0
				const hasTarget = (flags & 0x08) !== 0
				joints.push({
					servoId,
					online: (flags & 0x01) !== 0,
					hasFeedback,
					limitReached: (flags & 0x04) !== 0,
					hasTarget,
					hasFault: (flags & 0x10) !== 0,
					tick,
					targetTick: hasTarget ? targetTickRaw : null,
					speed,
					limitMin,
					limitMax,
					angleDeg: hasFeedback ? angleDegRaw : null,
					fault,
				})
			}
			let poseValid = false
			let coordsMm: ArmState["coordsMm"] = null
			if (offset + 13 <= buffer.length) {
				const poseFlags = buffer.readUInt8(offset)
				poseValid = (poseFlags & 0x01) !== 0
				const x = buffer.readFloatLE(offset + 1)
				const y = buffer.readFloatLE(offset + 5)
				const z = buffer.readFloatLE(offset + 9)
				coordsMm = poseValid ? { x, y, z } : null
			}
			return {
				type: MsgFromBotType.ArmState,
				protocolVersion,
				state: { joints, poseValid, coordsMm },
			}
		}
		default:
			throw new Error("Unknown command type")
	}
}
