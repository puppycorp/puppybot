import type { Bot, MotorConfig, MotorStateEntry } from "../types"

export type BotConfigState = {
	motors: MotorConfig[]
	templateKey: string | null
}

export class NotifyValue<T> {
	private value: T
	private listeners: ((value: T) => void)[] = []

	constructor(value: T) {
		this.value = value
	}

	get() {
		return this.value
	}

	set(value: T) {
		this.value = value
		this.listeners.forEach((listener) => listener(value))
	}

	onChange(listener: (value: T) => void) {
		this.listeners.push(listener)
	}
}

export const state = {
	bots: new NotifyValue<Bot[]>([]),
	configs: new NotifyValue<Record<string, BotConfigState>>({}),
	motorStates: new NotifyValue<
		Record<string, Record<number, MotorStateEntry>>
	>({}),
	smartbusScan: new NotifyValue<
		Record<
			string,
			{
				uartPort: number
				startId: number
				endId: number
				foundIds: number[]
			}
		>
	>({}),
	smartbusSetId: new NotifyValue<
		Record<
			string,
			{
				uartPort: number
				oldId: number
				newId: number
				status: number
				atMs: number
			}
		>
	>({}),
}
