import { state } from "./state"
import type { MsgToUi, MsgToServer } from "../types"

let wsclient: WebSocket | null = null

const handleMsg = (msg: MsgToUi) => {
	switch (msg.type) {
		case "botConnected":
			console.log("Bot connected:", msg.botId)
			{
				const bots = state.bots.get()
				const idx = bots.findIndex((b) => b.id === msg.botId)
				if (idx >= 0) {
					const updated = bots.slice()
					updated[idx] = { ...updated[idx], connected: true }
					state.bots.set(updated)
					break
				}
				state.bots.set([
					...bots,
					{
						id: msg.botId,
						version: "",
						variant: "",
						connected: true,
					},
				])
			}
			break
		case "botInfo":
			console.log("Bot info:", msg.botId, msg.version, msg.variant)
			state.bots.set(
				state.bots.get().map((b) =>
					b.id === msg.botId
						? {
								...b,
								version: msg.version,
								variant: msg.variant,
							}
						: b,
				),
			)
			break
		case "botDisconnected":
			console.log("Bot disconnected:", msg.botId)
			state.bots.set(
				state.bots
					.get()
					.map((b) =>
						b.id === msg.botId ? { ...b, connected: false } : b,
					),
			)
			break
		case "config":
			console.log(
				"Config update:",
				msg.botId,
				msg.motors,
				msg.templateKey ?? null,
			)
			state.configs.set({
				...state.configs.get(),
				[msg.botId]: {
					motors: msg.motors,
					templateKey: msg.templateKey ?? null,
				},
			})
			break
		case "motorState": {
			const existing = state.motorStates.get()
			const botStates: Record<number, any> = {
				...(existing[msg.botId] ?? {}),
			}
			for (const entry of msg.motors ?? []) {
				botStates[entry.motorId] = entry
			}
			state.motorStates.set({ ...existing, [msg.botId]: botStates })
			break
		}
		case "smartbusScan": {
			state.smartbusScan.set({
				...state.smartbusScan.get(),
				[msg.botId]: {
					uartPort: msg.uartPort,
					startId: msg.startId,
					endId: msg.endId,
					foundIds: msg.foundIds ?? [],
				},
			})
			break
		}
		case "smartbusSetId": {
			state.smartbusSetId.set({
				...state.smartbusSetId.get(),
				[msg.botId]: {
					uartPort: msg.uartPort,
					oldId: msg.oldId,
					newId: msg.newId,
					status: msg.status,
					atMs: Date.now(),
				},
			})
			break
		}
		default:
			console.log("Unknown message type:", msg)
	}
}

const createClient = () => {
	wsclient = new WebSocket("ws://localhost:7775/api/ws")

	wsclient.onopen = () => {
		console.log("WebSocket connection opened")
	}

	wsclient.onmessage = (event) => {
		try {
			const msg = JSON.parse(event.data) as MsgToUi
			console.log("Message received:", msg)
			handleMsg(msg)
		} catch (e) {
			console.log(event.data)
			console.error("Error parsing message:", e)
		}
	}

	wsclient.onclose = () => {
		console.log("WebSocket connection closed")
		createClient()
	}
}
createClient()

export const ws = {
	send: (msg: MsgToServer): boolean => {
		if (!wsclient) {
			console.log("WebSocket client not initialized")
			return false
		}
		if (wsclient.readyState === WebSocket.CONNECTING) {
			console.error("WebSocket is still connecting. Message not sent.")
			return false
		}
		let strMsg = JSON.stringify(msg)
		console.log("Sending message:", strMsg)
		wsclient.send(strMsg)
		return true
	},
}
