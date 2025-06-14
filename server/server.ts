
import type { ServerWebSocket } from "bun"
import index from "../web/index.html"
import type { MsgToBot, MsgToUi, MsgToServer } from "./types"
import { decodeBotMsg, encodeBotMsg, MsgFromBotType, type MsgFromBot } from "./bot-protocol"

class BotConnection {
	private ws: ServerWebSocket<Context>
	private pongTimeout: any
	private pingInterval: any
	constructor(ws: ServerWebSocket<Context>) {
		this.ws = ws
		this.handlePong()
		this.pingInterval = setInterval(() => {
			console.log("ping")
			this.send({ type: "ping" })
		}, 10_000)
	}

	public send(msg: MsgToBot) {
		console.log("send", msg)
		const binaryMsg = encodeBotMsg(msg)
		this.ws.send(binaryMsg)
	}

	public handlePong() {
		clearTimeout(this.pongTimeout)
		this.pongTimeout = setTimeout(() => {
			console.log("Ping timeout")
			this.close()
		}, 15_000)
	}

	public close() {
		clearTimeout(this.pongTimeout)
		clearInterval(this.pingInterval)
		this.ws.close()
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
	console.log("handleUiMsg", msg)
	switch (msg.type) {
		case "drive": {
			const conn = ws.data.botConnections.get(msg.botId)
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
                case "stopAllMotors": {
                        const conn = ws.data.botConnections.get(msg.botId)
                        if (!conn) return
                        conn.send(msg)
                        break
                }
                case "turnServo": {
                        const conn = ws.data.botConnections.get(msg.botId)
                        if (!conn) return
                        conn.send(msg)
                        break
                }
        }
}

const handleBotMsg = async (ws: ServerWebSocket<Context>, msg: MsgFromBot) => {
	ws.data.botConnections.get(ws.data.botId)?.handlePong()
	console.log("handleBotMsg", msg)
	switch (msg.type) {
		case MsgFromBotType.MyInfo: {
			for (const client of uiClients.values()) {
				client.send({
					type: "botInfo",
					botId: ws.data.botId,
					version: msg.version + ""
				})
			}
			break
		}
		case MsgFromBotType.Pong: break
		default:
			throw new Error("Unknown bot message type")
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
			console.log("new bot connection")
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
					clientType: "ui",
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
			console.log(`${ws.data.clientType} connection opened`)
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
			console.log(`${ws.data.clientType} connection closed`)
			if (ws.data.clientType === "bot") {
				ws.data.botConnections.delete(ws.data.botId)
			}
			if (ws.data.clientType === "ui") {
				uiClients.delete(ws)
			}
		},
		async message(ws, message) {
			try {
				if (ws.data.clientType === "ui") {
					const msg = JSON.parse(message.toString()) as MsgToServer
					await handleUiMsg(ws, msg)
				}

				if (ws.data.clientType === "bot") {
					console.log("received bot message", message)
					const msg = decodeBotMsg(message as Buffer)
					await handleBotMsg(ws, msg)
				}
			} catch (error) {
				console.log("Error handling message:", error)
			}
		},
	},
	development: true
})