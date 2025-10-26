import type { MsgToBot } from "./types"

enum MsgToBotType {
	Ping = 1,
	DriveMotor = 2,
	StopMotor = 3,
	StopAllMotors = 4,
	TurnServo = 5,
	ApplyConfig = 6,
}

export enum MsgFromBotType {
	Pong = 1,
	MyInfo = 2,
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
}

export type MsgFromBot = PongMsg | MyInfoMsg

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

const header = (cmd: Command) => {}

type Instruction = {
	type: InstructionType
	args: any[]
}

const block = (instructions: Instruction[]) => {}

export const encodeBotMsg = (msg: MsgToBot): Buffer => {
	switch (msg.type) {
		case "drive": {
			const commandType = MsgToBotType.DriveMotor
			const payloadLength = 9
			const payload = Buffer.alloc(payloadLength)

			const motorId = msg.motorId ?? 0
			const motorType = msg.motorType === "servo" ? 1 : 0
			const speed = Math.max(
				-128,
				Math.min(127, Math.round(msg.speed ?? 0)),
			)
			const steps = Math.max(
				0,
				Math.min(0xffff, Math.round(msg.steps ?? 0)),
			)
			const stepTime = Math.max(
				0,
				Math.min(0xffff, Math.round(msg.stepTimeMicros ?? 0)),
			)
			const angle = Math.max(
				0,
				Math.min(0xffff, Math.round(msg.angle ?? 0)),
			)

			payload.writeUInt8(motorId & 0xff, 0) // MotorID
			payload.writeUInt8(motorType & 0xff, 1) // Motor type (0 = DC)
			payload.writeInt8(speed, 2) // Speed (-128..127)
			payload.writeUInt16LE(steps, 3) // Steps / pulse count
			payload.writeUInt16LE(stepTime, 5) // Step time (microseconds)
			payload.writeUInt16LE(angle, 7) // Angle for servo mode

			const header = createHeader(commandType, payloadLength)
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
			const commandType = MsgToBotType.TurnServo
			const payloadLength = 5
			const payload = Buffer.alloc(payloadLength)

			payload.writeUInt8(msg.servoId, 0)
			payload.writeInt16LE(msg.angle, 1)
			const duration = Math.max(0, Math.min(0xffff, msg.durationMs ?? 0))
			payload.writeUInt16LE(duration, 3)

			const header = createHeader(commandType, payloadLength)
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

			return {
				type: MsgFromBotType.MyInfo,
				protocolVersion,
				firmwareVersion,
				variant,
			}
		}
		default:
			throw new Error("Unknown command type")
	}
}
