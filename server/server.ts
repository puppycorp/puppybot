import type { ServerWebSocket } from "bun"
import index from "../web/index.html"
import type { MsgToBot, MsgToUi, MsgToServer, Bot } from "./types"
import {
	decodeBotMsg,
	encodeBotMsg,
	MsgFromBotType,
	type MsgFromBot,
} from "./bot-protocol"

class BotConnection {
	private ws: ServerWebSocket<Context>
	private pongTimeout: any
	private pingInterval: any
	constructor(ws: ServerWebSocket<Context>) {
		this.ws = ws
		this.handlePong()
		// Disable server-initiated binary ping; rely on device heartbeat
		// If needed later, prefer WebSocket control ping over app-level ping
	}

	public send(msg: MsgToBot) {
		console.log("send", msg)
		const binaryMsg = encodeBotMsg(msg)
		this.ws.send(binaryMsg)
	}

	public handlePong() {
		console.log("handlePong")
		clearTimeout(this.pongTimeout)
		this.pongTimeout = setTimeout(() => {
			console.log("Ping timeout")
			// this.close()
		}, 65_000) // allow >2x device heartbeat (30s)
	}

	public close() {
		console.log("BotConnection close")
		clearTimeout(this.pongTimeout)
		if (this.pingInterval) clearInterval(this.pingInterval)
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
			// Update known info for this bot
			connectedBots.set(ws.data.botId, {
				id: ws.data.botId,
				version: msg.version + "",
				connected: true,
			})
			logConnectionsTable()
			for (const client of uiClients.values()) {
				client.send({
					type: "botInfo",
					botId: ws.data.botId,
					version: msg.version + "",
				})
			}
			break
		}
		case MsgFromBotType.Pong:
			break
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
// Track currently connected bots and (optionally) latest known info
const connectedBots = new Map<string, Bot>()

const logConnectionsTable = () => {
	const bots = Array.from(connectedBots.values()).map((b) => ({
		id: b.id,
		state: b.connected ? "connected" : "disconnected",
		version: b.version || "-",
	}))
	console.log(`Connected bots: ${bots.length}`)
	console.log(`UI clients: ${uiClients.size}`)
}

Bun.serve<Context, {}>({
	port: 7775,
	routes: {
		"/api/bots": () => {
			const bots = Array.from(connectedBots.values())
			return new Response(JSON.stringify({ bots }), {
				headers: { "Content-Type": "application/json" },
			})
		},
		"/api/bot/:id/ws": (req, server) => {
			console.log("new bot connection")
			const { id } = req.params as { id: string }
			if (!id) {
				return new Response("Bot ID is required", { status: 400 })
			}
			if (
				server.upgrade(req, {
					data: {
						clientType: "bot",
						botId: id,
						botConnections,
					},
				})
			) {
				return
			}
			return new Response("Upgrade failed", { status: 500 })
		},
		"/api/ws": (req, server) => {
			if (
				server.upgrade(req, {
					data: {
						clientType: "ui",
						botConnections,
					},
				})
			) {
				return
			}
			return new Response("Upgrade failed", { status: 500 })
		},
		"/*": index,
	},
	websocket: {
		open(ws) {
			console.log(`${ws.data.clientType} connection opened`)
			if (ws.data.clientType === "bot") {
				// If a bot with this ID already exists, close the old connection first
				const existing = ws.data.botConnections.get(ws.data.botId)
				if (existing) {
					try {
						existing.close()
					} catch (e) {
						console.log("Error closing existing bot connection", e)
					}
				}
				const conn = new BotConnection(ws)
				ws.data.botConnections.set(ws.data.botId, conn)
				// Remember this bot as connected (version unknown until MyInfo)
				connectedBots.set(ws.data.botId, {
					id: ws.data.botId,
					version: "",
					connected: true,
				})
				logConnectionsTable()
				for (const conn of uiClients.values()) {
					conn.send({
						type: "botConnected",
						botId: ws.data.botId,
					})
				}
			}
			if (ws.data.clientType === "ui") {
				const conn = new UiConnection(ws)
				uiClients.set(ws, conn)
				logConnectionsTable()
				// Send current snapshot of connected bots to this UI client
				for (const bot of connectedBots.values()) {
					conn.send({ type: "botConnected", botId: bot.id })
					if (bot.version) {
						conn.send({
							type: "botInfo",
							botId: bot.id,
							version: bot.version,
						})
					}
				}
			}
		},
		close(ws) {
			console.log(`${ws.data.clientType} connection closed`)
			if (ws.data.clientType === "bot") {
				ws.data.botConnections.delete(ws.data.botId)
				connectedBots.delete(ws.data.botId)
				logConnectionsTable()
				for (const conn of uiClients.values()) {
					conn.send({
						type: "botDisconnected",
						botId: ws.data.botId,
					})
				}
			}
			if (ws.data.clientType === "ui") {
				uiClients.delete(ws)
				logConnectionsTable()
			}
		},
		async message(ws, message) {
			try {
				if (ws.data.clientType === "ui") {
					const msg = JSON.parse(message.toString()) as MsgToServer
					await handleUiMsg(ws, msg)
				}

				if (ws.data.clientType === "bot") {
					// Bots may send text heartbeats ("ping") or binary frames
					if (typeof message === "string") {
						console.log("received bot text message", message)
						if (message === "ping") {
							// Treat as liveness signal
							ws.data.botConnections
								.get(ws.data.botId)
								?.handlePong()
							ws.send("pong")
						}
						return
					}
					console.log("received bot message", message)
					const binary = Buffer.isBuffer(message)
						? (message as Buffer)
						: Buffer.from(message as Uint8Array)
					const msg = decodeBotMsg(binary)
					await handleBotMsg(ws, msg)
				}
			} catch (error) {
				console.log("Error handling message:", error)
			}
		},
	},
	development: true,
})
