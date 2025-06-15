import type { MsgToBot } from "./types"

enum MsgToBotType {
	Ping = 1,
	DriveMotor = 2,
	StopMotor = 3,
	StopAllMotors = 4,
	TurnServo = 5,
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
}

export type MyInfoMsg = {
	type: MsgFromBotType.MyInfo
	version: number
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
			const payloadLength = 3
			const payload = Buffer.alloc(payloadLength)

			// Set payload fields
			payload.writeUInt8(msg.motorId, 0) // MotorID
			payload.writeInt8(msg.speed, 1) // speed
			// payload.writeInt8(0, 1)            // type (0 = DC)
			// payload.writeInt16LE(0, 3)         // steps
			// payload.writeInt16LE(0, 5)         // step_time
			// payload.writeInt16LE(msg.angle, 7) // angle

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
			const payloadLength = 2
			const payload = Buffer.alloc(payloadLength)

			payload.writeInt16LE(msg.angle, 0)

			const header = createHeader(commandType, payloadLength)
			return Buffer.concat([header, payload])
		}
		case "ping":
			return createHeader(MsgToBotType.Ping, 0)
		default:
			throw new Error("Unknown message type")
	}
}

export const decodeBotMsg = (buffer: Buffer): MsgFromBot => {
	let version = buffer.readUint16LE(0)
	const cmd = buffer.readUInt8(2)
	switch (cmd) {
		case MsgFromBotType.Pong: {
			return { type: MsgFromBotType.Pong }
		}
		case MsgFromBotType.MyInfo: {
			return {
				type: MsgFromBotType.MyInfo,
				version: 1,
			}
		}
		default:
			throw new Error("Unknown command type")
	}
}
