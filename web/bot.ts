import type { MsgToServer } from "../server/types"
import { state } from "./state"
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

	const statusDiv = document.createElement("div")
	statusDiv.innerText = "Disconnected"
	statusDiv.style.color = "red"

	const firmwareDiv = document.createElement("div")
	firmwareDiv.innerText = "Firmware: -"

	const variantDiv = document.createElement("div")
	variantDiv.innerText = "Variant: -"

	state.bots.onChange((bots) => {
		const bot = bots.find((bot) => bot.id === botId)
		if (bot) {
			statusDiv.innerText = bot.connected ? "Connected" : "Disconnected"
			statusDiv.style.color = bot.connected ? "green" : "red"
			firmwareDiv.innerText = `Firmware: ${bot.version || "-"}`
			variantDiv.innerText = `Variant: ${bot.variant || "-"}`
		} else {
			statusDiv.innerText = "Disconnected"
			statusDiv.style.color = "red"
			firmwareDiv.innerText = "Firmware: -"
			variantDiv.innerText = "Variant: -"
		}
	})

	container.root.appendChild(statusDiv)
	container.root.appendChild(firmwareDiv)
	container.root.appendChild(variantDiv)

	const configSection = document.createElement("div")
	configSection.style.display = "flex"
	configSection.style.flexDirection = "column"
	configSection.style.gap = "8px"
	configSection.style.margin = "16px 0"

	const configTitle = document.createElement("h3")
	configTitle.innerText = "Motor configuration"
	configTitle.style.margin = "0"
	configSection.appendChild(configTitle)

	const configHelp = document.createElement("p")
	configHelp.innerText =
		"Edit the PBCL motor config (JSON array) and apply to sync with the bot."
	configHelp.style.margin = "0"
	configHelp.style.opacity = "0.7"
	configHelp.style.fontSize = "12px"
	configSection.appendChild(configHelp)

	const configTextarea = document.createElement("textarea")
	configTextarea.style.width = "100%"
	configTextarea.style.minHeight = "160px"
	configTextarea.style.fontFamily = "monospace"
	configTextarea.style.fontSize = "12px"
	configTextarea.style.padding = "8px"
	configTextarea.style.boxSizing = "border-box"
	configSection.appendChild(configTextarea)

	const applyConfigButton = document.createElement("button")
	applyConfigButton.textContent = "Apply configuration"
	applyConfigButton.onclick = () => {
		try {
			const parsed = JSON.parse(configTextarea.value)
			if (!Array.isArray(parsed)) {
				throw new Error("Configuration must be an array of motors")
			}
			ws.send({
				type: "updateConfig",
				botId,
				motors: parsed,
			} as MsgToServer)
		} catch (err) {
			console.error("Failed to apply config", err)
			alert(`Invalid configuration: ${err}`)
		}
	}
	configSection.appendChild(applyConfigButton)

	state.configs.onChange((configs) => {
		const motors = configs[botId]
		if (motors) {
			configTextarea.value = JSON.stringify(motors, null, 2)
		}
	})
	const initialConfig = state.configs.get()[botId]
	if (initialConfig) {
		configTextarea.value = JSON.stringify(initialConfig, null, 2)
	} else {
		configTextarea.value = JSON.stringify([], null, 2)
	}

	container.root.appendChild(configSection)

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
	servoSection.style.display = "flex"
	servoSection.style.flexDirection = "column"
	servoSection.style.gap = "8px"
	servoSection.style.marginTop = "16px"

	const servoTitle = document.createElement("h3")
	servoTitle.innerText = "Servo controls"
	servoTitle.style.margin = "0"
	servoSection.appendChild(servoTitle)

	const servoControls = document.createElement("div")
	servoControls.style.display = "flex"
	servoControls.style.flexDirection = "column"
	servoControls.style.gap = "8px"
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
	pulseSection.style.display = "flex"
	pulseSection.style.flexDirection = "column"
	pulseSection.style.gap = "8px"
	pulseSection.style.marginTop = "16px"

	const pulseTitle = document.createElement("h3")
	pulseTitle.innerText = "Pulse drive"
	pulseTitle.style.margin = "0"
	pulseSection.appendChild(pulseTitle)

	const pulseSummary = document.createElement("span")
	pulseSummary.textContent = `Selected pulses: ${selectedPulseCount}`
	pulseSection.appendChild(pulseSummary)

	const pulseButtonsRow = document.createElement("div")
	pulseButtonsRow.style.display = "flex"
	pulseButtonsRow.style.gap = "8px"
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
	pulseControls.style.gap = "8px"

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

	const contoller = new FourWheelController({
		onForward: (speed) => moveForward(),
		onMoveLeft: (speed) => turnLeft(),
		onMoveRight: (speed) => turnRight(),
		onBackward: (speed) => moveBackward(),
		onReleased: () => stopAllMotors(),
	})
	container.add(contoller)
}
