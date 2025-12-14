import type { MotorConfig, MsgToServer } from "../types"
import { state } from "./state"
import { UiComponent, type Container } from "./ui"
import { onRouteChange } from "./router"
import { ws } from "./wsclient"

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

const computeDriveMappings = (motors: MotorConfig[]) => {
	const defaultSteeringServoId = 0
	const defaultDriveLeftMotorId = 1
	const defaultDriveRightMotorId = 2

	const normalizeName = (value?: string | null) =>
		(value ?? "").trim().toLowerCase()

	const findMotorIdByName = (name: string) =>
		motors.find((motor) => normalizeName(motor.name) === normalizeName(name))
			?.nodeId

	const steeringCandidate =
		findMotorIdByName("steering_servo") ??
		motors.find((motor) => motor.type === "angle" || motor.type === "smart")
			?.nodeId
	const steeringServoId = Number.isFinite(steeringCandidate)
		? (steeringCandidate as number)
		: defaultSteeringServoId

	const hbridgeMotors = motors.filter((motor) => motor.type === "hbridge")

	const leftCandidate =
		findMotorIdByName("drive_left") ?? hbridgeMotors[0]?.nodeId
	const driveLeft = Number.isFinite(leftCandidate)
		? (leftCandidate as number)
		: defaultDriveLeftMotorId

	const rightCandidate =
		findMotorIdByName("drive_right") ??
		hbridgeMotors.find((motor) => motor.nodeId !== driveLeft)?.nodeId ??
		hbridgeMotors[1]?.nodeId
	const driveRight = Number.isFinite(rightCandidate)
		? (rightCandidate as number)
		: defaultDriveRightMotorId

	return { steeringServoId, driveLeft, driveRight }
}

export const roverPage = (container: Container, botId: string) => {
	if (!botId) {
		container.root.innerText = "No bot ID provided"
		return
	}

	container.clear()

	const headerCard = document.createElement("div")
	headerCard.className = "card status-card"

	const title = document.createElement("h2")
	title.textContent = `Rover controls`
	title.style.margin = "0"
	headerCard.appendChild(title)

	const statusBadge = document.createElement("span")
	statusBadge.className = "status-pill"
	statusBadge.textContent = "Disconnected"
	headerCard.appendChild(statusBadge)

	const botLink = document.createElement("a")
	botLink.href = `/bot/${botId}`
	botLink.textContent = `Back to bot ${botId}`
	headerCard.appendChild(botLink)

	container.root.appendChild(headerCard)

	const updateStatus = () => {
		const bot = state.bots.get().find((candidate) => candidate.id === botId)
		const connected = bot?.connected ?? false
		statusBadge.textContent = connected ? "Connected" : "Disconnected"
		statusBadge.classList.toggle("connected", connected)
	}
	state.bots.onChange(updateStatus)
	updateStatus()

	let motors: MotorConfig[] = []
	let steeringServoId = 0
	let driveLeft = 1
	let driveRight = 2

	const updateMotors = () => {
		motors = state.configs.get()[botId]?.motors ?? []
		const mappings = computeDriveMappings(motors)
		steeringServoId = mappings.steeringServoId
		driveLeft = mappings.driveLeft
		driveRight = mappings.driveRight
	}
	state.configs.onChange(updateMotors)
	updateMotors()

	// ensure wheels are centered on load
	const centerAngle = 88

	const speed = -80

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
		getMotorId: () => number,
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
		forwardButton.onclick = () => sendPulseDrive(getMotorId(), "forward")
		row.appendChild(forwardButton)

		const backwardButton = document.createElement("button")
		backwardButton.textContent = "Backward"
		backwardButton.onclick = () => sendPulseDrive(getMotorId(), "backward")
		row.appendChild(backwardButton)

		return row
	}

	pulseControls.appendChild(createPulseControlRow("Left motor", () => driveLeft))
	pulseControls.appendChild(
		createPulseControlRow("Right motor", () => driveRight),
	)
	pulseSection.appendChild(pulseControls)

	container.root.appendChild(pulseSection)

	const stopDriveMotors = () => {
		ws.send({ type: "stopAllMotors", botId })
	}

	const stopAllMotors = (servoId: number = steeringServoId) => {
		stopDriveMotors()
		centerServo(servoId)
	}

	let driveIntervals: { [key: string]: number } = {}

	const onKeyDown = (e: KeyboardEvent) => {
		if (driveIntervals[e.key]) return
		if (e.key === "ArrowUp") {
			e.preventDefault()
			moveForward()
			driveIntervals[e.key] = window.setInterval(moveForward, 100)
		} else if (e.key === "ArrowDown") {
			e.preventDefault()
			moveBackward()
			driveIntervals[e.key] = window.setInterval(moveBackward, 100)
		} else if (e.key === "ArrowLeft") {
			e.preventDefault()
			turnLeft()
		} else if (e.key === "ArrowRight") {
			e.preventDefault()
			turnRight()
		}
	}

	const onKeyUp = (e: KeyboardEvent) => {
		if (driveIntervals[e.key]) {
			e.preventDefault()
			clearInterval(driveIntervals[e.key])
			driveIntervals[e.key] = undefined as any
			stopDriveMotors()
		}
		if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
			e.preventDefault()
			centerSteering()
		}
	}

	window.addEventListener("keydown", onKeyDown)
	window.addEventListener("keyup", onKeyUp)

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

	const cleanup = () => {
		window.removeEventListener("keydown", onKeyDown)
		window.removeEventListener("keyup", onKeyUp)
		driveIntervals = {}
		stopAllMotors()
	}

	const unsubscribe = onRouteChange((info) => {
		if (!info.path.startsWith(`/bot/${botId}/rover`)) {
			cleanup()
			unsubscribe()
		}
	})
}
