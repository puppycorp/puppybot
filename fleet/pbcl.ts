import type { MotorConfig } from "./types"

const PBCL_MAGIC = 0x5042434c
const PBCL_VERSION = 1
const PBCL_CLASS_MOTOR = 1

const MOTOR_TYPE: Record<MotorConfig["type"], number> = {
	angle: 1,
	continuous: 2,
	hbridge: 3,
	smart: 4,
}

const PBCL_T_NAME = 1
const PBCL_T_TIMEOUT = 3
const PBCL_T_M_PWM = 10
const PBCL_T_M_HBRIDGE = 11
const PBCL_T_M_ANALOG_FB = 12
const PBCL_T_M_LIMITS = 13
const PBCL_T_M_SMART_BUS = 14

const MOTOR_TYPE_REVERSE: Record<number, MotorConfig["type"]> = {
	1: "angle",
	2: "continuous",
	3: "hbridge",
	4: "smart",
}

const crc32 = (data: Buffer, seed = 0xffffffff): number => {
	let crc = seed >>> 0
	for (let i = 0; i < data.length; i++) {
		crc ^= data[i]
		for (let bit = 0; bit < 8; bit++) {
			const mask = -(crc & 1)
			crc = (crc >>> 1) ^ (0xedb88320 & mask)
		}
	}
	return crc >>> 0
}

const tlv = (tag: number, value: Buffer): Buffer => {
	const header = Buffer.alloc(4)
	header.writeUInt8(tag, 0)
	header.writeUInt8(0, 1)
	header.writeUInt16LE(value.length, 2)
	return Buffer.concat([header, value])
}

const buildMotorSection = (config: MotorConfig): Buffer => {
	const typeId = MOTOR_TYPE[config.type]
	if (typeId === undefined) {
		throw new Error(`Unsupported motor type: ${config.type}`)
	}

	const tlvs: Buffer[] = []
	if (config.name) {
		tlvs.push(tlv(PBCL_T_NAME, Buffer.from(config.name, "utf8")))
	}
	if (config.timeoutMs !== undefined) {
		const timeout = Buffer.alloc(2)
		timeout.writeUInt16LE(Math.max(0, Math.min(0xffff, config.timeoutMs)))
		tlvs.push(tlv(PBCL_T_TIMEOUT, timeout))
	}
	if (config.maxSpeed !== undefined) {
		const limits = Buffer.alloc(4)
		limits.writeUInt16LE(
			Math.max(0, Math.min(0xffff, Math.round(config.maxSpeed * 100))),
			0,
		)
		limits.writeUInt16LE(0, 2)
		tlvs.push(tlv(PBCL_T_M_LIMITS, limits))
	}

	if (config.pwm) {
		const pwm = Buffer.alloc(12)
		pwm.writeInt8(config.pwm.pin, 0)
		pwm.writeUInt8(config.pwm.channel, 1)
		pwm.writeUInt16LE(config.pwm.freqHz, 2)
		pwm.writeUInt16LE(config.pwm.minUs, 4)
		pwm.writeUInt16LE(config.pwm.maxUs, 6)
		pwm.writeUInt16LE(config.pwm.neutralUs ?? 0, 8)
		pwm.writeUInt8(config.pwm.invert ? 1 : 0, 10)
		pwm.writeUInt8(0, 11)
		tlvs.push(tlv(PBCL_T_M_PWM, pwm))
	}

	if (config.hbridge) {
		const hbridge = Buffer.alloc(4)
		hbridge.writeInt8(config.hbridge.in1, 0)
		hbridge.writeInt8(config.hbridge.in2, 1)
		hbridge.writeUInt8(config.hbridge.brakeMode ? 1 : 0, 2)
		hbridge.writeUInt8(0, 3)
		tlvs.push(tlv(PBCL_T_M_HBRIDGE, hbridge))
	}

	if (config.analog) {
		const analog = Buffer.alloc(8)
		analog.writeInt8(config.analog.adcPin, 0)
		analog.writeUInt8(0, 1)
		analog.writeUInt16LE(config.analog.adcMin, 2)
		analog.writeUInt16LE(config.analog.adcMax, 4)
		analog.writeInt16LE(Math.round(config.analog.degMin * 10), 6)
		const ext = Buffer.alloc(2)
		ext.writeInt16LE(Math.round(config.analog.degMax * 10), 0)
		tlvs.push(tlv(PBCL_T_M_ANALOG_FB, Buffer.concat([analog, ext])))
	}

	if (config.smart) {
		const smart = Buffer.alloc(8)
		const baud = Math.max(
			1,
			Math.min(5_000_000, config.smart.baudRate ?? 1_000_000),
		)
		smart.writeInt8(config.smart.txPin, 0)
		smart.writeInt8(config.smart.rxPin, 1)
		smart.writeUInt8(config.smart.uartPort, 2)
		smart.writeUInt8(0, 3)
		smart.writeUInt32LE(baud, 4)
		tlvs.push(tlv(PBCL_T_M_SMART_BUS, smart))
	}

	const tlvPayload = Buffer.concat(tlvs)

	const sec = Buffer.alloc(12)
	sec.writeUInt16LE(PBCL_CLASS_MOTOR, 0)
	sec.writeUInt16LE(typeId, 2)
	sec.writeUInt32LE(config.nodeId >>> 0, 4)
	sec.writeUInt16LE(tlvPayload.length, 8)
	sec.writeUInt16LE(0, 10)

	return Buffer.concat([sec, tlvPayload])
}

