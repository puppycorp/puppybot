import { state } from "./state"
import { Container, UiComponent } from "./ui"
import { getQueryParam } from "./utility "
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

	const div = document.createElement("div")
	div.innerText = "Disconnected"
	div.style.color = "red"
	state.bots.onChange((bots) => {
		const bot = bots.find((bot) => bot.id === botId)
		if (bot) {
			div.innerText = "Connected"
			div.style.color = "green"
		} else {
			div.innerText = "Disconnected"
			div.style.color = "red"
		}
	})
	container.root.appendChild(div)

	// ensure wheels are centered on load
	ws.send({ type: "turnServo", botId, angle: 90 })

	const speed = 80

	const driveLeft = 1
	const driveRight = 2

	const centerAngle = 88
	const leftAngle = 50
	const rightAngle = 150

	const moveForward = () => {
		ws.send({ type: "drive", botId, motorId: driveLeft, speed: -speed })
		ws.send({ type: "drive", botId, motorId: driveRight, speed: speed })
	}

	const moveBackward = () => {
		ws.send({ type: "drive", botId, motorId: driveLeft, speed: speed })
		ws.send({ type: "drive", botId, motorId: driveRight, speed: -speed })
	}

	const turnLeft = () => {
		ws.send({ type: "turnServo", botId, angle: leftAngle })
	}

	const turnRight = () => {
		ws.send({ type: "turnServo", botId, angle: rightAngle })
	}

	const center = () => {
		ws.send({ type: "turnServo", botId, angle: centerAngle })
	}

	// stop only drive motors without recentering servo
	const stopDriveMotors = () => {
		ws.send({ type: "stopAllMotors", botId })
	}

	// stop drive motors and recenter servo
	const stopAllMotors = () => {
		stopDriveMotors()
		center()
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
			center()
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
