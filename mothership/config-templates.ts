import type { MotorConfig } from "./types"

export const CUSTOM_TEMPLATE_KEY = "custom" as const

export type ConfigTemplateKey =
	| "puppybot"
	| "puppyarm_continuous"
	| "puppyarm_positional"

export type TemplateSelectionKey =
	| ConfigTemplateKey
	| typeof CUSTOM_TEMPLATE_KEY

export type ConfigTemplate = {
	key: ConfigTemplateKey
	name: string
	description: string
	variantMatches: string[]
	motors: MotorConfig[]
}

type TemplateRecord = Record<ConfigTemplateKey, ConfigTemplate>

const createPwm = (
	pin: number,
	channel: number,
	freqHz: number,
	minUs: number,
	maxUs: number,
	neutralUs?: number,
	invert?: boolean,
): NonNullable<MotorConfig["pwm"]> => {
	const pwm: NonNullable<MotorConfig["pwm"]> = {
		pin,
		channel,
		freqHz,
		minUs,
		maxUs,
	}
	if (neutralUs !== undefined) {
		pwm.neutralUs = neutralUs
	}
	if (invert) {
		pwm.invert = true
	}
	return pwm
}

const templates: TemplateRecord = {
	puppybot: {
		key: "puppybot",
		name: "PuppyBot rover",
		description:
			"Dual DC drive motors with a front steering servo, matching the default ESP32 rover wiring.",
		variantMatches: ["", "puppybot"],
		motors: [
			{
				nodeId: 1,
				type: "hbridge",
				name: "drive_left",
				pwm: createPwm(33, 0, 1000, 1000, 2000),
				hbridge: { in1: 25, in2: 26, brakeMode: false },
			},
			{
				nodeId: 2,
				type: "hbridge",
				name: "drive_right",
				pwm: createPwm(32, 1, 1000, 1000, 2000),
				hbridge: { in1: 27, in2: 14, brakeMode: false },
			},
			{
				nodeId: 100,
				type: "angle",
				name: "steering_servo",
				pwm: createPwm(13, 2, 50, 1000, 2000, 1500),
			},
		],
	},
	puppyarm_continuous: {
		key: "puppyarm_continuous",
		name: "PuppyArm continuous servos",
		description:
			"Four continuous-rotation servos for experimental arm builds that expect throttle-style control.",
		variantMatches: ["puppyarm_continuous"],
		motors: [
			{
				nodeId: 200,
				type: "continuous",
				name: "shoulder",
				pwm: createPwm(13, 2, 50, 1000, 2000, 1500),
			},
			{
				nodeId: 201,
				type: "continuous",
				name: "elbow",
				pwm: createPwm(21, 3, 50, 1000, 2000, 1500),
			},
			{
				nodeId: 202,
				type: "continuous",
				name: "wrist",
				pwm: createPwm(22, 4, 50, 1000, 2000, 1500),
			},
			{
				nodeId: 203,
				type: "continuous",
				name: "gripper",
				pwm: createPwm(23, 5, 50, 1000, 2000, 1500),
			},
		],
	},
	puppyarm_positional: {
		key: "puppyarm_positional",
		name: "PuppyArm positional servos",
		description:
			"Four standard servos centred at 90° for the PuppyArm joints outlined in the project README.",
		variantMatches: ["puppyarm", "puppyarm_positional"],
		motors: [
			{
				nodeId: 210,
				type: "angle",
				name: "base",
				pwm: createPwm(13, 2, 50, 1000, 2000, 1500),
			},
			{
				nodeId: 211,
				type: "angle",
				name: "shoulder",
				pwm: createPwm(21, 3, 50, 1000, 2000, 1500),
			},
			{
				nodeId: 212,
				type: "angle",
				name: "elbow",
				pwm: createPwm(22, 4, 50, 1000, 2000, 1500),
			},
			{
				nodeId: 213,
				type: "angle",
				name: "gripper",
				pwm: createPwm(23, 5, 50, 1000, 2000, 1500),
			},
		],
	},
}

export const CONFIG_TEMPLATES: TemplateRecord = templates

export const TEMPLATE_OPTIONS: Array<{
	key: TemplateSelectionKey
	name: string
	description: string
}> = [
	{
		key: CUSTOM_TEMPLATE_KEY,
		name: "Fully custom",
		description:
			"Start from an empty configuration and add motors manually for testing or bespoke rigs.",
	},
	...Object.values(templates).map((template) => ({
		key: template.key,
		name: template.name,
		description: template.description,
	})),
]

export const DEFAULT_TEMPLATE_KEY: ConfigTemplateKey = "puppybot"

const deepClone = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T

export const cloneTemplateMotors = (key: ConfigTemplateKey): MotorConfig[] =>
	deepClone(templates[key].motors)

export const isConfigTemplateKey = (
	value: string | null | undefined,
): value is ConfigTemplateKey => {
	if (!value) return false
	return Object.prototype.hasOwnProperty.call(templates, value)
}

const normalizeVariant = (variant?: string | null): string =>
	(variant ?? "").trim().toLowerCase()

export const templateForVariant = (
	variant?: string | null,
): ConfigTemplateKey | null => {
	const normalized = normalizeVariant(variant)
	if (!normalized) {
		return DEFAULT_TEMPLATE_KEY
	}
	for (const template of Object.values(templates)) {
		if (template.variantMatches.includes(normalized)) {
			return template.key
		}
	}
	return null
}

export const describeTemplate = (key: TemplateSelectionKey): string => {
	if (key === CUSTOM_TEMPLATE_KEY) {
		const custom = TEMPLATE_OPTIONS.find(
			(option) => option.key === CUSTOM_TEMPLATE_KEY,
		)
		return custom ? custom.description : ""
	}
	return templates[key]?.description ?? ""
}
