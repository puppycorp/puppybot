import type { MsgToUi, MsgToServer } from "./types";

let wsclient: WebSocket | null = null

const handleMsg = (msg: MsgToUi) => {
	switch (msg.type) {
		case "botConnected":
			console.log("Bot connected:", msg.botId)
			break
		case "botDisconnected":
			console.log("Bot disconnected:", msg.botId)
			break
		default:
			console.error("Unknown message type:", msg)
	}
}

const createClient = () => {
	wsclient = new WebSocket("ws://localhost:7775/api/bot/1/ws")

	wsclient.onopen = () => {
		console.log("WebSocket connection opened")
	}

	wsclient.onmessage = (event) => {
		const msg = JSON.parse(event.data) as MsgToUi
		console.log("Message received:", msg)
		handleMsg(msg)
	}

	wsclient.onclose = () => {
		console.log("WebSocket connection closed")
		createClient()
	}
}
createClient()

export const ws = {
	send: (msg: MsgToServer): boolean => {
		if (!wsclient) return false
		if (wsclient.readyState === WebSocket.CONNECTING) {
			console.error("WebSocket is still connecting. Message not sent.")
			return false
		}
		wsclient.send(JSON.stringify(msg))
		return true
	}
}