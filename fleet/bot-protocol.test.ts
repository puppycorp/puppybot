import { decodeBotMsg, encodeBotMsg, MsgFromBotType } from "./bot-protocol"
import type { MsgToBot } from "./types"

describe("encodeBotMsg", () => {
	test("encodes a drive message correctly", () => {
		const driveMsg: MsgToBot = {
			type: "drive",
			motorId: 2,
			speed: 10,
			motorType: "dc",
			steps: 123,
			stepTimeMicros: 456,
			angle: 45,
		}

		const buffer = encodeBotMsg(driveMsg)

		const expectedHeader = Buffer.from([0xaa, 2, 9, 0])
		const expectedPayload = Buffer.alloc(9)
		expectedPayload.writeUInt8(2, 0)
		expectedPayload.writeUInt8(0, 1)
		expectedPayload.writeInt8(10, 2)
		expectedPayload.writeUInt16LE(123, 3)
		expectedPayload.writeUInt16LE(456, 5)
		expectedPayload.writeUInt16LE(45, 7)

		const expectedBuffer = Buffer.concat([expectedHeader, expectedPayload])
		expect(buffer.equals(expectedBuffer)).toBe(true)
	})

	test("encodes a stop message correctly", () => {
		// Create a stop message.
		const stopMsg: MsgToBot = { type: "stop" } as any

		const buffer = encodeBotMsg(stopMsg)

		// Expected header:
		//  Byte 0: 0xAA
		//  Byte 1: Command Type for stop -> 2
		//  Bytes 2-3: Payload length (1 byte) in little-endian (1, 0)
		const expectedHeader = Buffer.from([0xaa, 3, 1, 0])

		// Expected payload for a stop message is 1 byte:
		//  Byte 0: MotorID (0)
		const expectedPayload = Buffer.from([0])

		const expectedBuffer = Buffer.concat([expectedHeader, expectedPayload])
		expect(buffer.equals(expectedBuffer)).toBe(true)
	})

	test("encodes a turn servo message correctly", () => {
		const turnMsg: MsgToBot = {
			type: "turnServo",
			servoId: 2,
			angle: 45,
			durationMs: 500,
		} as any

		const buffer = encodeBotMsg(turnMsg)

		const expectedHeader = Buffer.from([0xaa, 2, 9, 0])
		const expectedPayload = Buffer.alloc(9)
		expectedPayload.writeUInt8(2, 0)
		expectedPayload.writeUInt8(1, 1)
		expectedPayload.writeInt8(0, 2)
		expectedPayload.writeUInt16LE(500, 3)
		expectedPayload.writeUInt16LE(0, 5)
		expectedPayload.writeUInt16LE(45, 7)
		const expectedBuffer = Buffer.concat([expectedHeader, expectedPayload])
		expect(buffer.equals(expectedBuffer)).toBe(true)
	})

	test("encodes a turn servo message without timeout", () => {
		const turnMsg: MsgToBot = {
			type: "turnServo",
			servoId: 1,
			angle: 30,
		} as any

		const buffer = encodeBotMsg(turnMsg)

		const expectedHeader = Buffer.from([0xaa, 2, 9, 0])
		const expectedPayload = Buffer.alloc(9)
		expectedPayload.writeUInt8(1, 0)
		expectedPayload.writeUInt8(1, 1)
		expectedPayload.writeInt8(0, 2)
		expectedPayload.writeUInt16LE(0, 3)
		expectedPayload.writeUInt16LE(0, 5)
		expectedPayload.writeUInt16LE(30, 7)
		const expectedBuffer = Buffer.concat([expectedHeader, expectedPayload])
		expect(buffer.equals(expectedBuffer)).toBe(true)
	})

	test("encodes an apply config message", () => {
		const blob = new Uint8Array([1, 2, 3, 4])
		const msg: MsgToBot = { type: "applyConfig", blob }
		const buffer = encodeBotMsg(msg)
		const expectedHeader = Buffer.from([0xaa, 6, 4, 0])
		const expectedPayload = Buffer.from(blob)
		expect(
			buffer.equals(Buffer.concat([expectedHeader, expectedPayload])),
		).toBe(true)
	})

	test("decodes a MyInfo message with version, variant, and name", () => {
		const version = "3.2.1"
		const variant = "PuppyBot"
		const deviceName = "rover"
		const buffer = Buffer.alloc(
			3 + 1 + version.length + 1 + variant.length + 1 + deviceName.length,
		)
		buffer.writeUInt16LE(1, 0)
		buffer.writeUInt8(MsgFromBotType.MyInfo, 2)
		let offset = 3
		buffer.writeUInt8(version.length, offset)
		offset += 1
		buffer.write(version, offset)
		offset += version.length
		buffer.writeUInt8(variant.length, offset)
		offset += 1
		buffer.write(variant, offset)
		offset += variant.length
		buffer.writeUInt8(deviceName.length, offset)
		offset += 1
		buffer.write(deviceName, offset)

		const msg = decodeBotMsg(buffer)
		expect(msg).toEqual({
			type: MsgFromBotType.MyInfo,
			protocolVersion: 1,
			firmwareVersion: version,
			variant,
			deviceName,
		})
	})

	test("decodes a motor state message", () => {
		const buffer = Buffer.alloc(4 + 6)
		buffer.writeUInt16LE(1, 0)
		buffer.writeUInt8(MsgFromBotType.MotorState, 2)
		buffer.writeUInt8(1, 3) // count
		buffer.writeUInt8(7, 4) // motorId
		buffer.writeUInt8(0x03, 5) // valid + wheelMode
		buffer.writeInt16LE(123, 6) // 12.3 deg
		buffer.writeUInt16LE(456, 8) // raw

		const msg = decodeBotMsg(buffer)
		expect(msg.type).toBe(MsgFromBotType.MotorState)
		if (msg.type !== MsgFromBotType.MotorState) return
		expect(msg.motors).toEqual([
			{
				motorId: 7,
				valid: true,
				wheelMode: true,
				positionDeg: 12.3,
				positionRaw: 456,
			},
		])
	})

	test("decodes a smartbus scan result message", () => {
		const buffer = Buffer.from([
			0x01,
			0x00,
			MsgFromBotType.SmartbusScanResult,
			0x01,
			0x01,
			0x05,
			0x02,
			0x01,
			0x04,
		])
		const msg = decodeBotMsg(buffer)
		expect(msg.type).toBe(MsgFromBotType.SmartbusScanResult)
		if (msg.type !== MsgFromBotType.SmartbusScanResult) return
		expect(msg.uartPort).toBe(1)
		expect(msg.startId).toBe(1)
		expect(msg.endId).toBe(5)
		expect(msg.foundIds).toEqual([1, 4])
	})

	test("decodes a smartbus set-id result message", () => {
		const buffer = Buffer.from([
			0x01,
			0x00,
			MsgFromBotType.SmartbusSetIdResult,
			0x01,
			0x01,
			0x02,
			0x00,
		])
		const msg = decodeBotMsg(buffer)
		expect(msg.type).toBe(MsgFromBotType.SmartbusSetIdResult)
		if (msg.type !== MsgFromBotType.SmartbusSetIdResult) return
		expect(msg.uartPort).toBe(1)
		expect(msg.oldId).toBe(1)
		expect(msg.newId).toBe(2)
		expect(msg.status).toBe(0)
	})

	test("decodes a config blob message", () => {
		const blob = Buffer.from([0x10, 0x20, 0x30])
		const buffer = Buffer.alloc(5 + blob.length)
		buffer.writeUInt16LE(1, 0)
		buffer.writeUInt8(MsgFromBotType.ConfigBlob, 2)
		buffer.writeUInt16LE(blob.length, 3)
		blob.copy(buffer, 5)
		const msg = decodeBotMsg(buffer)
		expect(msg.type).toBe(MsgFromBotType.ConfigBlob)
		if (msg.type !== MsgFromBotType.ConfigBlob) return
		expect(Buffer.from(msg.blob).equals(blob)).toBe(true)
	})

	test("encodes a set motor poll message", () => {
		const msg: MsgToBot = { type: "setMotorPoll", ids: [1, 2, 300] } as any
		const buffer = encodeBotMsg(msg)
		const expectedHeader = Buffer.from([0xaa, 9, 3, 0])
		const expectedPayload = Buffer.from([2, 1, 2])
		expect(
			buffer.equals(Buffer.concat([expectedHeader, expectedPayload])),
		).toBe(true)
	})
})
