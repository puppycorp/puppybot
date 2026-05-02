import type { ArmConfig, ArmJointConfig, MotorConfig, MsgToServer } from "../types"
import { state } from "./state"
import { onRouteChange } from "./router"
import type { Container } from "./ui"
import { ws } from "./wsclient"

const buildJointList = (
	arm: ArmConfig,
	motors: MotorConfig[],
): ArmJointConfig[] => {
	const count = Math.max(1, Math.min(3, Math.round(arm.jointCount || 0)))
	const joints = arm.joints ?? []
	const servoMotors = motors.filter(
		(motor) => motor.type === "angle" || motor.type === "smart",
	)
	const list: ArmJointConfig[] = []
	for (let i = 0; i < count; i++) {
		list.push({
			motorId: joints[i]?.motorId ?? servoMotors[i]?.nodeId ?? i + 1,
			sign: joints[i]?.sign === -1 ? -1 : 1,
			offsetDeg: joints[i]?.offsetDeg ?? 0,
		})
	}
	return list
}

export const armPage = (container: Container, botId: string) => {
	if (!botId) {
		container.root.innerText = "No bot ID provided"
		return
	}

	container.clear()

	const headerCard = document.createElement("div")
	headerCard.className = "card status-card"

	const title = document.createElement("h2")
	title.textContent = `Arm controls`
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

	const geometryCard = document.createElement("div")
	geometryCard.className = "card"
	container.root.appendChild(geometryCard)

	const geometryTitle = document.createElement("h3")
	geometryTitle.textContent = "Arm geometry"
	geometryTitle.style.margin = "0"
	geometryCard.appendChild(geometryTitle)

	const geometryNote = document.createElement("p")
	geometryNote.className = "section-note"
	geometryCard.appendChild(geometryNote)

	const jointSummary = document.createElement("div")
	jointSummary.className = "section-note"
	geometryCard.appendChild(jointSummary)

	const controlCard = document.createElement("div")
	controlCard.className = "card"
	container.root.appendChild(controlCard)

	const controlTitle = document.createElement("h3")
	controlTitle.textContent = "Coordinate target"
	controlTitle.style.margin = "0"
	controlCard.appendChild(controlTitle)

	const controlHint = document.createElement("p")
	controlHint.className = "section-note"
	controlHint.textContent =
		"Enter target x/y/z in the same units as L1/L2/Z0."
	controlCard.appendChild(controlHint)

	const targetGrid = document.createElement("div")
	targetGrid.className = "motor-grid"
	controlCard.appendChild(targetGrid)

	const xInput = document.createElement("input")
	xInput.type = "number"
	xInput.step = "0.001"
	xInput.value = "0"
	targetGrid.appendChild(wrapField("X", xInput))

	const yInput = document.createElement("input")
	yInput.type = "number"
	yInput.step = "0.001"
	yInput.value = "0"
	targetGrid.appendChild(wrapField("Y", yInput))

	const zInput = document.createElement("input")
	zInput.type = "number"
	zInput.step = "0.001"
	zInput.value = "0"
	targetGrid.appendChild(wrapField("Z", zInput))

	const elbowSelect = document.createElement("select")
	;[
		{ label: "Elbow down", value: "down" },
		{ label: "Elbow up", value: "up" },
	].forEach((option) => {
		const opt = document.createElement("option")
		opt.value = option.value
		opt.textContent = option.label
		elbowSelect.appendChild(opt)
	})
	targetGrid.appendChild(wrapField("Pose", elbowSelect))

	const durationInput = document.createElement("input")
	durationInput.type = "number"
	durationInput.min = "0"
	durationInput.placeholder = "Optional"
	targetGrid.appendChild(wrapField("Duration (ms)", durationInput))

	const output = document.createElement("div")
	output.className = "section-note"
	output.textContent = "IK runs on the bot."
	controlCard.appendChild(output)

	const moveButton = document.createElement("button")
	moveButton.textContent = "Move arm"
	controlCard.appendChild(moveButton)

	const parseNumber = (value: string): number | null => {
		if (!value.trim()) return null
		const parsed = Number.parseFloat(value)
		return Number.isNaN(parsed) ? null : parsed
	}

	const updateOutput = () => {
		if (!armConfig) {
			output.textContent = "Arm config not set."
			moveButton.disabled = true
			return
		}
		if (Math.round(armConfig.jointCount) !== 3) {
			output.textContent = "Only 3-joint IK is supported right now."
			moveButton.disabled = true
			return
		}
		const x = parseNumber(xInput.value)
		const y = parseNumber(yInput.value)
		const z = parseNumber(zInput.value)
		if (x === null || y === null || z === null) {
			output.textContent = "Enter x/y/z to send a move."
			moveButton.disabled = true
			return
		}
		output.textContent = "Ready to send IK move to bot."
		moveButton.disabled = false
	}

	let motors: MotorConfig[] = []
	let armConfig: ArmConfig | null = null
	let joints: ArmJointConfig[] = []

	const updateStatus = () => {
		const bot = state.bots.get().find((candidate) => candidate.id === botId)
		const connected = bot?.connected ?? false
		statusBadge.textContent = connected ? "Connected" : "Disconnected"
		statusBadge.classList.toggle("connected", connected)
	}
	state.bots.onChange(updateStatus)
	updateStatus()

	const refreshConfig = () => {
		const config = state.configs.get()[botId]
		motors = config?.motors ?? []
		armConfig = config?.arm ?? null
		if (!armConfig) {
			geometryNote.textContent =
				"Arm config not set. Configure it on the bot page."
			jointSummary.textContent = ""
			joints = []
		} else {
			joints = buildJointList(armConfig, motors)
			geometryNote.textContent = `L1=${armConfig.l1}, L2=${armConfig.l2}, Z0=${armConfig.z0}, joints=${armConfig.jointCount}`
			jointSummary.textContent = `Joint motors: ${joints
				.map(
					(joint, idx) =>
						`J${idx + 1}=${joint.motorId} (sign ${
							joint.sign === -1 ? "-1" : "+1"
						}, offset ${joint.offsetDeg ?? 0}°)`,
				)
				.join(", ")}`
		}
		updateOutput()
	}
	state.configs.onChange(refreshConfig)
	refreshConfig()

	const sendMove = () => {
		if (!armConfig) return
		if (Math.round(armConfig.jointCount) !== 3) return
		const x = parseNumber(xInput.value)
		const y = parseNumber(yInput.value)
		const z = parseNumber(zInput.value)
		if (x === null || y === null || z === null) return
		const elbowUp = elbowSelect.value === "up"
		const durationMs = parseNumber(durationInput.value)
		ws.send({
			type: "armMove",
			botId,
			x,
			y,
			z,
			elbowUp,
			durationMs: durationMs ?? undefined,
		} as MsgToServer)
	}

	;[xInput, yInput, zInput, elbowSelect, durationInput].forEach((input) => {
		input.addEventListener("input", updateOutput)
	})
	moveButton.addEventListener("click", sendMove)
	updateOutput()

	const unsubscribe = onRouteChange((info) => {
		if (!info.path.startsWith(`/bot/${botId}/arm`)) {
			unsubscribe()
		}
	})
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