export const buildMotorBlob = (motors: MotorConfig[]): Buffer => {
	const HEADER_SIZE = 20
	const sections = motors.map((m) => buildMotorSection(m))
	const body = Buffer.concat(sections)
	const totalSize = HEADER_SIZE + body.length
	const header = Buffer.alloc(HEADER_SIZE)
	header.writeUInt32LE(PBCL_MAGIC, 0)
	header.writeUInt16LE(PBCL_VERSION, 4)
	header.writeUInt16LE(0, 6)
	header.writeUInt16LE(motors.length, 8)
	header.writeUInt16LE(HEADER_SIZE, 10)
	header.writeUInt32LE(totalSize, 12)
	header.writeUInt32LE(0, 16)

	const crcSeed = crc32(header)
	const crc = crc32(body, crcSeed) ^ 0xffffffff
	header.writeUInt32LE(crc >>> 0, 16)

	return Buffer.concat([header, body])
}

export const parseMotorBlob = (blob: Uint8Array): MotorConfig[] => {
	const buffer = Buffer.from(blob)
	if (buffer.length < 20) {
		throw new Error("PBCL blob too short")
	}
	const magic = buffer.readUInt32LE(0)
	const version = buffer.readUInt16LE(4)
	const sections = buffer.readUInt16LE(8)
	const headerSize = buffer.readUInt16LE(10)
	const totalSize = buffer.readUInt32LE(12)
	if (magic !== PBCL_MAGIC) {
		throw new Error("PBCL blob has invalid magic")
	}
	if (version !== PBCL_VERSION) {
		throw new Error("PBCL blob has unsupported version")
	}
	if (headerSize < 20 || headerSize > buffer.length) {
		throw new Error("PBCL blob has invalid header size")
	}
	if (totalSize !== 0 && totalSize > buffer.length) {
		throw new Error("PBCL blob has invalid total size")
	}
	const motors: MotorConfig[] = []
	let offset = headerSize
	for (let i = 0; i < sections; i++) {
		if (offset + 12 > buffer.length) {
			break
		}
		const classId = buffer.readUInt16LE(offset)
		const typeId = buffer.readUInt16LE(offset + 2)
		const nodeId = buffer.readUInt32LE(offset + 4)
		const tlvLen = buffer.readUInt16LE(offset + 8)
		const sectionEnd = offset + 12 + tlvLen
		if (sectionEnd > buffer.length) {
			break
		}
		if (classId === PBCL_CLASS_MOTOR) {
			const type = MOTOR_TYPE_REVERSE[typeId]
			if (type) {
				const config: MotorConfig = { nodeId, type }
				let tlvOffset = offset + 12
				while (tlvOffset + 4 <= sectionEnd) {
					const tag = buffer.readUInt8(tlvOffset)
					const len = buffer.readUInt16LE(tlvOffset + 2)
					const valueOffset = tlvOffset + 4
					const valueEnd = valueOffset + len
					if (valueEnd > sectionEnd) {
						break
					}
					switch (tag) {
						case PBCL_T_NAME:
							config.name = buffer
								.subarray(valueOffset, valueEnd)
								.toString("utf8")
							break
						case PBCL_T_TIMEOUT:
							if (len >= 2) {
								config.timeoutMs = buffer.readUInt16LE(valueOffset)
							}
							break
						case PBCL_T_M_LIMITS:
							if (len >= 2) {
								config.maxSpeed =
									buffer.readUInt16LE(valueOffset) / 100
							}
							break
						case PBCL_T_M_PWM:
							if (len >= 12) {
								config.pwm = {
									pin: buffer.readInt8(valueOffset),
									channel: buffer.readUInt8(valueOffset + 1),
									freqHz: buffer.readUInt16LE(valueOffset + 2),
									minUs: buffer.readUInt16LE(valueOffset + 4),
									maxUs: buffer.readUInt16LE(valueOffset + 6),
									neutralUs: buffer.readUInt16LE(valueOffset + 8),
									invert: buffer.readUInt8(valueOffset + 10) === 1,
								}
							}
							break
						case PBCL_T_M_HBRIDGE:
							if (len >= 4) {
								config.hbridge = {
									in1: buffer.readInt8(valueOffset),
									in2: buffer.readInt8(valueOffset + 1),
									brakeMode: buffer.readUInt8(valueOffset + 2) === 1,
								}
							}
							break
						case PBCL_T_M_ANALOG_FB:
							if (len >= 10) {
								config.analog = {
									adcPin: buffer.readInt8(valueOffset),
									adcMin: buffer.readUInt16LE(valueOffset + 2),
									adcMax: buffer.readUInt16LE(valueOffset + 4),
									degMin: buffer.readInt16LE(valueOffset + 6) / 10,
									degMax: buffer.readInt16LE(valueOffset + 8) / 10,
								}
							}
							break
						case PBCL_T_M_SMART_BUS:
							if (len >= 8) {
								config.smart = {
									txPin: buffer.readInt8(valueOffset),
									rxPin: buffer.readInt8(valueOffset + 1),
									uartPort: buffer.readUInt8(valueOffset + 2),
									baudRate: buffer.readUInt32LE(valueOffset + 4),
								}
							}
							break
					}
					tlvOffset = valueEnd
				}
				motors.push(config)
			}
		}
		offset = sectionEnd
	}
	return motors
}
