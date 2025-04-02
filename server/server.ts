
import type { ServerWebSocket } from "bun"
import index from "./index.html"
import type { MsgFromBot, MsgToBot, MsgToUi, MsgToServer } from "./types"
import { decodeBotMsg, encodeBotMsg } from "./bot-protocol"

class BotConnection {
	private ws: ServerWebSocket<Context>
	constructor(ws: ServerWebSocket<Context>) {
		this.ws = ws
	}

	public send(msg: MsgToBot) {
		const binaryMsg = encodeBotMsg(msg)
		this.ws.send(binaryMsg)
	}
}

class UiConnection {
	private ws: ServerWebSocket<Context>
	constructor(ws: ServerWebSocket<Context>) {
		this.ws = ws
	}

	public send(msg: MsgToUi) {
		const jsonMsg = JSON.stringify(msg)
		this.ws.send(jsonMsg)
	}
}

const handleUiMsg = async (ws: ServerWebSocket<Context>, msg: MsgToServer) => {
	switch (msg.type) {
		case "drive": {
			const conn = ws.data.botConnections.get(ws.data.botId)
			if (!conn) return
			conn.send(msg)
			break
		}
		case "stop": {
			const conn = ws.data.botConnections.get(ws.data.botId)
			if (!conn) return
			conn.send(msg)
			break
		}
	}
}

const handleBotMsg = async (ws: ServerWebSocket<Context>, msg: MsgFromBot) => {
	switch (msg.type) {
		case "myInfo": {
			for (const client of uiClients.values()) {
				client.send({
					type: "botInfo",
					botId: ws.data.botId,
					version: msg.version
				})
			}
			break
		}
	}
}

type Context = {
	clientType: "bot" | "ui"
	botId: string
	botConnections: Map<string, BotConnection>
}

const botConnections = new Map<string, BotConnection>()
const uiClients = new Map<ServerWebSocket<Context>, UiConnection>()

Bun.serve<Context, {}>({
	port: 7775,
	routes: {
		"/api/bots": () => {
			return new Response(JSON.stringify({ bots: [] }), {
				headers: { "Content-Type": "application/json" }
			})
		},
		"/api/bot/:id/ws": (req, server) => {
			const { id } = req.params as { id: string }
			if (!id) {
				return new Response("Bot ID is required", { status: 400 })
			}
			if (server.upgrade(req, {
				data: {
					clientType: "bot",
					botId: id,
					botConnections
				}
			})) {
				return
			}
			return new Response("Upgrade failed", { status: 500 })
		},
		"/api/ws": (req, server) => {
			if (server.upgrade(req, {
				data: {
					clientType: "web",
					botConnections
				}
			})) {
				return
			}
			return new Response("Upgrade failed", { status: 500 })
		},
		"/*": index
	},
	websocket: {
		open(ws) {
			console.log("WebSocket connection opened")
			ws.send("Hello from server")
			if (ws.data.clientType === "bot") {
				const conn = new BotConnection(ws)
				ws.data.botConnections.set(ws.data.botId, conn)
				for (const conn of uiClients.values()) {
					conn.send({
						type: "botConnected",
						botId: ws.data.botId
					})
				}
			}
			if (ws.data.clientType === "ui") {
				const conn = new UiConnection(ws)
				uiClients.set(ws, conn)
			}
		},
		close(ws) {
			console.log("WebSocket connection closed")
			if (ws.data.clientType === "bot") {
				ws.data.botConnections.delete(ws.data.botId)
			}
			if (ws.data.clientType === "ui") {
				uiClients.delete(ws)
			}
		},
		async message(ws, message) {
			if (ws.data.clientType === "ui") {
				const msg = JSON.parse(message.toString()) as MsgToServer
				await handleUiMsg(ws, msg)
			}

			if (ws.data.clientType === "bot") {
				const msg = decodeBotMsg(message as Buffer)
				await handleBotMsg(ws, msg)
			}

			const msg = JSON.parse(message.toString()) as MsgToServer
			await handleUiMsg(ws, msg)

			console.log("Message received:", message)
			// Handle the message here
			// For example, you can send a response back to the client
			ws.send("Message received")
		},
	},
	development: true
})