import type { ServerWebSocket } from "bun"
import index from "../web/index.html"
import type { MsgToBot, MsgToUi, MsgToServer, Bot, MotorConfig } from "./types"
import {
	decodeBotMsg,
	encodeBotMsg,
	MsgFromBotType,
	type MsgFromBot,
} from "./bot-protocol"
import { buildMotorBlob } from "./pbcl"

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
		case "updateConfig": {
			const motors = msg.motors ?? []
			botConfigs.set(msg.botId, motors)
			const blob = buildMotorBlob(motors)
			const conn = ws.data.botConnections.get(msg.botId)
			if (conn) {
				conn.send({ type: "applyConfig", blob: new Uint8Array(blob) })
			}
			const broadcast: MsgToUi = {
				type: "config",
				botId: msg.botId,
				motors,
			}
			for (const client of uiClients.values()) {
				client.send(broadcast)
			}
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
				version: msg.firmwareVersion || "",
				variant: msg.variant || "",
				connected: true,
			})
			logConnectionsTable()
			for (const client of uiClients.values()) {
				client.send({
					type: "botInfo",
					botId: ws.data.botId,
					version: msg.firmwareVersion || "",
					variant: msg.variant || "",
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
const botConfigs = new Map<string, MotorConfig[]>()

const defaultConfig: MotorConfig[] = [
	{
		nodeId: 1,
		type: "hbridge",
		name: "drive_left",
		pwm: { pin: 33, channel: 0, freqHz: 1000, minUs: 1000, maxUs: 2000 },
		hbridge: { in1: 25, in2: 26, brakeMode: false },
	},
	{
		nodeId: 2,
		type: "hbridge",
		name: "drive_right",
		pwm: { pin: 32, channel: 1, freqHz: 1000, minUs: 1000, maxUs: 2000 },
		hbridge: { in1: 27, in2: 14, brakeMode: false },
	},
	{
		nodeId: 100,
		type: "angle",
		name: "servo_0",
		pwm: { pin: 13, channel: 2, freqHz: 50, minUs: 1000, maxUs: 2000 },
	},
	{
		nodeId: 101,
		type: "angle",
		name: "servo_1",
		pwm: { pin: 21, channel: 3, freqHz: 50, minUs: 1000, maxUs: 2000 },
	},
	{
		nodeId: 102,
		type: "angle",
		name: "servo_2",
		pwm: { pin: 22, channel: 4, freqHz: 50, minUs: 1000, maxUs: 2000 },
	},
	{
		nodeId: 103,
		type: "angle",
		name: "servo_3",
		pwm: { pin: 23, channel: 5, freqHz: 50, minUs: 1000, maxUs: 2000 },
	},
]

const cloneConfig = (motors: MotorConfig[]): MotorConfig[] =>
	motors.map((m) => ({
		...m,
		pwm: m.pwm ? { ...m.pwm } : undefined,
		hbridge: m.hbridge ? { ...m.hbridge } : undefined,
		analog: m.analog ? { ...m.analog } : undefined,
	}))

const logConnectionsTable = () => {
	const bots = Array.from(connectedBots.values()).map((b) => ({
		id: b.id,
		state: b.connected ? "connected" : "disconnected",
		version: b.version || "-",
		variant: b.variant || "-",
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
					variant: "",
					connected: true,
				})
				if (!botConfigs.has(ws.data.botId)) {
					botConfigs.set(ws.data.botId, cloneConfig(defaultConfig))
				}
				logConnectionsTable()
				for (const conn of uiClients.values()) {
					conn.send({
						type: "botConnected",
						botId: ws.data.botId,
					})
				}
				const motors = botConfigs.get(ws.data.botId) ?? []
				const configMsg: MsgToUi = {
					type: "config",
					botId: ws.data.botId,
					motors,
				}
				for (const ui of uiClients.values()) {
					ui.send(configMsg)
				}
				if (motors.length > 0) {
					const blob = buildMotorBlob(motors)
					ws.data.botConnections.get(ws.data.botId)?.send({
						type: "applyConfig",
						blob: new Uint8Array(blob),
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
					if (bot.version || bot.variant) {
						conn.send({
							type: "botInfo",
							botId: bot.id,
							version: bot.version,
							variant: bot.variant,
						})
					}
				}
				for (const [botId, motors] of botConfigs.entries()) {
					conn.send({ type: "config", botId, motors })
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

console.log("listening on http://localhost:7775")
