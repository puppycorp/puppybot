import { Container, UiComponent } from "./ui";
import { ws } from "./wsclient";

class MotorController extends UiComponent<HTMLDivElement> {
	constructor(args: {
		title?: string
		onForward?: (speed: number) => void
		onReleased?: () => void
		onBackward?: (speed: number) => void
	}) {
		super(document.createElement("div"))
		this.root.style.display = "flex"
		this.root.style.gap = "10px"

		const label = document.createElement("label")
		label.innerText = "Speed"
		this.root.appendChild(label)

		const speedInput = document.createElement("input")
		speedInput.type = "number"
		speedInput.value = "180"
		this.root.appendChild(speedInput)

		const forwardButton = document.createElement("button")
		forwardButton.innerText = "Forward"
		forwardButton.onmousedown = () => args.onForward?.(parseInt(speedInput.value))
		forwardButton.onmouseup = () => args.onReleased?.()
		this.root.appendChild(forwardButton)

		const backwardButton = document.createElement("button")
		backwardButton.innerText = "Backward"
		backwardButton.onmousedown = () => args.onBackward?.(parseInt(speedInput.value))
		backwardButton.onmouseup = () => args.onReleased?.()
		this.root.appendChild(backwardButton)
	}
}

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
		buttons.appendChild(forwardButton)

		const hbuttons = document.createElement("div")
		hbuttons.style.display = "flex"
		hbuttons.style.gap = "5px"
		hbuttons.style.flexDirection = "row"
		buttons.appendChild(hbuttons)

		const leftButton = document.createElement("button")
		leftButton.innerText = "Left"
		leftButton.style.flexGrow = "1"
		hbuttons.appendChild(leftButton)

		const rightButton = document.createElement("button")
		rightButton.innerText = "Right"
		rightButton.style.flexGrow = "1"
		hbuttons.appendChild(rightButton)

		const backwardButton = document.createElement("button")
		backwardButton.innerText = "Backward"
		buttons.appendChild(backwardButton)
	}
}

export const botPage = (container: Container) => {
	const motor1 = new MotorController({
		title: "Motor 1",
		onForward: (speed) => console.log(`Motor 1 moving forward at speed: ${speed}`),
		onReleased: () => console.log("Motor 1 released"),
		onBackward: (speed) => console.log(`Motor 1 moving backward at speed: ${speed}`)
	})
	const motor2 = new MotorController({
		title: "Motor 2",
		onForward: (speed) => console.log(`Motor 2 moving forward at speed: ${speed}`),
		onReleased: () => console.log("Motor 2 released"),
		onBackward: (speed) => console.log(`Motor 2 moving backward at speed: ${speed}`)
	})
	const motor3 = new MotorController({
		title: "Motor 3",
		onForward: (speed) => console.log(`Motor 3 moving forward at speed: ${speed}`),
		onReleased: () => console.log("Motor 3 released"),
		onBackward: (speed) => console.log(`Motor 3 moving backward at speed: ${speed}`)
	})
	const motor4 = new MotorController({
		title: "Motor 4",
		onForward: (speed) => console.log(`Motor 4 moving forward at speed: ${speed}`),
		onReleased: () => console.log("Motor 4 released"),
		onBackward: (speed) => console.log(`Motor 4 moving backward at speed: ${speed}`)
	})

	container.clear()
	container.add(motor1)
	container.add(motor2)
	container.add(motor3)
	container.add(motor4)

	const contoller = new FourWheelController({
		onForward: (speed) => ws.send({ type: "drive", speed: 180, direction: "forward" }),
		onMoveLeft: (speed) => console.log(`Moving left at speed: ${speed}`),
		onMoveRight: (speed) => console.log(`Moving right at speed: ${speed}`),
		onBackward: (speed) => console.log(`Moving backward at speed: ${speed}`),
		onReleased: () => console.log("Released")
	})
	container.add(contoller)
}