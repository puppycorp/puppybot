import type { Bot } from "../server/types"

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
}
