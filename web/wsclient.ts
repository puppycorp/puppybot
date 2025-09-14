import { state } from "./state"
import type { MsgToUi, MsgToServer } from "../server/types"

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
						connected: true,
					},
				])
			}
			break
		case "botInfo":
			console.log("Bot info:", msg.botId, msg.version)
			state.bots.set(
				state.bots
					.get()
					.map((b) =>
						b.id === msg.botId ? { ...b, version: msg.version } : b,
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
