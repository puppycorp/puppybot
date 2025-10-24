import { encodeBotMsg } from "./bot-protocol"
import type { MsgToBot } from "./types"

describe("encodeBotMsg", () => {
	test("encodes a drive message correctly", () => {
		// Create a drive message with speed and angle values.
		const driveMsg: MsgToBot = {
			type: "drive",
			speed: 10,
			angle: 45,
		} as any

		const buffer = encodeBotMsg(driveMsg)

		// Expected header:
		//  Byte 0: 0xAA
		//  Byte 1: Command Type for drive -> 1
		//  Bytes 2-3: Payload length (9 bytes) in little-endian (9, 0)
		const expectedHeader = Buffer.from([0xaa, 2, 3, 0])

		// Expected payload for a drive message is 9 bytes:
		//  Byte 0: MotorID (0)
		//  Byte 1: type (0, representing DC)
		//  Byte 2: speed (10)
		//  Bytes 3-4: steps (0 as int16 little-endian)
		//  Bytes 5-6: step_time (0 as int16 little-endian)
		//  Bytes 7-8: angle (45 as int16 little-endian: 45 = 0x2D, 0x00)
		const expectedPayload = Buffer.alloc(3)
		expectedPayload.writeUInt8(0, 0) // MotorID
		expectedPayload.writeInt8(10, 1) // speed
		expectedPayload.writeInt8(0, 2) // reserved

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
		} as any

		const buffer = encodeBotMsg(turnMsg)

		const expectedHeader = Buffer.from([0xaa, 5, 3, 0])
		const expectedPayload = Buffer.alloc(3)
		expectedPayload.writeUInt8(2, 0)
		expectedPayload.writeInt16LE(45, 1)
		const expectedBuffer = Buffer.concat([expectedHeader, expectedPayload])
		expect(buffer.equals(expectedBuffer)).toBe(true)
	})
})
