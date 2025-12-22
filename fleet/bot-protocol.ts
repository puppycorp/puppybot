import type { MsgToBot } from "./types"

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
}

export enum MsgFromBotType {
	Pong = 1,
	MyInfo = 2,
	MotorState = 3,
	SmartbusScanResult = 4,
	SmartbusSetIdResult = 5,
	ConfigBlob = 6,
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

export type MsgFromBot =
	| PongMsg
	| MyInfoMsg
	| MotorStateMsg
	| SmartbusScanResultMsg
	| SmartbusSetIdResultMsg
	| ConfigBlobMsg

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

			return {
				type: MsgFromBotType.MyInfo,
				protocolVersion,
				firmwareVersion,
				variant,
				deviceName,
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
		default:
			throw new Error("Unknown command type")
	}
}
