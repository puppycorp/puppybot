import type { MotorConfig, MsgToServer } from "../fleet/types"
import {
	TEMPLATE_OPTIONS,
	cloneTemplateMotors,
	describeTemplate,
	isConfigTemplateKey,
	type ConfigTemplateKey,
	type TemplateSelectionKey,
} from "../server/config-templates"
import { state } from "./state"
import type { BotConfigState } from "./state"
import { Container, UiComponent } from "./ui"
import { ws } from "./wsclient"

// class MotorController extends UiComponent<HTMLDivElement> {
//     constructor(args: {
//         title?: string
//         onForward?: (speed: number) => void
//         onReleased?: () => void
//         onBackward?: (speed: number) => void
//     }) {
//         super(document.createElement("div"))
//         this.root.style.display = "flex"
//         this.root.style.gap = "10px"

//         const label = document.createElement("label")
//         label.innerText = "Speed"
//         this.root.appendChild(label)

//         const speedInput = document.createElement("input")
//         speedInput.type = "number"
//         speedInput.value = "180"
//         this.root.appendChild(speedInput)

//         const forwardButton = document.createElement("button")
//         forwardButton.innerText = "Forward"
//         forwardButton.onmousedown = () => args.onForward?.(parseInt(speedInput.value))
//         forwardButton.onmouseup = () => args.onReleased?.()
//         this.root.appendChild(forwardButton)

//         const backwardButton = document.createElement("button")
//         backwardButton.innerText = "Backward"
//         backwardButton.onmousedown = () => args.onBackward?.(parseInt(speedInput.value))
//         backwardButton.onmouseup = () => args.onReleased?.()
//         this.root.appendChild(backwardButton)
//     }
// }

class FourWheelController extends UiComponent<HTMLDivElement> {
	constructor(args: {
		onForward?: (speed: number) => void
		onMoveLeft?: (speed: number) => void
		onMoveRight?: (speed: number) => void
		onBackward?: (speed: number) => void
		onReleased?: () => void
	}) {
		super(document.createElement("div"))

		const label = document.createElement("div")
		label.innerText = "Four Wheel Controller"
		label.style.fontSize = "20px"
		label.style.fontWeight = "bold"
		this.root.appendChild(label)

		this.root.style.display = "flex"
		this.root.style.gap = "5px"
		this.root.style.maxWidth = "200px"
		this.root.style.flexDirection = "column"

		const speedInput = document.createElement("input")
		speedInput.type = "number"
		speedInput.value = "180"
		this.root.appendChild(speedInput)

		const buttons = document.createElement("div")
		buttons.style.display = "flex"
		buttons.style.gap = "5px"
		buttons.style.flexDirection = "column"
		this.root.appendChild(buttons)

		const forwardButton = document.createElement("button")
		forwardButton.innerText = "Forward"
		let forwardInterval: number
		forwardButton.onmousedown = () => {
			const currentSpeed = parseInt(speedInput.value)
			args.onForward?.(currentSpeed)
			forwardInterval = window.setInterval(
				() => args.onForward?.(currentSpeed),
				500,
			)
		}
		forwardButton.onmouseup = () => {
			clearInterval(forwardInterval)
			args.onReleased?.()
		}
		buttons.appendChild(forwardButton)

		const hbuttons = document.createElement("div")
		hbuttons.style.display = "flex"
		hbuttons.style.gap = "5px"
		hbuttons.style.flexDirection = "row"
		buttons.appendChild(hbuttons)

		const leftButton = document.createElement("button")
		leftButton.innerText = "Left"
		leftButton.style.flexGrow = "1"
		let leftInterval: number
		leftButton.onmousedown = () => {
			const currentSpeed = parseInt(speedInput.value)
			args.onMoveLeft?.(currentSpeed)
			leftInterval = window.setInterval(
				() => args.onMoveLeft?.(currentSpeed),
				500,
			)
		}
		leftButton.onmouseup = () => {
			clearInterval(leftInterval)
			args.onReleased?.()
		}
		hbuttons.appendChild(leftButton)

		const rightButton = document.createElement("button")
		rightButton.innerText = "Right"
		rightButton.style.flexGrow = "1"
		let rightInterval: number
		rightButton.onmousedown = () => {
			const currentSpeed = parseInt(speedInput.value)
			args.onMoveRight?.(currentSpeed)
			rightInterval = window.setInterval(
				() => args.onMoveRight?.(currentSpeed),
				500,
			)
		}
		rightButton.onmouseup = () => {
			clearInterval(rightInterval)
			args.onReleased?.()
		}
		hbuttons.appendChild(rightButton)

		const backwardButton = document.createElement("button")
		backwardButton.innerText = "Backward"
		let backwardInterval: number
		backwardButton.onmousedown = () => {
			const currentSpeed = parseInt(speedInput.value)
			args.onBackward?.(currentSpeed)
			backwardInterval = window.setInterval(
				() => args.onBackward?.(currentSpeed),
				500,
			)
		}
		backwardButton.onmouseup = () => {
			clearInterval(backwardInterval)
			args.onReleased?.()
		}
		buttons.appendChild(backwardButton)
	}
}

