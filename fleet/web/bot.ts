import type { MotorConfig, MsgToServer } from "../types"
import {
	TEMPLATE_OPTIONS,
	cloneTemplateMotors,
	describeTemplate,
	isConfigTemplateKey,
	type ConfigTemplateKey,
	type TemplateSelectionKey,
} from "../config-templates"
import { state } from "./state"
import type { BotConfigState } from "./state"
import { Container } from "./ui"
import { ws } from "./wsclient"

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

	const nameText = document.createElement("div")
	nameText.className = "info-text"
	nameText.textContent = "Name: -"
	statusCard.appendChild(nameText)

	const ipText = document.createElement("div")
	ipText.className = "info-text"
	ipText.textContent = "IP: -"
	statusCard.appendChild(ipText)

	state.bots.onChange((bots) => {
		const bot = bots.find((candidate) => candidate.id === botId)
		if (bot) {
			statusBadge.textContent = bot.connected
				? "Connected"
				: "Disconnected"
			statusBadge.classList.toggle("connected", bot.connected)
			firmwareText.textContent = `Firmware: ${bot.version || "-"}`
			variantText.textContent = `Variant: ${bot.variant || "-"}`
			nameText.textContent = `Name: ${bot.name || "-"}`
			ipText.textContent = `IP: ${bot.ip || "-"}`
		} else {
			statusBadge.textContent = "Disconnected"
			statusBadge.classList.remove("connected")
			firmwareText.textContent = "Firmware: -"
			variantText.textContent = "Variant: -"
			nameText.textContent = "Name: -"
			ipText.textContent = "IP: -"
		}
	})

	container.root.appendChild(statusCard)

	const smartbusCard = document.createElement("div")
	smartbusCard.className = "card"

	const smartbusTitle = document.createElement("h3")
	smartbusTitle.textContent = "Smartbus tools"
	smartbusTitle.style.margin = "0"
	smartbusCard.appendChild(smartbusTitle)

	const smartbusNote = document.createElement("p")
	smartbusNote.className = "section-note"
	smartbusNote.textContent =
		"Scan for connected smart servos and change a servo ID. For safety, only connect one servo when changing IDs."
	smartbusCard.appendChild(smartbusNote)

	let scanUartPort = 1
	let scanStartId = 1
	let scanEndId = 20

	const scanRow = document.createElement("div")
	scanRow.style.display = "flex"
	scanRow.style.gap = "8px"
	scanRow.style.flexWrap = "wrap"
	smartbusCard.appendChild(scanRow)

	const uartInput = document.createElement("input")
	uartInput.type = "number"
	uartInput.min = "0"
	uartInput.max = "3"
	uartInput.value = scanUartPort.toString()
	uartInput.style.width = "90px"
	uartInput.oninput = () => {
		const parsed = Number(uartInput.value)
		if (Number.isFinite(parsed))
			scanUartPort = Math.max(0, Math.min(255, parsed))
	}
	scanRow.appendChild(createFieldWrapper("UART", uartInput))

	const startInput = document.createElement("input")
	startInput.type = "number"
	startInput.min = "1"
	startInput.max = "253"
	startInput.value = scanStartId.toString()
	startInput.style.width = "90px"
	startInput.oninput = () => {
		const parsed = Number(startInput.value)
		if (Number.isFinite(parsed))
			scanStartId = Math.max(1, Math.min(253, parsed))
	}
	scanRow.appendChild(createFieldWrapper("Start ID", startInput))

	const endInput = document.createElement("input")
	endInput.type = "number"
	endInput.min = "1"
	endInput.max = "253"
	endInput.value = scanEndId.toString()
	endInput.style.width = "90px"
	endInput.oninput = () => {
		const parsed = Number(endInput.value)
		if (Number.isFinite(parsed))
			scanEndId = Math.max(1, Math.min(253, parsed))
	}
	scanRow.appendChild(createFieldWrapper("End ID", endInput))

	const scanButton = document.createElement("button")
	scanButton.textContent = "Scan IDs"
	scanButton.classList.add("secondary")
	scanButton.onclick = () => {
		ws.send({
			type: "smartbusScan",
			botId,
			uartPort: scanUartPort,
			startId: scanStartId,
			endId: scanEndId,
		} as MsgToServer)
	}
	scanRow.appendChild(scanButton)

	const scanResult = document.createElement("div")
	scanResult.className = "section-note"
	scanResult.textContent = "Found IDs: -"
	smartbusCard.appendChild(scanResult)

	const updateScanResult = () => {
		const entry = state.smartbusScan.get()[botId]
		if (!entry) return
		const ids = entry.foundIds ?? []
		scanResult.textContent = `Found IDs (uart ${entry.uartPort}, ${entry.startId}..${entry.endId}): ${
			ids.length ? ids.join(", ") : "<none>"
		}`
	}
	state.smartbusScan.onChange(updateScanResult)
	updateScanResult()

	let setUartPort = 1
	let setOldId = 1
	let setNewId = 2

	const setRow = document.createElement("div")
	setRow.style.display = "flex"
	setRow.style.gap = "8px"
	setRow.style.flexWrap = "wrap"
	setRow.style.marginTop = "8px"
	smartbusCard.appendChild(setRow)

	const setUartInput = document.createElement("input")
	setUartInput.type = "number"
	setUartInput.min = "0"
	setUartInput.max = "3"
	setUartInput.value = setUartPort.toString()
	setUartInput.style.width = "90px"
	setUartInput.oninput = () => {
		const parsed = Number(setUartInput.value)
		if (Number.isFinite(parsed))
			setUartPort = Math.max(0, Math.min(255, parsed))
	}
	setRow.appendChild(createFieldWrapper("UART", setUartInput))

	const oldIdInput = document.createElement("input")
	oldIdInput.type = "number"
	oldIdInput.min = "1"
	oldIdInput.max = "253"
	oldIdInput.value = setOldId.toString()
	oldIdInput.style.width = "90px"
	oldIdInput.oninput = () => {
		const parsed = Number(oldIdInput.value)
		if (Number.isFinite(parsed))
			setOldId = Math.max(1, Math.min(253, parsed))
	}
	setRow.appendChild(createFieldWrapper("Old ID", oldIdInput))

	const newIdInput = document.createElement("input")
	newIdInput.type = "number"
	newIdInput.min = "1"
	newIdInput.max = "253"
	newIdInput.value = setNewId.toString()
	newIdInput.style.width = "90px"
	newIdInput.oninput = () => {
		const parsed = Number(newIdInput.value)
		if (Number.isFinite(parsed))
			setNewId = Math.max(1, Math.min(253, parsed))
	}
	setRow.appendChild(createFieldWrapper("New ID", newIdInput))

	const setButton = document.createElement("button")
	setButton.textContent = "Set ID"
	setButton.classList.add("secondary")
	setButton.onclick = () => {
		ws.send({
			type: "smartbusSetId",
			botId,
			uartPort: setUartPort,
			oldId: setOldId,
			newId: setNewId,
		} as MsgToServer)
	}
	setRow.appendChild(setButton)

	const setResult = document.createElement("div")
	setResult.className = "section-note"
	setResult.textContent = "Set ID result: -"
	smartbusCard.appendChild(setResult)

	const updateSetResult = () => {
		const entry = state.smartbusSetId.get()[botId]
		if (!entry) return
		setResult.textContent = `Set ID uart ${entry.uartPort}: ${entry.oldId} -> ${entry.newId} (status=${entry.status})`
	}
	state.smartbusSetId.onChange(updateSetResult)
	updateSetResult()

	container.root.appendChild(smartbusCard)

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

	function createFieldWrapper<T extends HTMLInputElement | HTMLSelectElement>(
		label: string,
		input: T,
	): HTMLLabelElement {
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
	const defaultSteeringServoId = 0
	const defaultDriveLeftMotorId = 1
	const defaultDriveRightMotorId = 2

	let steeringServoId = defaultSteeringServoId
	let driveLeft = defaultDriveLeftMotorId
	let driveRight = defaultDriveRightMotorId

	const normalizeName = (value?: string | null) =>
		(value ?? "").trim().toLowerCase()

	const updateDriveMappings = () => {
		const findMotorIdByName = (name: string) =>
			motors.find(
				(motor) => normalizeName(motor.name) === normalizeName(name),
			)?.nodeId

		const steeringCandidate =
			findMotorIdByName("steering_servo") ??
			motors.find(
				(motor) => motor.type === "angle" || motor.type === "smart",
			)?.nodeId
		steeringServoId = Number.isFinite(steeringCandidate)
			? (steeringCandidate as number)
			: defaultSteeringServoId

		const hbridgeMotors = motors.filter((motor) => motor.type === "hbridge")

		const leftCandidate =
			findMotorIdByName("drive_left") ?? hbridgeMotors[0]?.nodeId
		driveLeft = Number.isFinite(leftCandidate)
			? (leftCandidate as number)
			: defaultDriveLeftMotorId

		const rightCandidate =
			findMotorIdByName("drive_right") ??
			hbridgeMotors.find((motor) => motor.nodeId !== driveLeft)?.nodeId ??
			hbridgeMotors[1]?.nodeId
		driveRight = Number.isFinite(rightCandidate)
			? (rightCandidate as number)
			: defaultDriveRightMotorId
	}

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

	const ensureSmartConfig = (config: MotorConfig): void => {
		if (!config.smart) {
			config.smart = {
				uartPort: 1,
				txPin: 17,
				rxPin: 16,
				baudRate: 1_000_000,
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

		if (motor.pollStatus) {
			sanitized.pollStatus = true
		}

		if (motor.type !== "smart" && motor.pwm) {
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

		if (motor.type === "hbridge" && motor.hbridge) {
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

		if (motor.type === "smart" && motor.smart) {
			const { uartPort, txPin, rxPin, baudRate } = motor.smart
			if (
				[uartPort, txPin, rxPin].every(
					(value) => value !== undefined && Number.isFinite(value),
				)
			) {
				sanitized.smart = {
					uartPort: Math.max(0, Math.round(uartPort)),
					txPin: Math.round(txPin),
					rxPin: Math.round(rxPin),
				}
				const baud = toInt(baudRate)
				if (baud !== undefined) {
					sanitized.smart.baudRate = Math.max(1, baud)
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

		if (motor.type === "smart") {
			ensureSmartConfig(motor)
		}

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

		if (motor.type === "smart") {
			const pollInput = document.createElement("input")
			pollInput.type = "checkbox"
			pollInput.checked = !!motor.pollStatus
			pollInput.addEventListener("change", () => {
				motor.pollStatus = pollInput.checked ? true : undefined
			})
			grid.appendChild(createFieldWrapper("Poll status", pollInput))
		}

		const typeSelect = document.createElement("select")
		;[
			{ value: "angle", label: "Angle (servo)" },
			{ value: "smart", label: "Serial bus servo" },
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
			if (motor.type === "smart") {
				ensureSmartConfig(motor)
			} else {
				delete motor.smart
			}
			renderMotors()
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

		if (motor.type === "smart") {
			ensureSmartConfig(motor)
			const smartGrid = document.createElement("div")
			smartGrid.className = "motor-grid"
			card.appendChild(smartGrid)

			const uartPortInput = document.createElement("input")
			uartPortInput.type = "number"
			uartPortInput.min = "0"
			uartPortInput.value = motor.smart?.uartPort.toString() ?? "1"
			uartPortInput.addEventListener("input", () => {
				const parsed = parseInteger(uartPortInput.value)
				if (parsed !== undefined) {
					ensureSmartConfig(motor)
					motor.smart!.uartPort = Math.max(0, parsed)
				}
			})
			smartGrid.appendChild(
				createFieldWrapper("UART port", uartPortInput),
			)

			const txPinInput = document.createElement("input")
			txPinInput.type = "number"
			txPinInput.value = motor.smart?.txPin.toString() ?? "17"
			txPinInput.addEventListener("input", () => {
				const parsed = parseInteger(txPinInput.value)
				if (parsed !== undefined) {
					ensureSmartConfig(motor)
					motor.smart!.txPin = parsed
				}
			})
			smartGrid.appendChild(createFieldWrapper("TX pin", txPinInput))

			const rxPinInput = document.createElement("input")
			rxPinInput.type = "number"
			rxPinInput.value = motor.smart?.rxPin.toString() ?? "16"
			rxPinInput.addEventListener("input", () => {
				const parsed = parseInteger(rxPinInput.value)
				if (parsed !== undefined) {
					ensureSmartConfig(motor)
					motor.smart!.rxPin = parsed
				}
			})
			smartGrid.appendChild(createFieldWrapper("RX pin", rxPinInput))

			const baudInput = document.createElement("input")
			baudInput.type = "number"
			baudInput.min = "1"
			baudInput.value = motor.smart?.baudRate?.toString() ?? "1000000"
			baudInput.addEventListener("input", () => {
				const parsed = parseInteger(baudInput.value)
				if (parsed !== undefined) {
					ensureSmartConfig(motor)
					motor.smart!.baudRate = Math.max(1, parsed)
				}
			})
			smartGrid.appendChild(createFieldWrapper("Baud rate", baudInput))
		}

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

		if (motor.type === "angle" || motor.type === "smart") {
			const degMin =
				motor.analog?.degMin ?? (motor.type === "smart" ? 0 : 0)
			const degMax =
				motor.analog?.degMax ?? (motor.type === "smart" ? 240 : 180)
			const sliderMin = Math.floor(Math.min(degMin, degMax))
			const sliderMax = Math.ceil(Math.max(degMin, degMax))
			const centerDeg = Math.round((sliderMin + sliderMax) / 2)

			let durationMs = 0

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
			angleSlider.min = sliderMin.toString()
			angleSlider.max = sliderMax.toString()
			angleSlider.step = "1"
			angleSlider.value = centerDeg.toString()
			angleSlider.style.flexGrow = "1"
			angleControlRow.appendChild(angleSlider)

			const angleValue = document.createElement("span")
			angleValue.textContent = `${centerDeg}°`
			angleValue.style.width = "60px"
			angleValue.style.textAlign = "right"
			angleControlRow.appendChild(angleValue)

			const sendAngle = (angle: number) => {
				ws.send({
					type: "turnServo",
					botId,
					servoId: motor.nodeId,
					angle,
					durationMs: motor.type === "smart" ? durationMs : undefined,
				} as MsgToServer)
			}

			angleSlider.addEventListener("input", () => {
				const angle = Number(angleSlider.value)
				angleValue.textContent = `${angle}°`
				sendAngle(angle)
			})

			controlContainer.appendChild(angleControlRow)

			if (motor.type === "smart") {
				const busRow = document.createElement("div")
				busRow.style.display = "flex"
				busRow.style.alignItems = "center"
				busRow.style.gap = "8px"

				const busLabel = document.createElement("span")
				busLabel.textContent = "Bus"
				busLabel.style.width = "60px"
				busRow.appendChild(busLabel)

				const busValue = document.createElement("span")
				busValue.textContent = "-"
				busRow.appendChild(busValue)

				const updateBusValue = () => {
					const entry =
						state.motorStates.get()[botId]?.[motor.nodeId] ?? null
					if (!entry || !entry.valid || entry.positionDeg == null) {
						busValue.textContent = "No data"
						return
					}
					const mode = entry.wheelMode ? "wheel" : "pos"
					const deg = entry.positionDeg.toFixed(1)
					const raw =
						entry.positionRaw == null
							? "-"
							: entry.positionRaw.toString()
					busValue.textContent = `${deg}° (${mode}, raw=${raw})`
				}

				updateBusValue()
				state.motorStates.onChange(updateBusValue)
				controlContainer.appendChild(busRow)

				const durationRow = document.createElement("div")
				durationRow.style.display = "flex"
				durationRow.style.alignItems = "center"
				durationRow.style.gap = "8px"

				const durationLabel = document.createElement("span")
				durationLabel.textContent = "Move ms"
				durationLabel.style.width = "60px"
				durationRow.appendChild(durationLabel)

				const durationInput = document.createElement("input")
				durationInput.type = "number"
				durationInput.min = "0"
				durationInput.max = "65535"
				durationInput.value = "0"
				durationInput.style.width = "120px"
				durationInput.addEventListener("input", () => {
					const parsed = parseInteger(durationInput.value)
					durationMs =
						parsed === undefined
							? 0
							: Math.max(0, Math.min(65535, parsed))
				})
				durationRow.appendChild(durationInput)

				const durationHint = document.createElement("span")
				durationHint.textContent = "0 = max speed"
				durationHint.style.opacity = "0.8"
				durationRow.appendChild(durationHint)

				controlContainer.appendChild(durationRow)
			}

			const buttonRow = document.createElement("div")
			buttonRow.style.display = "flex"
			buttonRow.style.gap = "8px"

			const centerButton = document.createElement("button")
			centerButton.textContent = `Center (${centerDeg}°)`
			centerButton.classList.add("secondary")
			centerButton.onclick = () => {
				angleSlider.value = centerDeg.toString()
				angleValue.textContent = `${centerDeg}°`
				sendAngle(centerDeg)
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

			if (motor.type === "smart") {
				const speedControlRow = document.createElement("div")
				speedControlRow.style.display = "flex"
				speedControlRow.style.alignItems = "center"
				speedControlRow.style.gap = "8px"

				const speedLabel = document.createElement("span")
				speedLabel.textContent = "Wheel"
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
				speedValue.style.width = "60px"
				speedValue.style.textAlign = "right"
				speedControlRow.appendChild(speedValue)

				speedSlider.addEventListener("input", () => {
					const speed = Number(speedSlider.value)
					speedValue.textContent = `${speed}`
					ws.send({
						type: "drive",
						botId,
						motorId: motor.nodeId,
						motorType: "dc",
						speed,
					} as MsgToServer)
				})

				controlContainer.appendChild(speedControlRow)

				const wheelButtons = document.createElement("div")
				wheelButtons.style.display = "flex"
				wheelButtons.style.gap = "8px"

				const ccwButton = document.createElement("button")
				ccwButton.textContent = "CCW"
				ccwButton.classList.add("secondary")
				ccwButton.onclick = () => {
					speedSlider.value = "-50"
					speedValue.textContent = "-50"
					ws.send({
						type: "drive",
						botId,
						motorId: motor.nodeId,
						motorType: "dc",
						speed: -50,
					} as MsgToServer)
				}
				wheelButtons.appendChild(ccwButton)

				const wheelStop = document.createElement("button")
				wheelStop.textContent = "Stop wheel"
				wheelStop.classList.add("secondary")
				wheelStop.onclick = () => {
					speedSlider.value = "0"
					speedValue.textContent = "0"
					ws.send({
						type: "drive",
						botId,
						motorId: motor.nodeId,
						motorType: "dc",
						speed: 0,
					} as MsgToServer)
				}
				wheelButtons.appendChild(wheelStop)

				const cwButton = document.createElement("button")
				cwButton.textContent = "CW"
				cwButton.classList.add("secondary")
				cwButton.onclick = () => {
					speedSlider.value = "50"
					speedValue.textContent = "50"
					ws.send({
						type: "drive",
						botId,
						motorId: motor.nodeId,
						motorType: "dc",
						speed: 50,
					} as MsgToServer)
				}
				wheelButtons.appendChild(cwButton)

				controlContainer.appendChild(wheelButtons)
			}
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
		updateDriveMappings()
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
			if (motor.type === "smart") {
				const bus = motor.smart
				if (
					!bus ||
					![bus.txPin, bus.rxPin, bus.uartPort].every(
						(value) =>
							value !== undefined && Number.isFinite(value),
					)
				) {
					alert(
						`Complete smart servo bus fields before applying (motor ${idx + 1}).`,
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

	const roverCard = document.createElement("div")
	roverCard.className = "card"

	const roverTitle = document.createElement("h3")
	roverTitle.textContent = "Rover controls"
	roverTitle.style.margin = "0"
	roverCard.appendChild(roverTitle)

	const roverHint = document.createElement("p")
	roverHint.className = "section-note"
	roverHint.textContent =
		"Manual driving controls live on a separate page to avoid accidental key presses."
	roverCard.appendChild(roverHint)

	const roverLink = document.createElement("a")
	roverLink.href = `/bot/${botId}/rover`
	roverLink.textContent = "Open rover controls"
	roverCard.appendChild(roverLink)

	container.root.appendChild(roverCard)
}
