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

	test("encodes an arm move message", () => {
		const msg: MsgToBot = {
			type: "armMove",
			x: 1.25,
			y: -2.5,
			z: 3,
			elbowUp: true,
			durationMs: 400,
		} as any
		const buffer = encodeBotMsg(msg)
		const expectedHeader = Buffer.from([0xaa, 11, 15, 0])
		const expectedPayload = Buffer.alloc(15)
		expectedPayload.writeFloatLE(1.25, 0)
		expectedPayload.writeFloatLE(-2.5, 4)
		expectedPayload.writeFloatLE(3, 8)
		expectedPayload.writeUInt8(1, 12)
		expectedPayload.writeUInt16LE(400, 13)
		expect(
			buffer.equals(Buffer.concat([expectedHeader, expectedPayload])),
		).toBe(true)
	})

	test("encodes arm set speed, jog, stop, hold, and clear commands", () => {
		expect(
			encodeBotMsg({ type: "armSetSpeed", speed: 250 } as any).equals(
				Buffer.from([0xaa, 12, 2, 0, 0xfa, 0x00]),
			),
		).toBe(true)
		expect(
			encodeBotMsg({
				type: "armJog",
				joint: 2,
				direction: -1,
				speed: 300,
			} as any).equals(
				Buffer.from([0xaa, 13, 4, 0, 2, 0xff, 0x2c, 0x01])
			),
		).toBe(true)
		expect(
			encodeBotMsg({ type: "armStopJoint", joint: 3 } as any).equals(
				Buffer.from([0xaa, 14, 1, 0, 3]),
			),
		).toBe(true)
		expect(
			encodeBotMsg({ type: "armStopAll" } as any).equals(
				Buffer.from([0xaa, 15, 0, 0]),
			),
		).toBe(true)
		expect(
			encodeBotMsg({ type: "armHold", speed: 210 } as any).equals(
				Buffer.from([0xaa, 19, 2, 0, 0xd2, 0x00]),
			),
		).toBe(true)
		expect(
			encodeBotMsg({ type: "armClearFaults" } as any).equals(
				Buffer.from([0xaa, 24, 1, 0, 0xff]),
			),
		).toBe(true)
	})

	test("encodes arm goto ticks message", () => {
		const buffer = encodeBotMsg({
			type: "armGotoTicks",
			speed: 400,
			ticks: [-1400, 530, 3565, 1783],
		} as any)
		const expectedPayload = Buffer.alloc(18)
		expectedPayload.writeUInt16LE(400, 0)
		expectedPayload.writeInt32LE(-1400, 2)
		expectedPayload.writeInt32LE(530, 6)
		expectedPayload.writeInt32LE(3565, 10)
		expectedPayload.writeInt32LE(1783, 14)
		expect(
			buffer.equals(
				Buffer.concat([Buffer.from([0xaa, 16, 18, 0]), expectedPayload])
			),
		).toBe(true)
	})

	test("encodes arm goto angles message", () => {
		const buffer = encodeBotMsg({
			type: "armGotoAngles",
			speed: 500,
			anglesDeg: [10, -20.5, 30.25, 45],
		} as any)
		const expectedPayload = Buffer.alloc(18)
		expectedPayload.writeUInt16LE(500, 0)
		expectedPayload.writeFloatLE(10, 2)
		expectedPayload.writeFloatLE(-20.5, 6)
		expectedPayload.writeFloatLE(30.25, 10)
		expectedPayload.writeFloatLE(45, 14)
		expect(
			buffer.equals(
				Buffer.concat([Buffer.from([0xaa, 17, 18, 0]), expectedPayload])
			),
		).toBe(true)
	})

	test("encodes arm coords, joint tick, limits, and relative messages", () => {
		const coords = encodeBotMsg({
			type: "armGotoCoords",
			speed: 180,
			x: 100,
			y: -25.5,
			z: 60,
		} as any)
		const coordsPayload = Buffer.alloc(14)
		coordsPayload.writeUInt16LE(180, 0)
		coordsPayload.writeFloatLE(100, 2)
		coordsPayload.writeFloatLE(-25.5, 6)
		coordsPayload.writeFloatLE(60, 10)
		expect(
			coords.equals(Buffer.concat([Buffer.from([0xaa, 18, 14, 0]), coordsPayload])),
		).toBe(true)

		const tick = encodeBotMsg({
			type: "armSetJointTick",
			joint: 1,
			speed: 190,
			tick: -100,
		} as any)
		const tickPayload = Buffer.alloc(7)
		tickPayload.writeUInt8(1, 0)
		tickPayload.writeUInt16LE(190, 1)
		tickPayload.writeInt32LE(-100, 3)
		expect(
			tick.equals(Buffer.concat([Buffer.from([0xaa, 20, 7, 0]), tickPayload])),
		).toBe(true)

		const limits = encodeBotMsg({
			type: "armSetTickLimits",
			joint: 2,
			min: -300,
			max: 900,
		} as any)
		const limitsPayload = Buffer.alloc(9)
		limitsPayload.writeUInt8(2, 0)
		limitsPayload.writeInt32LE(-300, 1)
		limitsPayload.writeInt32LE(900, 5)
		expect(
			limits.equals(Buffer.concat([Buffer.from([0xaa, 21, 9, 0]), limitsPayload])),
		).toBe(true)

		expect(
			encodeBotMsg({
				type: "armSetTickLimitsEnabled",
				joint: 3,
				enabled: true,
			} as any).equals(Buffer.from([0xaa, 22, 2, 0, 3, 1])),
		).toBe(true)

		const relative = encodeBotMsg({
			type: "armMoveRelative",
			speed: 160,
			dx: 12.5,
			dy: -4,
		} as any)
		const relativePayload = Buffer.alloc(10)
		relativePayload.writeUInt16LE(160, 0)
		relativePayload.writeFloatLE(12.5, 2)
		relativePayload.writeFloatLE(-4, 6)
		expect(
			relative.equals(
				Buffer.concat([Buffer.from([0xaa, 23, 10, 0]), relativePayload]),
			),
		).toBe(true)
	})

	test("decodes a MyInfo message with version, variant, and name", () => {
		const version = "3.2.1"
		const variant = "PuppyBot"
		const deviceName = "rover"
		const botId = "bot-123"
		const buffer = Buffer.alloc(
			3 +
				1 +
				version.length +
				1 +
				variant.length +
				1 +
				deviceName.length +
				1 +
				botId.length,
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
		offset += deviceName.length
		buffer.writeUInt8(botId.length, offset)
		offset += 1
		buffer.write(botId, offset)

		const msg = decodeBotMsg(buffer)
		expect(msg).toEqual({
			type: MsgFromBotType.MyInfo,
			protocolVersion: 1,
			firmwareVersion: version,
			variant,
			deviceName,
			botId,
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

	test("decodes an arm state message", () => {
		const fault = Buffer.from("limit")
		const buffer = Buffer.alloc(3 + 1 + 25 + fault.length + 13)
		buffer.writeUInt16LE(1, 0)
		buffer.writeUInt8(MsgFromBotType.ArmState, 2)
		buffer.writeUInt8(1, 3)
		let offset = 4
		buffer.writeUInt8(2, offset)
		buffer.writeUInt8(0x1b, offset + 1)
		buffer.writeInt32LE(530, offset + 2)
		buffer.writeInt32LE(900, offset + 6)
		buffer.writeInt16LE(-120, offset + 10)
		buffer.writeInt32LE(100, offset + 12)
		buffer.writeInt32LE(1000, offset + 16)
		buffer.writeFloatLE(45.5, offset + 20)
		buffer.writeUInt8(fault.length, offset + 24)
		offset += 25
		fault.copy(buffer, offset)
		offset += fault.length
		buffer.writeUInt8(1, offset)
		buffer.writeFloatLE(10, offset + 1)
		buffer.writeFloatLE(20, offset + 5)
		buffer.writeFloatLE(30, offset + 9)

		const msg = decodeBotMsg(buffer)
		expect(msg.type).toBe(MsgFromBotType.ArmState)
		if (msg.type !== MsgFromBotType.ArmState) return
		expect(msg.state.joints).toEqual([
			{
				servoId: 2,
				online: true,
				hasFeedback: true,
				limitReached: false,
				hasTarget: true,
				hasFault: true,
				tick: 530,
				targetTick: 900,
				speed: -120,
				limitMin: 100,
				limitMax: 1000,
				angleDeg: 45.5,
				fault: "limit",
			},
		])
		expect(msg.state.coordsMm).toEqual({ x: 10, y: 20, z: 30 })
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

	test("encodes an arm state subscription message", () => {
		const msg: MsgToBot = {
			type: "subscribe",
			topic: "armState",
			enabled: true,
		}
		const buffer = encodeBotMsg(msg)
		const expectedHeader = Buffer.from([0xaa, 33, 2, 0])
		const expectedPayload = Buffer.from([1, 1])
		expect(
			buffer.equals(Buffer.concat([expectedHeader, expectedPayload])),
		).toBe(true)
	})
})