export const botPage = (container: Container, botId: string) => {
	if (!botId) {
		container.root.innerText = "No bot ID provided"
		return
	}

	container.clear()

	const statusCard = document.createElement("div")
	statusCard.className = "card status-card"

	const statusTitle = document.createElement("h2")
	statusTitle.textContent = `Bot ${botId}`
	statusTitle.style.margin = "0"
	statusCard.appendChild(statusTitle)

	const statusBadge = document.createElement("span")
	statusBadge.className = "status-pill"
	statusBadge.textContent = "Disconnected"
	statusCard.appendChild(statusBadge)

	const firmwareText = document.createElement("div")
	firmwareText.className = "info-text"
	firmwareText.textContent = "Firmware: -"
	statusCard.appendChild(firmwareText)

	const variantText = document.createElement("div")
	variantText.className = "info-text"
	variantText.textContent = "Variant: -"
	statusCard.appendChild(variantText)

	state.bots.onChange((bots) => {
		const bot = bots.find((candidate) => candidate.id === botId)
		if (bot) {
			statusBadge.textContent = bot.connected
				? "Connected"
				: "Disconnected"
			statusBadge.classList.toggle("connected", bot.connected)
			firmwareText.textContent = `Firmware: ${bot.version || "-"}`
			variantText.textContent = `Variant: ${bot.variant || "-"}`
		} else {
			statusBadge.textContent = "Disconnected"
			statusBadge.classList.remove("connected")
			firmwareText.textContent = "Firmware: -"
			variantText.textContent = "Variant: -"
		}
	})

	container.root.appendChild(statusCard)

	const configCard = document.createElement("div")
	configCard.className = "card"

	const configTitle = document.createElement("h3")
	configTitle.textContent = "Motor configuration"
	configTitle.style.margin = "0"
	configCard.appendChild(configTitle)

	const configHelp = document.createElement("p")
	configHelp.className = "section-note"
	configHelp.innerText =
		"Configure each motor using the form below. Add motors, edit fields, and apply to sync the PBCL blob."
	configCard.appendChild(configHelp)

	const templateSelect = document.createElement("select")
	TEMPLATE_OPTIONS.forEach((option) => {
		const opt = document.createElement("option")
		opt.value = option.key
		opt.textContent = option.name
		templateSelect.appendChild(opt)
	})

	const templateWrapper = document.createElement("label")
	templateWrapper.className = "field"
	const templateLabel = document.createElement("span")
	templateLabel.textContent = "Configuration template"
	templateWrapper.appendChild(templateLabel)
	templateWrapper.appendChild(templateSelect)
	configCard.appendChild(templateWrapper)

	const templateDescription = document.createElement("p")
	templateDescription.className = "section-note"
	configCard.appendChild(templateDescription)

	const motorsContainer = document.createElement("div")
	motorsContainer.className = "motors-container"
	configCard.appendChild(motorsContainer)

	const configActions = document.createElement("div")
	configActions.className = "config-actions"
	configCard.appendChild(configActions)

	const configActionsLeft = document.createElement("div")
	configActionsLeft.className = "config-actions-left"
	configActions.appendChild(configActionsLeft)

	const configActionsRight = document.createElement("div")
	configActionsRight.className = "config-actions-right"
	configActions.appendChild(configActionsRight)

	const addMotorButton = document.createElement("button")
	addMotorButton.classList.add("secondary")
	addMotorButton.textContent = "Add motor"
	configActionsLeft.appendChild(addMotorButton)

	const applyConfigButton = document.createElement("button")
	applyConfigButton.textContent = "Apply configuration"
	configActionsRight.appendChild(applyConfigButton)

	const createFieldWrapper = <T extends HTMLInputElement | HTMLSelectElement>(
		label: string,
		input: T,
	): HTMLLabelElement => {
		const wrapper = document.createElement("label")
		wrapper.className = "field"
		const labelText = document.createElement("span")
		labelText.textContent = label
		wrapper.appendChild(labelText)
		wrapper.appendChild(input)
		return wrapper
	}

	const parseInteger = (value: string): number | undefined => {
		if (!value.trim()) return undefined
		const parsed = Number.parseInt(value, 10)
		return Number.isNaN(parsed) ? undefined : parsed
	}

	const parseNumber = (value: string): number | undefined => {
		if (!value.trim()) return undefined
		const parsed = Number.parseFloat(value)
		return Number.isNaN(parsed) ? undefined : parsed
	}

	const cloneMotorConfig = (config: MotorConfig): MotorConfig => {
		if (typeof structuredClone === "function") {
			return structuredClone(config)
		}
		return JSON.parse(JSON.stringify(config)) as MotorConfig
	}

	let motors: MotorConfig[] = []

	const ensurePwmConfig = (config: MotorConfig): void => {
		if (!config.pwm) {
			config.pwm = {
				pin: 0,
				channel: 0,
				freqHz: 50,
				minUs: 1000,
				maxUs: 2000,
				neutralUs: 1500,
				invert: false,
			}
		}
	}

	const ensureAnalogConfig = (config: MotorConfig): void => {
		if (!config.analog) {
			config.analog = {
				adcPin: 0,
				adcMin: 0,
				adcMax: 4095,
				degMin: 0,
				degMax: 180,
			}
		}
	}

	const ensureHBridgeConfig = (config: MotorConfig): void => {
		if (!config.hbridge) {
			config.hbridge = {
				in1: 0,
				in2: 1,
				brakeMode: false,
			}
		}
	}

	const sanitizeMotor = (motor: MotorConfig): MotorConfig => {
		const toInt = (value: number | undefined): number | undefined =>
			value !== undefined && Number.isFinite(value)
				? Math.round(value)
				: undefined
		const toFloat = (value: number | undefined): number | undefined =>
			value !== undefined && Number.isFinite(value) ? value : undefined

		const baseNodeId = toInt(motor.nodeId) ?? 0
		const sanitized: MotorConfig = {
			nodeId: baseNodeId,
			type: motor.type,
		}

		if (motor.name && motor.name.trim()) {
			sanitized.name = motor.name.trim()
		}

		const timeout = toInt(motor.timeoutMs)
		if (timeout !== undefined) {
			sanitized.timeoutMs = Math.max(0, timeout)
		}

		const maxSpeed = toFloat(motor.maxSpeed)
		if (maxSpeed !== undefined) {
			sanitized.maxSpeed = Math.max(0, maxSpeed)
		}

		if (motor.pwm) {
			const { pin, channel, freqHz, minUs, maxUs, neutralUs, invert } =
				motor.pwm
			if (
				[pin, channel, freqHz, minUs, maxUs].every(
					(value) => value !== undefined && Number.isFinite(value),
				)
			) {
				sanitized.pwm = {
					pin: Math.round(pin),
					channel: Math.round(channel),
					freqHz: Math.round(freqHz),
					minUs: Math.round(minUs),
					maxUs: Math.round(maxUs),
				}
				const neutral = toInt(neutralUs)
				if (neutral !== undefined) {
					sanitized.pwm.neutralUs = Math.max(0, neutral)
				}
				if (invert) {
					sanitized.pwm.invert = true
				}
			}
		}

		if (motor.hbridge) {
			const { in1, in2, brakeMode } = motor.hbridge
			if (
				[in1, in2].every(
					(value) => value !== undefined && Number.isFinite(value),
				)
			) {
				sanitized.hbridge = {
					in1: Math.round(in1!),
					in2: Math.round(in2!),
				}
				if (brakeMode) {
					sanitized.hbridge.brakeMode = true
				}
			}
		}

		if (motor.analog) {
			const { adcPin, adcMin, adcMax, degMin, degMax } = motor.analog
			if (
				[adcPin, adcMin, adcMax, degMin, degMax].every(
					(value) => value !== undefined && Number.isFinite(value),
				)
			) {
				sanitized.analog = {
					adcPin: Math.round(adcPin),
					adcMin: Math.round(adcMin),
					adcMax: Math.round(adcMax),
					degMin: degMin,
					degMax: degMax,
				}
			}
		}

		return sanitized
	}

	const createMotorCard = (
		motor: MotorConfig,
		index: number,
	): HTMLDivElement => {
		const card = document.createElement("div")
		card.className = "motor-card"

		const header = document.createElement("div")
		header.className = "motor-card-header"
		card.appendChild(header)

		const title = document.createElement("h4")
		const fallbackTitle = `Motor ${index + 1}`
		title.textContent = motor.name?.trim() || fallbackTitle
		header.appendChild(title)

		const removeButton = document.createElement("button")
		removeButton.classList.add("secondary", "danger")
		removeButton.textContent = "Remove"
		removeButton.onclick = () => {
			motors.splice(index, 1)
			renderMotors()
		}
		header.appendChild(removeButton)

		const grid = document.createElement("div")
		grid.className = "motor-grid"
		card.appendChild(grid)

		const nameInput = document.createElement("input")
		nameInput.type = "text"
		nameInput.placeholder = "Display name"
		nameInput.value = motor.name ?? ""
		nameInput.addEventListener("input", () => {
			const trimmed = nameInput.value.trim()
			motor.name = trimmed.length ? nameInput.value : undefined
			title.textContent = trimmed.length ? nameInput.value : fallbackTitle
		})
		grid.appendChild(createFieldWrapper("Name", nameInput))

		const nodeInput = document.createElement("input")
		nodeInput.type = "number"
		nodeInput.min = "0"
		nodeInput.value = motor.nodeId?.toString() ?? "0"
		nodeInput.addEventListener("input", () => {
			const parsed = parseInteger(nodeInput.value)
			if (parsed !== undefined) {
				motor.nodeId = parsed
			}
		})
		grid.appendChild(createFieldWrapper("Node ID", nodeInput))

		const typeSelect = document.createElement("select")
		;[
			{ value: "angle", label: "Angle (servo)" },
			{ value: "continuous", label: "Continuous" },
			{ value: "hbridge", label: "H-Bridge" },
		].forEach((option) => {
			const opt = document.createElement("option")
			opt.value = option.value
			opt.textContent = option.label
			typeSelect.appendChild(opt)
		})
		typeSelect.value = motor.type
		typeSelect.addEventListener("change", () => {
			motor.type = typeSelect.value as MotorConfig["type"]
		})
		grid.appendChild(createFieldWrapper("Motor type", typeSelect))

		const timeoutInput = document.createElement("input")
		timeoutInput.type = "number"
		timeoutInput.min = "0"
		timeoutInput.placeholder = "ms"
		timeoutInput.value = motor.timeoutMs?.toString() ?? ""
		timeoutInput.addEventListener("input", () => {
			const parsed = parseInteger(timeoutInput.value)
			if (parsed === undefined) {
				delete motor.timeoutMs
				return
			}
			motor.timeoutMs = Math.max(0, parsed)
		})
		grid.appendChild(createFieldWrapper("Timeout", timeoutInput))

		const maxSpeedInput = document.createElement("input")
		maxSpeedInput.type = "number"
		maxSpeedInput.min = "0"
		maxSpeedInput.step = "0.01"
		maxSpeedInput.placeholder = "units"
		maxSpeedInput.value =
			motor.maxSpeed !== undefined ? motor.maxSpeed.toString() : ""
		maxSpeedInput.addEventListener("input", () => {
			const parsed = parseNumber(maxSpeedInput.value)
			if (parsed === undefined) {
				delete motor.maxSpeed
				return
			}
			motor.maxSpeed = Math.max(0, parsed)
		})
		grid.appendChild(createFieldWrapper("Max speed", maxSpeedInput))

		const addToggleSection = (
			label: string,
			isEnabled: boolean,
			onToggle: (enabled: boolean) => void,
		): HTMLDivElement => {
			const wrapper = document.createElement("div")
			wrapper.className = "motor-section-title"
			const toggle = document.createElement("input")
			toggle.type = "checkbox"
			toggle.checked = isEnabled
			toggle.addEventListener("change", () => onToggle(toggle.checked))
			wrapper.appendChild(toggle)
			const text = document.createElement("span")
			text.textContent = label
			wrapper.appendChild(text)
			return wrapper
		}

		const pwmSectionHeader = addToggleSection(
			"PWM output",
			!!motor.pwm,
			(enabled) => {
				if (enabled) {
					ensurePwmConfig(motor)
				} else {
					delete motor.pwm
				}
				renderMotors()
			},
		)
		card.appendChild(pwmSectionHeader)

		if (motor.pwm) {
			const pwmGrid = document.createElement("div")
			pwmGrid.className = "motor-grid"
			card.appendChild(pwmGrid)

			const pwmPinInput = document.createElement("input")
			pwmPinInput.type = "number"
			pwmPinInput.value = motor.pwm.pin.toString()
			pwmPinInput.addEventListener("input", () => {
				const parsed = parseInteger(pwmPinInput.value)
				if (parsed !== undefined) {
					motor.pwm!.pin = parsed
				}
			})
			pwmGrid.appendChild(createFieldWrapper("PWM pin", pwmPinInput))

			const pwmChannelInput = document.createElement("input")
			pwmChannelInput.type = "number"
			pwmChannelInput.min = "0"
			pwmChannelInput.value = motor.pwm.channel.toString()
			pwmChannelInput.addEventListener("input", () => {
				const parsed = parseInteger(pwmChannelInput.value)
				if (parsed !== undefined) {
					motor.pwm!.channel = Math.max(0, parsed)
				}
			})
			pwmGrid.appendChild(
				createFieldWrapper("PWM channel", pwmChannelInput),
			)

			const pwmFreqInput = document.createElement("input")
			pwmFreqInput.type = "number"
			pwmFreqInput.min = "1"
			pwmFreqInput.value = motor.pwm.freqHz.toString()
			pwmFreqInput.addEventListener("input", () => {
				const parsed = parseInteger(pwmFreqInput.value)
				if (parsed !== undefined) {
					motor.pwm!.freqHz = Math.max(1, parsed)
				}
			})
			pwmGrid.appendChild(
				createFieldWrapper("PWM freq (Hz)", pwmFreqInput),
			)

			const pwmMinInput = document.createElement("input")
			pwmMinInput.type = "number"
			pwmMinInput.min = "0"
			pwmMinInput.value = motor.pwm.minUs.toString()
			pwmMinInput.addEventListener("input", () => {
				const parsed = parseInteger(pwmMinInput.value)
				if (parsed !== undefined) {
					motor.pwm!.minUs = Math.max(0, parsed)
				}
			})
			pwmGrid.appendChild(
				createFieldWrapper("Pulse min (µs)", pwmMinInput),
			)

			const pwmMaxInput = document.createElement("input")
			pwmMaxInput.type = "number"
			pwmMaxInput.min = "0"
			pwmMaxInput.value = motor.pwm.maxUs.toString()
			pwmMaxInput.addEventListener("input", () => {
				const parsed = parseInteger(pwmMaxInput.value)
				if (parsed !== undefined) {
					motor.pwm!.maxUs = Math.max(0, parsed)
				}
			})
			pwmGrid.appendChild(
				createFieldWrapper("Pulse max (µs)", pwmMaxInput),
			)

			const pwmNeutralInput = document.createElement("input")
			pwmNeutralInput.type = "number"
			pwmNeutralInput.min = "0"
			pwmNeutralInput.placeholder = "Optional"
			pwmNeutralInput.value =
				motor.pwm.neutralUs !== undefined
					? motor.pwm.neutralUs.toString()
					: ""
			pwmNeutralInput.addEventListener("input", () => {
				const parsed = parseInteger(pwmNeutralInput.value)
				if (parsed === undefined) {
					delete motor.pwm!.neutralUs
					return
				}
				motor.pwm!.neutralUs = Math.max(0, parsed)
			})
			pwmGrid.appendChild(
				createFieldWrapper("Pulse neutral (µs)", pwmNeutralInput),
			)

			const pwmInvertWrapper = document.createElement("label")
			pwmInvertWrapper.className = "field"
			const pwmInvertLabel = document.createElement("span")
			pwmInvertLabel.textContent = "Invert"
			pwmInvertWrapper.appendChild(pwmInvertLabel)
			const pwmInvertInput = document.createElement("input")
			pwmInvertInput.type = "checkbox"
			pwmInvertInput.checked = motor.pwm.invert ?? false
			pwmInvertInput.addEventListener("change", () => {
				motor.pwm!.invert = pwmInvertInput.checked
			})
			pwmInvertWrapper.appendChild(pwmInvertInput)
			pwmGrid.appendChild(pwmInvertWrapper)
		}

		const hbridgeHeader = addToggleSection(
			"H-Bridge control",
			!!motor.hbridge,
			(enabled) => {
				if (enabled) {
					ensureHBridgeConfig(motor)
				} else {
					delete motor.hbridge
				}
				renderMotors()
			},
		)
		card.appendChild(hbridgeHeader)

		if (motor.hbridge) {
			const hbridgeGrid = document.createElement("div")
			hbridgeGrid.className = "motor-grid"
			card.appendChild(hbridgeGrid)

			const in1Input = document.createElement("input")
			in1Input.type = "number"
			in1Input.value = motor.hbridge.in1.toString()
			in1Input.addEventListener("input", () => {
				const parsed = parseInteger(in1Input.value)
				if (parsed !== undefined) {
					motor.hbridge!.in1 = parsed
				}
			})
			hbridgeGrid.appendChild(createFieldWrapper("IN1 pin", in1Input))

			const in2Input = document.createElement("input")
			in2Input.type = "number"
			in2Input.value = motor.hbridge.in2.toString()
			in2Input.addEventListener("input", () => {
				const parsed = parseInteger(in2Input.value)
				if (parsed !== undefined) {
					motor.hbridge!.in2 = parsed
				}
			})
			hbridgeGrid.appendChild(createFieldWrapper("IN2 pin", in2Input))

			const brakeWrapper = document.createElement("label")
			brakeWrapper.className = "field"
			const brakeLabel = document.createElement("span")
			brakeLabel.textContent = "Brake mode"
			brakeWrapper.appendChild(brakeLabel)
			const brakeInput = document.createElement("input")
			brakeInput.type = "checkbox"
			brakeInput.checked = motor.hbridge.brakeMode ?? false
			brakeInput.addEventListener("change", () => {
				motor.hbridge!.brakeMode = brakeInput.checked
			})
			brakeWrapper.appendChild(brakeInput)
			hbridgeGrid.appendChild(brakeWrapper)
		}

		const analogHeader = addToggleSection(
			"Analog feedback",
			!!motor.analog,
			(enabled) => {
				if (enabled) {
					ensureAnalogConfig(motor)
				} else {
					delete motor.analog
				}
				renderMotors()
			},
		)
		card.appendChild(analogHeader)

		if (motor.analog) {
			const analogGrid = document.createElement("div")
			analogGrid.className = "motor-grid"
			card.appendChild(analogGrid)

			const adcPinInput = document.createElement("input")
			adcPinInput.type = "number"
			adcPinInput.value = motor.analog.adcPin.toString()
			adcPinInput.addEventListener("input", () => {
				const parsed = parseInteger(adcPinInput.value)
				if (parsed !== undefined) {
					motor.analog!.adcPin = parsed
				}
			})
			analogGrid.appendChild(createFieldWrapper("ADC pin", adcPinInput))

			const adcMinInput = document.createElement("input")
			adcMinInput.type = "number"
			adcMinInput.min = "0"
			adcMinInput.value = motor.analog.adcMin.toString()
			adcMinInput.addEventListener("input", () => {
				const parsed = parseInteger(adcMinInput.value)
				if (parsed !== undefined) {
					motor.analog!.adcMin = Math.max(0, parsed)
				}
			})
			analogGrid.appendChild(createFieldWrapper("ADC min", adcMinInput))

			const adcMaxInput = document.createElement("input")
			adcMaxInput.type = "number"
			adcMaxInput.min = "0"
			adcMaxInput.value = motor.analog.adcMax.toString()
			adcMaxInput.addEventListener("input", () => {
				const parsed = parseInteger(adcMaxInput.value)
				if (parsed !== undefined) {
					motor.analog!.adcMax = Math.max(0, parsed)
				}
			})
			analogGrid.appendChild(createFieldWrapper("ADC max", adcMaxInput))

			const degMinInput = document.createElement("input")
			degMinInput.type = "number"
			degMinInput.step = "0.1"
			degMinInput.value = motor.analog.degMin.toString()
			degMinInput.addEventListener("input", () => {
				const parsed = parseNumber(degMinInput.value)
				if (parsed !== undefined) {
					motor.analog!.degMin = parsed
				}
			})
			analogGrid.appendChild(
				createFieldWrapper("Degrees min", degMinInput),
			)

			const degMaxInput = document.createElement("input")
			degMaxInput.type = "number"
			degMaxInput.step = "0.1"
			degMaxInput.value = motor.analog.degMax.toString()
			degMaxInput.addEventListener("input", () => {
				const parsed = parseNumber(degMaxInput.value)
				if (parsed !== undefined) {
					motor.analog!.degMax = parsed
				}
			})
			analogGrid.appendChild(
				createFieldWrapper("Degrees max", degMaxInput),
			)
		}

		// Motor Control Interface Section
		const controlSection = document.createElement("div")
		controlSection.className = "motor-section-title"
		controlSection.style.marginTop = "8px"
		const controlTitle = document.createElement("span")
		controlTitle.textContent = "Motor Control"
		controlTitle.style.fontWeight = "600"
		controlSection.appendChild(controlTitle)
		card.appendChild(controlSection)

		const controlContainer = document.createElement("div")
		controlContainer.style.display = "flex"
		controlContainer.style.flexDirection = "column"
		controlContainer.style.gap = "8px"
		controlContainer.style.marginTop = "8px"
		card.appendChild(controlContainer)

		if (motor.type === "angle") {
			// Positional motor - angle slider (0-180 degrees)
			const angleControlRow = document.createElement("div")
			angleControlRow.style.display = "flex"
			angleControlRow.style.alignItems = "center"
			angleControlRow.style.gap = "8px"

			const angleLabel = document.createElement("span")
			angleLabel.textContent = "Angle"
			angleLabel.style.width = "60px"
			angleControlRow.appendChild(angleLabel)

			const angleSlider = document.createElement("input")
			angleSlider.type = "range"
			angleSlider.min = "0"
			angleSlider.max = "180"
			angleSlider.value = "90"
			angleSlider.style.flexGrow = "1"
			angleControlRow.appendChild(angleSlider)

			const angleValue = document.createElement("span")
			angleValue.textContent = "90°"
			angleValue.style.width = "50px"
			angleValue.style.textAlign = "right"
			angleControlRow.appendChild(angleValue)

			angleSlider.addEventListener("input", () => {
				const angle = Number(angleSlider.value)
				angleValue.textContent = `${angle}°`
				ws.send({
					type: "turnServo",
					botId,
					servoId: motor.nodeId,
					angle: angle,
				} as MsgToServer)
			})

			controlContainer.appendChild(angleControlRow)

			// Add center and stop buttons
			const buttonRow = document.createElement("div")
			buttonRow.style.display = "flex"
			buttonRow.style.gap = "8px"

			const centerButton = document.createElement("button")
			centerButton.textContent = "Center (90°)"
			centerButton.classList.add("secondary")
			centerButton.onclick = () => {
				angleSlider.value = "90"
				angleValue.textContent = "90°"
				ws.send({
					type: "turnServo",
					botId,
					servoId: motor.nodeId,
					angle: 90,
				} as MsgToServer)
			}
			buttonRow.appendChild(centerButton)

			const stopButton = document.createElement("button")
			stopButton.textContent = "Stop"
			stopButton.classList.add("secondary")
			stopButton.onclick = () => {
				ws.send({
					type: "stop",
					botId,
				} as MsgToServer)
			}
			buttonRow.appendChild(stopButton)

			controlContainer.appendChild(buttonRow)
		} else if (motor.type === "continuous" || motor.type === "hbridge") {
			// Continuous/H-bridge motor - speed and direction slider (-100 to 100)
			const speedControlRow = document.createElement("div")
			speedControlRow.style.display = "flex"
			speedControlRow.style.alignItems = "center"
			speedControlRow.style.gap = "8px"

			const speedLabel = document.createElement("span")
			speedLabel.textContent = "Speed"
			speedLabel.style.width = "60px"
			speedControlRow.appendChild(speedLabel)

			const speedSlider = document.createElement("input")
			speedSlider.type = "range"
			speedSlider.min = "-100"
			speedSlider.max = "100"
			speedSlider.value = "0"
			speedSlider.style.flexGrow = "1"
			speedControlRow.appendChild(speedSlider)

			const speedValue = document.createElement("span")
			speedValue.textContent = "0"
			speedValue.style.width = "50px"
			speedValue.style.textAlign = "right"
			speedControlRow.appendChild(speedValue)

			speedSlider.addEventListener("input", () => {
				const speed = Number(speedSlider.value)
				speedValue.textContent = `${speed}`
				ws.send({
					type: "drive",
					botId,
					motorId: motor.nodeId,
					speed: speed,
				} as MsgToServer)
			})

			controlContainer.appendChild(speedControlRow)

			// Add direction and stop buttons
			const buttonRow = document.createElement("div")
			buttonRow.style.display = "flex"
			buttonRow.style.gap = "8px"

			const reverseButton = document.createElement("button")
			reverseButton.textContent = "Reverse"
			reverseButton.classList.add("secondary")
			reverseButton.onclick = () => {
				speedSlider.value = "-50"
				speedValue.textContent = "-50"
				ws.send({
					type: "drive",
					botId,
					motorId: motor.nodeId,
					speed: -50,
				} as MsgToServer)
			}
			buttonRow.appendChild(reverseButton)

			const stopButton = document.createElement("button")
			stopButton.textContent = "Stop"
			stopButton.classList.add("secondary")
			stopButton.onclick = () => {
				speedSlider.value = "0"
				speedValue.textContent = "0"
				ws.send({
					type: "drive",
					botId,
					motorId: motor.nodeId,
					speed: 0,
				} as MsgToServer)
			}
			buttonRow.appendChild(stopButton)

			const forwardButton = document.createElement("button")
			forwardButton.textContent = "Forward"
			forwardButton.classList.add("secondary")
			forwardButton.onclick = () => {
				speedSlider.value = "50"
				speedValue.textContent = "50"
				ws.send({
					type: "drive",
					botId,
					motorId: motor.nodeId,
					speed: 50,
				} as MsgToServer)
			}
			buttonRow.appendChild(forwardButton)

			controlContainer.appendChild(buttonRow)
		}

		return card
	}

	const renderMotors = () => {
		motorsContainer.innerHTML = ""
		if (motors.length === 0) {
			const empty = document.createElement("div")
			empty.className = "empty-state"
			empty.textContent =
				'No motors configured yet. Click "Add motor" to create one.'
			motorsContainer.appendChild(empty)
			return
		}
		motors.forEach((motor, idx) => {
			motorsContainer.appendChild(createMotorCard(motor, idx))
		})
	}

	const updateTemplateDescription = (key: TemplateSelectionKey) => {
		if (key === "custom") {
			templateDescription.textContent =
				"Custom motors. Build your configuration by adding motors manually."
		} else if (isConfigTemplateKey(key)) {
			const desc = describeTemplate(key)
			templateDescription.textContent = desc
		} else {
			templateDescription.textContent = ""
		}
	}

	templateSelect.addEventListener("change", () => {
		const value = templateSelect.value as TemplateSelectionKey
		updateTemplateDescription(value)

		if (value === "custom") {
			return
		}

		if (!isConfigTemplateKey(value)) {
			return
		}

		motors = cloneTemplateMotors(value).map((config) =>
			cloneMotorConfig(config),
		)
		renderMotors()
		state.configs.set({
			...state.configs.get(),
			[botId]: {
				motors: motors.map((motor) => cloneMotorConfig(motor)),
				templateKey: value,
			},
		})

		ws.send({
			type: "updateConfig",
			botId,
			motors: motors.map((motor) => sanitizeMotor(motor)),
			templateKey: value,
		} as MsgToServer)
	})

	addMotorButton.onclick = () => {
		motors.push({
			nodeId: motors.length ? motors[motors.length - 1].nodeId + 1 : 1,
			type: "angle",
		})
		renderMotors()
	}

	applyConfigButton.onclick = () => {
		if (motors.length === 0) {
			if (!confirm("Apply an empty configuration?")) {
				return
			}
		}

		for (let idx = 0; idx < motors.length; idx++) {
			const motor = motors[idx]
			if (!Number.isFinite(motor.nodeId)) {
				alert(`Motor ${idx + 1} must have a node ID.`)
				return
			}
			if (!motor.type) {
				alert(`Motor ${idx + 1} must have a type.`)
				return
			}
			if (motor.pwm) {
				const { pin, channel, freqHz, minUs, maxUs } = motor.pwm
				if (
					![pin, channel, freqHz, minUs, maxUs].every(
						(value) =>
							value !== undefined && Number.isFinite(value),
					)
				) {
					alert(
						`Complete all PWM fields before applying (motor ${idx + 1}).`,
					)
					return
				}
			}
			if (motor.hbridge) {
				const { in1, in2 } = motor.hbridge
				if (
					![in1, in2].every(
						(value) =>
							value !== undefined && Number.isFinite(value),
					)
				) {
					alert(
						`Complete all H-Bridge fields before applying (motor ${idx + 1}).`,
					)
					return
				}
			}
			if (motor.analog) {
				const { adcPin, adcMin, adcMax, degMin, degMax } = motor.analog
				if (
					![adcPin, adcMin, adcMax, degMin, degMax].every(
						(value) =>
							value !== undefined && Number.isFinite(value),
					)
				) {
					alert(
						`Complete all analog feedback fields before applying (motor ${idx + 1}).`,
					)
					return
				}
			}
		}

		const sanitized = motors.map((motor) => sanitizeMotor(motor))

		ws.send({
			type: "updateConfig",
			botId,
			motors: sanitized,
			templateKey: null,
		} as MsgToServer)
	}

	const syncMotorsFromState = (botConfig: BotConfigState | undefined) => {
		motors = botConfig?.motors
			? botConfig.motors.map((config) => cloneMotorConfig(config))
			: []
		const templateKey = botConfig?.templateKey ?? "custom"
		templateSelect.value = templateKey
		updateTemplateDescription(templateKey)
		renderMotors()
	}

	state.configs.onChange((configs) => {
		syncMotorsFromState(configs[botId])
	})

	syncMotorsFromState(state.configs.get()[botId])

	container.root.appendChild(configCard)

	// ensure wheels are centered on load
	const centerAngle = 88

	const speed = -80

	const driveLeft = 1
	const driveRight = 2

	const leftAngle = 50
	const rightAngle = 150

	const servoInitialAngles = [centerAngle, 90, 90, 90]
	const servoSliders: HTMLInputElement[] = []
	const servoValueLabels: HTMLSpanElement[] = []
	let sharedServoTimeout: number | undefined

	const setSharedServoTimeout = (value: number | undefined) => {
		if (value === undefined || Number.isNaN(value) || value <= 0) {
			sharedServoTimeout = undefined
			return
		}
		sharedServoTimeout = Math.min(0xffff, Math.max(1, Math.round(value)))
	}

	const sendServoAngle = (
		servoId: number,
		angle: number,
		durationOverride?: number,
	) => {
		const clamped = Math.max(0, Math.min(180, Math.round(angle)))
		const slider = servoSliders[servoId]
		const valueLabel = servoValueLabels[servoId]
		if (slider) {
			slider.value = clamped.toString()
		}
		if (valueLabel) {
			valueLabel.textContent = `${clamped}\u00B0`
		}
		let duration =
			durationOverride !== undefined
				? Math.max(0, Math.min(0xffff, Math.round(durationOverride)))
				: sharedServoTimeout
		if (duration === 0) duration = undefined
		const msg: MsgToServer = {
			type: "turnServo",
			botId,
			servoId,
			angle: clamped,
		}
		if (duration !== undefined) {
			msg.durationMs = duration
		}
		ws.send(msg)
	}

	const steeringServoId = 0

	const moveForward = () => {
		ws.send({ type: "drive", botId, motorId: driveLeft, speed: -speed })
		ws.send({ type: "drive", botId, motorId: driveRight, speed: speed })
	}

	const moveBackward = () => {
		ws.send({ type: "drive", botId, motorId: driveLeft, speed: speed })
		ws.send({ type: "drive", botId, motorId: driveRight, speed: -speed })
	}

	const turnLeft = () => {
		sendServoAngle(steeringServoId, leftAngle)
	}

	const turnRight = () => {
		sendServoAngle(steeringServoId, rightAngle)
	}

	const centerServo = (servoId: number) => {
		const fallbackAngle = servoInitialAngles[servoId]
		const targetAngle = fallbackAngle !== undefined ? fallbackAngle : 90
		sendServoAngle(servoId, targetAngle, 0)
	}

	const centerSteering = () => {
		centerServo(steeringServoId)
	}

	centerSteering()

	const servoSection = document.createElement("div")
	servoSection.className = "card"
	servoSection.style.display = "flex"
	servoSection.style.flexDirection = "column"
	servoSection.style.gap = "12px"

	const servoTitle = document.createElement("h3")
	servoTitle.innerText = "Servo controls"
	servoTitle.style.margin = "0"
	servoSection.appendChild(servoTitle)

	const servoControls = document.createElement("div")
	servoControls.style.display = "flex"
	servoControls.style.flexDirection = "column"
	servoControls.style.gap = "12px"
	servoSection.appendChild(servoControls)

	const sharedTimeoutRow = document.createElement("div")
	sharedTimeoutRow.style.display = "flex"
	sharedTimeoutRow.style.alignItems = "center"
	sharedTimeoutRow.style.gap = "8px"

	const timeoutLabel = document.createElement("span")
	timeoutLabel.textContent = "Servo timeout"
	timeoutLabel.style.width = "100px"
	sharedTimeoutRow.appendChild(timeoutLabel)

	const timeoutInput = document.createElement("input")
	timeoutInput.type = "number"
	timeoutInput.min = "0"
	timeoutInput.placeholder = "ms"
	timeoutInput.style.width = "80px"
	timeoutInput.addEventListener("input", () => {
		const parsed = Number.parseInt(timeoutInput.value, 10)
		if (!Number.isFinite(parsed) || parsed <= 0) {
			setSharedServoTimeout(undefined)
			timeoutInput.value = ""
			return
		}
		const sanitized = Math.min(0xffff, Math.max(1, Math.round(parsed)))
		timeoutInput.value = sanitized.toString()
		setSharedServoTimeout(sanitized)
	})
	sharedTimeoutRow.appendChild(timeoutInput)

	const timeoutHint = document.createElement("span")
	timeoutHint.textContent = "0 = disabled"
	timeoutHint.style.opacity = "0.7"
	timeoutHint.style.fontSize = "12px"
	sharedTimeoutRow.appendChild(timeoutHint)

	servoControls.appendChild(sharedTimeoutRow)

	servoInitialAngles.forEach((initialAngle, servoId) => {
		const row = document.createElement("div")
		row.style.display = "flex"
		row.style.alignItems = "center"
		row.style.gap = "8px"
		row.style.flexWrap = "wrap"

		const label = document.createElement("span")
		label.textContent = `Servo ${servoId + 1}`
		label.style.width = "80px"
		row.appendChild(label)

		const slider = document.createElement("input")
		slider.type = "range"
		slider.min = "0"
		slider.max = "180"
		slider.value = initialAngle.toString()
		slider.style.flexGrow = "1"
		row.appendChild(slider)

		const value = document.createElement("span")
		value.textContent = `${initialAngle}\u00B0`
		value.style.width = "52px"
		row.appendChild(value)

		servoSliders[servoId] = slider
		servoValueLabels[servoId] = value

		slider.addEventListener("input", () => {
			const angle = Number(slider.value)
			sendServoAngle(servoId, angle)
		})

		const centerButton = document.createElement("button")
		centerButton.textContent = "Center"
		centerButton.onclick = () => {
			centerServo(servoId)
		}
		row.appendChild(centerButton)

		const stopButton = document.createElement("button")
		stopButton.textContent = "Stop"
		stopButton.onclick = () => {
			stopAllMotors(servoId)
		}
		row.appendChild(stopButton)

		servoControls.appendChild(row)
	})

	container.root.appendChild(servoSection)

	const pulseOptions = [50, 100, 200, 400]
	let selectedPulseCount = pulseOptions[0]
	const pulseStepTimeMicros = 1000
	const basePulseSpeed = Math.abs(speed)

	const forwardSpeedForMotor = (motorId: number) =>
		motorId === driveLeft ? basePulseSpeed : -basePulseSpeed
	const backwardSpeedForMotor = (motorId: number) =>
		-forwardSpeedForMotor(motorId)

	const sendPulseDrive = (
		motorId: number,
		direction: "forward" | "backward",
	) => {
		const steps = selectedPulseCount
		if (!steps) return
		const motorSpeed =
			direction === "forward"
				? forwardSpeedForMotor(motorId)
				: backwardSpeedForMotor(motorId)
		ws.send({
			type: "drive",
			botId,
			motorId,
			speed: motorSpeed,
			steps,
			stepTimeMicros: pulseStepTimeMicros,
		})
	}

	const pulseSection = document.createElement("div")
	pulseSection.className = "card"
	pulseSection.style.display = "flex"
	pulseSection.style.flexDirection = "column"
	pulseSection.style.gap = "12px"

	const pulseTitle = document.createElement("h3")
	pulseTitle.innerText = "Pulse drive"
	pulseTitle.style.margin = "0"
	pulseSection.appendChild(pulseTitle)

	const pulseSummary = document.createElement("span")
	pulseSummary.textContent = `Selected pulses: ${selectedPulseCount}`
	pulseSummary.className = "info-text"
	pulseSection.appendChild(pulseSummary)

	const pulseButtonsRow = document.createElement("div")
	pulseButtonsRow.style.display = "flex"
	pulseButtonsRow.style.gap = "8px"
	pulseButtonsRow.style.flexWrap = "wrap"
	const pulseButtons: HTMLButtonElement[] = []

	const updatePulseButtons = () => {
		pulseSummary.textContent = `Selected pulses: ${selectedPulseCount}`
		pulseButtons.forEach((button, idx) => {
			const isSelected = pulseOptions[idx] === selectedPulseCount
			button.disabled = isSelected
			button.style.fontWeight = isSelected ? "bold" : "normal"
		})
	}

	pulseOptions.forEach((option) => {
		const button = document.createElement("button")
		button.textContent = `${option}`
		button.onclick = () => {
			selectedPulseCount = option
			updatePulseButtons()
		}
		pulseButtons.push(button)
		pulseButtonsRow.appendChild(button)
	})
	updatePulseButtons()
	pulseSection.appendChild(pulseButtonsRow)

	const pulseControls = document.createElement("div")
	pulseControls.style.display = "flex"
	pulseControls.style.flexDirection = "column"
	pulseControls.style.gap = "12px"

	const createPulseControlRow = (
		label: string,
		motorId: number,
	): HTMLDivElement => {
		const row = document.createElement("div")
		row.style.display = "flex"
		row.style.gap = "8px"
		row.style.alignItems = "center"

		const text = document.createElement("span")
		text.textContent = label
		text.style.width = "80px"
		row.appendChild(text)

		const forwardButton = document.createElement("button")
		forwardButton.textContent = "Forward"
		forwardButton.onclick = () => sendPulseDrive(motorId, "forward")
		row.appendChild(forwardButton)

		const backwardButton = document.createElement("button")
		backwardButton.textContent = "Backward"
		backwardButton.onclick = () => sendPulseDrive(motorId, "backward")
		row.appendChild(backwardButton)

		return row
	}

	pulseControls.appendChild(createPulseControlRow("Left motor", driveLeft))
	pulseControls.appendChild(createPulseControlRow("Right motor", driveRight))
	pulseSection.appendChild(pulseControls)

	container.root.appendChild(pulseSection)

	// stop only drive motors without recentering servo
	const stopDriveMotors = () => {
		ws.send({ type: "stopAllMotors", botId })
	}

	// stop drive motors and recenter servo
	const stopAllMotors = (servoId: number = steeringServoId) => {
		stopDriveMotors()
		centerServo(servoId)
	}

	let driveIntervals: { [key: string]: number } = {}

	window.onkeydown = (e) => {
		if (driveIntervals[e.key]) return
		if (e.key === "ArrowUp") {
			moveForward()
			driveIntervals[e.key] = window.setInterval(moveForward, 100)
		} else if (e.key === "ArrowDown") {
			moveBackward()
			driveIntervals[e.key] = window.setInterval(moveBackward, 100)
		} else if (e.key === "ArrowLeft") {
			turnLeft()
		} else if (e.key === "ArrowRight") {
			turnRight()
		}
	}

	window.onkeyup = (e) => {
		// on drive key release, stop drive but keep servo angle
		if (driveIntervals[e.key]) {
			clearInterval(driveIntervals[e.key])
			driveIntervals[e.key] = undefined as any
			stopDriveMotors()
		}
		// on steering key release, recenter servo
		if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
			centerSteering()
		}
	}

	const controller = new FourWheelController({
		onForward: () => moveForward(),
		onMoveLeft: () => turnLeft(),
		onMoveRight: () => turnRight(),
		onBackward: () => moveBackward(),
		onReleased: () => stopAllMotors(),
	})

	const controllerCard = document.createElement("div")
	controllerCard.className = "card"

	const controllerTitle = document.createElement("h3")
	controllerTitle.textContent = "Manual drive"
	controllerTitle.style.margin = "0"
	controllerCard.appendChild(controllerTitle)

	const controllerHint = document.createElement("p")
	controllerHint.className = "section-note"
	controllerHint.textContent =
		"Use the on-screen pad or arrow keys for quick driving experiments."
	controllerCard.appendChild(controllerHint)

	controllerCard.appendChild(controller.root)
	container.root.appendChild(controllerCard)
}
