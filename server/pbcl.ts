import { MotorConfig } from "./types"

const PBCL_MAGIC = 0x5042434c
const PBCL_VERSION = 1
const PBCL_CLASS_MOTOR = 1

const MOTOR_TYPE: Record<MotorConfig["type"], number> = {
	angle: 1,
	continuous: 2,
	hbridge: 3,
}

const PBCL_T_NAME = 1
const PBCL_T_TIMEOUT = 3
const PBCL_T_M_PWM = 10
const PBCL_T_M_HBRIDGE = 11
const PBCL_T_M_ANALOG_FB = 12
const PBCL_T_M_LIMITS = 13

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
