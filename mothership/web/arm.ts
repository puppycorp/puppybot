import type { ArmJointConfig, MotorConfig, MsgToServer } from "../types"
import { state } from "./state"
import { onRouteChange } from "./router"
import type { Container } from "./ui"
import { ws } from "./wsclient"

const JOINT_NAMES = ["Yaw", "Shoulder", "Elbow", "Tip"]

const parseNumber = (value: string): number | null => {
	if (!value.trim()) return null
	const parsed = Number.parseFloat(value)
	return Number.isFinite(parsed) ? parsed : null
}

const parseInteger = (value: string): number | null => {
	const number = parseNumber(value)
	return number === null ? null : Math.round(number)
}

const wrapField = <
	T extends HTMLInputElement | HTMLSelectElement,
>(
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

const makeNumberInput = (
	value: string,
	step = "1",
	min?: string,
	max?: string,
) => {
	const input = document.createElement("input")
	input.type = "number"
	input.step = step
	input.value = value
	if (min !== undefined) input.min = min
	if (max !== undefined) input.max = max
	return input
}

const buildJointList = (motors: MotorConfig[]): ArmJointConfig[] => {
	const servoMotors = motors.filter(
		(motor) => motor.type === "angle" || motor.type === "smart",
	)
	return JOINT_NAMES.map((_, idx) => ({
		motorId: servoMotors[idx]?.nodeId ?? idx + 1,
		sign: 1,
		offsetDeg: 0,
	}))
}

export const armPage = (container: Container, botId: string) => {
	if (!botId) {
		container.root.innerText = "No bot ID provided"
		return
	}

	container.clear()

	const send = (msg: Record<string, unknown>) =>
		ws.send({ ...msg, botId } as MsgToServer)

	const headerCard = document.createElement("div")
	headerCard.className = "card status-card"
	const title = document.createElement("h2")
	title.textContent = "Arm controls"
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

	const armCard = document.createElement("div")
	armCard.className = "card"
	container.root.appendChild(armCard)

	const armTitle = document.createElement("h3")
	armTitle.textContent = "PuppyArm"
	armTitle.style.margin = "0"
	armCard.appendChild(armTitle)

	const commandRow = document.createElement("div")
	commandRow.className = "motor-grid"
	armCard.appendChild(commandRow)

	const speedInput = makeNumberInput("200", "1", "0", "1000")
	commandRow.appendChild(wrapField("Speed", speedInput))

	const statusLine = document.createElement("div")
	statusLine.className = "section-note"
	statusLine.textContent = "No ARM telemetry"
	armCard.appendChild(statusLine)

	const poseLine = document.createElement("div")
	poseLine.className = "section-note"
	poseLine.textContent = "XYZ: --"
	armCard.appendChild(poseLine)

	const buttonRow = document.createElement("div")
	buttonRow.className = "button-row"
	armCard.appendChild(buttonRow)

	const stopAllButton = document.createElement("button")
	stopAllButton.textContent = "Stop All"
	stopAllButton.addEventListener("click", () => send({ type: "armStopAll" }))
	buttonRow.appendChild(stopAllButton)

	const holdButton = document.createElement("button")
	holdButton.textContent = "Hold"
	holdButton.addEventListener("click", () =>
		send({ type: "armHold", speed: readSpeed() }),
	)
	buttonRow.appendChild(holdButton)

	const clearButton = document.createElement("button")
	clearButton.textContent = "Clear Faults"
	clearButton.addEventListener("click", () => send({ type: "armClearFaults" }))
	buttonRow.appendChild(clearButton)

	const jointTable = document.createElement("table")
	jointTable.className = "motor-table"
	jointTable.innerHTML =
		"<thead><tr><th>Joint</th><th>Status</th><th>Angle</th><th>Tick</th><th>Target</th><th>Speed</th><th>Jog</th><th>Target tick</th><th>Limits</th></tr></thead>"
	const jointBody = document.createElement("tbody")
	jointTable.appendChild(jointBody)
	armCard.appendChild(jointTable)

	const angleInputs = JOINT_NAMES.map(() => makeNumberInput("0", "0.1"))
	const tickInputs = JOINT_NAMES.map(() => makeNumberInput("0", "1"))
	const limitMinInputs = JOINT_NAMES.map(() => makeNumberInput("0", "1"))
	const limitMaxInputs = JOINT_NAMES.map(() => makeNumberInput("4095", "1"))
	const limitEnabledInputs = JOINT_NAMES.map(() => {
		const input = document.createElement("input")
		input.type = "checkbox"
		input.checked = true
		return input
	})

	const jointCells = JOINT_NAMES.map((name, joint) => {
		const row = document.createElement("tr")
		const nameCell = document.createElement("td")
		nameCell.textContent = name
		row.appendChild(nameCell)

		const statusCell = document.createElement("td")
		statusCell.textContent = "--"
		row.appendChild(statusCell)

		const angleCell = document.createElement("td")
		angleCell.textContent = "--"
		row.appendChild(angleCell)

		const tickCell = document.createElement("td")
		tickCell.textContent = "--"
		row.appendChild(tickCell)

		const targetCell = document.createElement("td")
		targetCell.textContent = "--"
		row.appendChild(targetCell)

		const speedCell = document.createElement("td")
		speedCell.textContent = "--"
		row.appendChild(speedCell)

		const jogCell = document.createElement("td")
		const minus = document.createElement("button")
		minus.textContent = "-"
		const stop = document.createElement("button")
		stop.textContent = "0"
		const plus = document.createElement("button")
		plus.textContent = "+"
		jogCell.append(minus, stop, plus)
		row.appendChild(jogCell)

		const targetTickCell = document.createElement("td")
		targetTickCell.appendChild(tickInputs[joint])
		const setTick = document.createElement("button")
		setTick.textContent = "Set"
		targetTickCell.appendChild(setTick)
		row.appendChild(targetTickCell)

		const limitsCell = document.createElement("td")
		limitsCell.append(
			limitMinInputs[joint],
			limitMaxInputs[joint],
			limitEnabledInputs[joint],
		)
		const applyLimits = document.createElement("button")
		applyLimits.textContent = "Apply"
		const clearJoint = document.createElement("button")
		clearJoint.textContent = "Clear"
		limitsCell.append(applyLimits, clearJoint)
		row.appendChild(limitsCell)

		const startJog = (direction: -1 | 1) =>
			send({ type: "armJog", joint, direction, speed: readSpeed() })
		const stopJog = () => send({ type: "armStopJoint", joint })

		for (const [button, direction] of [
			[minus, -1],
			[plus, 1],
		] as const) {
			button.addEventListener("pointerdown", (event) => {
				button.setPointerCapture(event.pointerId)
				startJog(direction)
			})
			button.addEventListener("pointerup", stopJog)
			button.addEventListener("pointercancel", stopJog)
			button.addEventListener("lostpointercapture", stopJog)
		}
		stop.addEventListener("click", stopJog)
		setTick.addEventListener("click", () => {
			const tick = parseInteger(tickInputs[joint].value)
			if (tick === null) return
			send({ type: "armSetJointTick", joint, tick, speed: readSpeed() })
		})
		applyLimits.addEventListener("click", () => {
			const min = parseInteger(limitMinInputs[joint].value)
			const max = parseInteger(limitMaxInputs[joint].value)
			if (min === null || max === null) return
			send({ type: "armSetTickLimits", joint, min, max })
			send({
				type: "armSetTickLimitsEnabled",
				joint,
				enabled: limitEnabledInputs[joint].checked,
			})
		})
		limitEnabledInputs[joint].addEventListener("change", () =>
			send({
				type: "armSetTickLimitsEnabled",
				joint,
				enabled: limitEnabledInputs[joint].checked,
			}),
		)
		clearJoint.addEventListener("click", () =>
			send({ type: "armClearFaults", joint }),
		)

		jointBody.appendChild(row)
		return { statusCell, angleCell, tickCell, targetCell, speedCell }
	})

	const targetCard = document.createElement("div")
	targetCard.className = "card"
	container.root.appendChild(targetCard)

	const targetTitle = document.createElement("h3")
	targetTitle.textContent = "Targets"
	targetTitle.style.margin = "0"
	targetCard.appendChild(targetTitle)

	const targetGrid = document.createElement("div")
	targetGrid.className = "motor-grid"
	targetCard.appendChild(targetGrid)

	const xInput = makeNumberInput("200", "0.1")
	const yInput = makeNumberInput("0", "0.1")
	const zInput = makeNumberInput("0", "0.1")
	targetGrid.appendChild(wrapField("X", xInput))
	targetGrid.appendChild(wrapField("Y", yInput))
	targetGrid.appendChild(wrapField("Z", zInput))

	const gotoCoordsButton = document.createElement("button")
	gotoCoordsButton.textContent = "Go to XYZ"
	gotoCoordsButton.addEventListener("click", () => {
		const x = parseNumber(xInput.value)
		const y = parseNumber(yInput.value)
		const z = parseNumber(zInput.value)
		if (x === null || y === null || z === null) return
		send({ type: "armGotoCoords", x, y, z, speed: readSpeed() })
	})
	targetGrid.appendChild(gotoCoordsButton)

	const gotoAnglesButton = document.createElement("button")
	gotoAnglesButton.textContent = "Go to Angles"
	gotoAnglesButton.addEventListener("click", () => {
		const angles = angleInputs.map((input) => parseNumber(input.value))
		if (angles.some((value) => value === null)) return
		send({
			type: "armGotoAngles",
			anglesDeg: angles as [number, number, number, number],
			speed: readSpeed(),
		})
	})
	targetGrid.appendChild(gotoAnglesButton)

	const gotoTicksButton = document.createElement("button")
	gotoTicksButton.textContent = "Go to Ticks"
	gotoTicksButton.addEventListener("click", () => {
		const ticks = tickInputs.map((input) => parseInteger(input.value))
		if (ticks.some((value) => value === null)) return
		send({
			type: "armGotoTicks",
			ticks: ticks as [number, number, number, number],
			speed: readSpeed(),
		})
	})
	targetGrid.appendChild(gotoTicksButton)

	angleInputs.forEach((input, idx) =>
		targetGrid.appendChild(wrapField(`${JOINT_NAMES[idx]} deg`, input)),
	)

	const relativeGrid = document.createElement("div")
	relativeGrid.className = "motor-grid"
	targetCard.appendChild(relativeGrid)
	const stepInput = makeNumberInput("10", "0.1")
	relativeGrid.appendChild(wrapField("XY step", stepInput))
	const moveRelative = (dx: number, dy: number) =>
		send({ type: "armMoveRelative", dx, dy, speed: readSpeed() })
	for (const [label, dx, dy] of [
		["-X", -1, 0],
		["+X", 1, 0],
		["-Y", 0, -1],
		["+Y", 0, 1],
	] as const) {
		const button = document.createElement("button")
		button.textContent = label
		button.addEventListener("click", () => {
			const step = parseNumber(stepInput.value) ?? 0
			moveRelative(dx * step, dy * step)
		})
		relativeGrid.appendChild(button)
	}

	const legacyCard = document.createElement("div")
	legacyCard.className = "card"
	container.root.appendChild(legacyCard)
	const legacyTitle = document.createElement("h3")
	legacyTitle.textContent = "Legacy IK"
	legacyTitle.style.margin = "0"
	legacyCard.appendChild(legacyTitle)
	const legacyGrid = document.createElement("div")
	legacyGrid.className = "motor-grid"
	legacyCard.appendChild(legacyGrid)
	const legacyX = makeNumberInput("0", "0.001")
	const legacyY = makeNumberInput("0", "0.001")
	const legacyZ = makeNumberInput("0", "0.001")
	const legacyDuration = makeNumberInput("0", "1", "0")
	const elbowSelect = document.createElement("select")
	for (const option of [
		{ label: "Elbow down", value: "down" },
		{ label: "Elbow up", value: "up" },
	]) {
		const opt = document.createElement("option")
		opt.value = option.value
		opt.textContent = option.label
		elbowSelect.appendChild(opt)
	}
	legacyGrid.appendChild(wrapField("X", legacyX))
	legacyGrid.appendChild(wrapField("Y", legacyY))
	legacyGrid.appendChild(wrapField("Z", legacyZ))
	legacyGrid.appendChild(wrapField("Pose", elbowSelect))
	legacyGrid.appendChild(wrapField("Duration", legacyDuration))
	const legacyMove = document.createElement("button")
	legacyMove.textContent = "Move legacy"
	legacyMove.addEventListener("click", () => {
		const x = parseNumber(legacyX.value)
		const y = parseNumber(legacyY.value)
		const z = parseNumber(legacyZ.value)
		if (x === null || y === null || z === null) return
		const durationMs = parseInteger(legacyDuration.value)
		send({
			type: "armMove",
			x,
			y,
			z,
			elbowUp: elbowSelect.value === "up",
			durationMs: durationMs ?? undefined,
		})
	})
	legacyGrid.appendChild(legacyMove)

	const readSpeed = () => {
		const parsed = parseInteger(speedInput.value)
		if (parsed === null) return 0
		return Math.max(0, Math.min(1000, parsed))
	}

	let seededFromTelemetry = false
	const updateStatus = () => {
		const bot = state.bots.get().find((candidate) => candidate.id === botId)
		const connected = bot?.connected ?? false
		statusBadge.textContent = connected ? "Connected" : "Disconnected"
		statusBadge.classList.toggle("connected", connected)
	}
	state.bots.onChange(updateStatus)
	updateStatus()

	const updateTelemetry = () => {
		const arm = state.armStates.get()[botId]
		if (!arm) {
			statusLine.textContent = "No ARM telemetry"
			return
		}
		statusLine.textContent = `${arm.joints.length} joints`
		poseLine.textContent = arm.coordsMm
			? `XYZ: ${arm.coordsMm.x.toFixed(1)}, ${arm.coordsMm.y.toFixed(1)}, ${arm.coordsMm.z.toFixed(1)} mm`
			: "XYZ: --"
		arm.joints.forEach((joint, idx) => {
			if (!jointCells[idx]) return
			const fault = joint.fault ? ` ${joint.fault}` : ""
			jointCells[idx].statusCell.textContent = joint.online
				? joint.hasFeedback
					? `online${fault}`
					: `no feedback${fault}`
				: `offline${fault}`
			jointCells[idx].angleCell.textContent =
				joint.angleDeg === null ? "--" : joint.angleDeg.toFixed(1)
			jointCells[idx].tickCell.textContent = joint.hasFeedback
				? `${joint.tick}`
				: "--"
			jointCells[idx].targetCell.textContent =
				joint.targetTick === null ? "--" : `${joint.targetTick}`
			jointCells[idx].speedCell.textContent = `${joint.speed}`
			limitMinInputs[idx].value = `${joint.limitMin}`
			limitMaxInputs[idx].value = `${joint.limitMax}`
			if (!seededFromTelemetry) {
				tickInputs[idx].value = `${joint.tick}`
				if (joint.angleDeg !== null)
					angleInputs[idx].value = joint.angleDeg.toFixed(1)
			}
		})
		if (!seededFromTelemetry && arm.coordsMm) {
			xInput.value = arm.coordsMm.x.toFixed(1)
			yInput.value = arm.coordsMm.y.toFixed(1)
			zInput.value = arm.coordsMm.z.toFixed(1)
		}
		seededFromTelemetry = true
	}
	state.armStates.onChange(updateTelemetry)
	updateTelemetry()

	const refreshConfig = () => {
		const config = state.configs.get()[botId]
		const joints = buildJointList(config?.motors ?? [])
		if (!seededFromTelemetry) {
			joints.forEach((joint, idx) => {
				tickInputs[idx].placeholder = `${joint.motorId}`
			})
		}
	}
	state.configs.onChange(refreshConfig)
	refreshConfig()

	const unsubscribe = onRouteChange((info) => {
		if (!info.path.startsWith(`/bot/${botId}/arm`)) {
			unsubscribe()
		}
	})
}
