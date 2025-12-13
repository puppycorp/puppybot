import type { ServerWebSocket } from "bun"
import index from "./web/index.html"
import type { MsgToBot, MsgToUi, MsgToServer, Bot, MotorConfig } from "./types"
import {
	decodeBotMsg,
	encodeBotMsg,
	MsgFromBotType,
	type MsgFromBot,
} from "./bot-protocol"
import {
	getAddresses,
	resolveInstance,
	watchInstances,
	type Instance,
	type InstanceWatcher,
} from "./mdns"
import { buildMotorBlob } from "./pbcl"
import { isConfigTemplateKey, type ConfigTemplateKey } from "./config-templates"

type BotSocket = {
	send(data: string | Uint8Array | ArrayBufferLike): void
	close(): void
}

class BotConnection {
	private socket: BotSocket
	private pongTimeout: ReturnType<typeof setTimeout> | null = null
	constructor(socket: BotSocket) {
		this.socket = socket
		this.handlePong()
		// Disable server-initiated binary ping; rely on device heartbeat
		// If needed later, prefer WebSocket control ping over app-level ping
	}

	public send(msg: MsgToBot) {
		console.log("send", msg)
		const binaryMsg = encodeBotMsg(msg)
		this.socket.send(binaryMsg)
	}

	public handlePong() {
		console.log("handlePong")
		if (this.pongTimeout) clearTimeout(this.pongTimeout)
		this.pongTimeout = setTimeout(() => {
			console.log("Ping timeout")
			// this.close()
		}, 65_000) // allow >2x device heartbeat (30s)
	}

	public close() {
		console.log("BotConnection close")
		if (this.pongTimeout) {
			clearTimeout(this.pongTimeout)
			this.pongTimeout = null
		}
		this.socket.close()
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

const handleUiMsg = async (_ws: ServerWebSocket<Context>, msg: MsgToServer) => {
	console.log("handleUiMsg", msg)
	switch (msg.type) {
		case "drive": {
			const conn = botConnections.get(msg.botId)
			if (!conn) return
			conn.send(msg)
			break
		}
		case "stop": {
			const conn = botConnections.get(msg.botId)
			if (!conn) return
			conn.send(msg)
			break
		}
		case "stopAllMotors": {
			const conn = botConnections.get(msg.botId)
			if (!conn) return
			conn.send(msg)
			break
		}
		case "turnServo": {
			const conn = botConnections.get(msg.botId)
			if (!conn) return
			conn.send(msg)
			break
		}
		case "updateConfig": {
			const motors = msg.motors ?? []
			const templateKey = parseTemplateKey(msg.templateKey)
			setBotConfig(msg.botId, motors, templateKey, "user")
			applyConfigToBot(msg.botId)
			broadcastConfig(msg.botId)
			break
		}
	}
}

const handleBotMsg = async (botId: string, msg: MsgFromBot) => {
	botConnections.get(botId)?.handlePong()
	console.log("handleBotMsg", msg)
	switch (msg.type) {
		case MsgFromBotType.MyInfo: {
			// Update known info for this bot
			connectedBots.set(botId, {
				id: botId,
				version: msg.firmwareVersion || "",
				variant: msg.variant || "",
				connected: true,
			})
			ensureBotConfig(botId)
			// Default to a fully custom, empty config on connect.
			// Users can apply templates manually from the UI.
			broadcastConfig(botId)
			logConnectionsTable()
			for (const client of uiClients.values()) {
				client.send({
					type: "botInfo",
					botId,
					version: msg.firmwareVersion || "",
					variant: msg.variant || "",
				})
			}
			break
		}
		case MsgFromBotType.MotorState: {
			const motors = msg.motors ?? []
			for (const client of uiClients.values()) {
				client.send({ type: "motorState", botId, motors })
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
	botId?: string
	botConnections: Map<string, BotConnection>
	connection?: BotConnection
}

const botConnections = new Map<string, BotConnection>()
const uiClients = new Map<ServerWebSocket<Context>, UiConnection>()
// Track currently connected bots and (optionally) latest known info
const connectedBots = new Map<string, Bot>()
const botConfigs = new Map<string, MotorConfig[]>()
const botConfigStates = new Map<
	string,
	{
		templateKey: ConfigTemplateKey | null
		source: "auto" | "user"
	}
>()

const createServerSocketAdapter = (
	ws: ServerWebSocket<Context>,
): BotSocket => ({
	send(data) {
		ws.send(data)
	},
	close() {
		try {
			ws.close()
		} catch (error) {
			console.log("Error closing server websocket:", error)
		}
	},
})

const createClientSocketAdapter = (ws: WebSocket): BotSocket => ({
	send(data) {
		ws.send(data)
	},
	close() {
		try {
			ws.close()
		} catch (error) {
			console.log("Error closing client websocket:", error)
		}
	},
})

const broadcastBotConnected = (botId: string) => {
	for (const client of uiClients.values()) {
		client.send({
			type: "botConnected",
			botId,
		})
	}
}

const broadcastBotDisconnected = (botId: string) => {
	for (const client of uiClients.values()) {
		client.send({
			type: "botDisconnected",
			botId,
		})
	}
}

const attachBotConnection = (botId: string, socket: BotSocket) => {
	const previous = connectedBots.get(botId)
	const existing = botConnections.get(botId)
	if (existing) {
		try {
			existing.close()
		} catch (error) {
			console.log("Error closing existing bot connection", error)
		}
	}
	const connection = new BotConnection(socket)
	botConnections.set(botId, connection)
	connectedBots.set(botId, {
		id: botId,
		version: previous?.version ?? "",
		variant: previous?.variant ?? "",
		connected: true,
	})
	ensureBotConfig(botId)
	logConnectionsTable()
	broadcastBotConnected(botId)
	broadcastConfig(botId)
	applyConfigToBot(botId)
	return connection
}

const detachBotConnection = (botId: string, expected?: BotConnection) => {
	const existing = botConnections.get(botId)
	if (!existing) return
	if (expected && existing !== expected) return
	botConnections.delete(botId)
	connectedBots.delete(botId)
	logConnectionsTable()
	broadcastBotDisconnected(botId)
}

const cloneConfig = (motors: MotorConfig[]): MotorConfig[] =>
	motors.map((m) => ({
		...m,
		pwm: m.pwm ? { ...m.pwm } : undefined,
		hbridge: m.hbridge ? { ...m.hbridge } : undefined,
		analog: m.analog ? { ...m.analog } : undefined,
	}))

const setBotConfig = (
	botId: string,
	motors: MotorConfig[],
	templateKey: ConfigTemplateKey | null,
	source: "auto" | "user",
) => {
	botConfigs.set(botId, cloneConfig(motors))
	botConfigStates.set(botId, { templateKey, source })
}

const buildConfigBroadcast = (botId: string): MsgToUi | null => {
	const motors = botConfigs.get(botId)
	if (!motors) return null
	const state = botConfigStates.get(botId)
	return {
		type: "config",
		botId,
		motors: cloneConfig(motors),
		templateKey: state?.templateKey ?? null,
	}
}

const broadcastConfig = (botId: string) => {
	const message = buildConfigBroadcast(botId)
	if (!message) return
	for (const client of uiClients.values()) {
		client.send(message)
	}
}

const applyConfigToBot = (botId: string) => {
	const motors = botConfigs.get(botId)
	if (!motors || motors.length === 0) return
	const blob = buildMotorBlob(motors)
	const conn = botConnections.get(botId)
	if (!conn) return
	conn.send({ type: "applyConfig", blob: new Uint8Array(blob) })
}

const ensureBotConfig = (botId: string) => {
	if (botConfigs.has(botId)) {
		return
	}
	setBotConfig(botId, [], null, "auto")
}

const parseTemplateKey = (
	value: string | null | undefined,
): ConfigTemplateKey | null => {
	if (!value) return null
	if (value === "custom") return null
	return isConfigTemplateKey(value) ? (value as ConfigTemplateKey) : null
}

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

const mdnsInstanceKey = (inst: Instance) => `${inst.name}@${inst.domain}`

const stripTrailingDot = (value: string | undefined): string => {
	if (!value) return ""
	return value.endsWith(".") ? value.slice(0, -1) : value
}

const sanitizeIdentifier = (value: string | undefined): string | undefined => {
	if (!value) return undefined
	const cleaned = value
		.trim()
		.replace(/\.local\.?$/i, "")
		.replace(/[^a-zA-Z0-9_-]+/g, "-")
		.replace(/-+/g, "-")
		.replace(/^-+|-+$/g, "")
	return cleaned || undefined
}

const normalizeHostCandidate = (value: string | undefined): string => {
	if (!value) return ""
	const trimmed = value.trim()
	if (!trimmed) return ""
	if (trimmed.includes(":")) return trimmed
	if (/^\d{1,3}(\.\d{1,3}){3}$/.test(trimmed)) return trimmed
	return stripTrailingDot(trimmed)
}

const chooseBestHost = (
	host: string,
	addrs: string[],
	fallbacks: string[] = [],
): string | null => {
	const ipv4 = addrs.find((addr) => addr.includes("."))
	if (ipv4) return ipv4
	const ipv6 = addrs.find((addr) => addr.includes(":"))
	if (ipv6) return ipv6
	const direct = normalizeHostCandidate(host)
	if (direct) return direct
	for (const candidate of fallbacks) {
		const normalized = normalizeHostCandidate(candidate)
		if (normalized) return normalized
	}
	return null
}

const dataToBuffer = async (data: unknown): Promise<Buffer | null> => {
	if (Buffer.isBuffer(data)) return data
	if (data instanceof ArrayBuffer) {
		return Buffer.from(data)
	}
	if (ArrayBuffer.isView(data)) {
		return Buffer.from(data.buffer, data.byteOffset, data.byteLength)
	}
	if (typeof Blob !== "undefined" && data instanceof Blob) {
		const arrayBuffer = await data.arrayBuffer()
		return Buffer.from(arrayBuffer)
	}
	if (data instanceof Uint8Array) {
		return Buffer.from(data)
	}
	return null
}

const deriveBotIdFromMdns = (
	instance: Instance,
	resolvedHost: string,
	txt: Record<string, string>,
	chosenHost: string,
): string => {
	const candidates: (string | undefined)[] = [
		txt.deviceId,
		txt.device_id,
		txt.id,
		txt.botId,
		txt.name,
		txt.hostname,
		instance.name,
		stripTrailingDot(resolvedHost),
		chosenHost,
		`${instance.name}-${instance.domain}`,
	]
	for (const candidate of candidates) {
		const sanitised = sanitizeIdentifier(candidate)
		if (sanitised) {
			return sanitised
		}
	}
	return `bot-${Math.random().toString(36).slice(2, 8)}`
}

type MdnsServiceState = {
	key: string
	instance: Instance
	connecting: boolean
	removed: boolean
	ws?: WebSocket
	connection?: BotConnection
	botId?: string
	reconnectTimer?: ReturnType<typeof setTimeout>
}

const mdnsStates = new Map<string, MdnsServiceState>()
let mdnsWatcher: InstanceWatcher | null = null

const handleMdnsSocketClose = (state: MdnsServiceState, ws: WebSocket) => {
	if (state.ws === ws) {
		state.ws = undefined
	}
	const botId = state.botId
	const connection = state.connection
	if (botId && connection) {
		detachBotConnection(botId, connection)
	}
	state.connection = undefined
	if (state.removed) {
		mdnsStates.delete(state.key)
		return
	}
	if (!state.removed) {
		if (state.reconnectTimer) {
			clearTimeout(state.reconnectTimer)
			state.reconnectTimer = undefined
		}
		state.reconnectTimer = setTimeout(() => {
			state.reconnectTimer = undefined
			void connectToMdnsService(state)
		}, 5_000)
	}
}

const connectToMdnsService = async (state: MdnsServiceState) => {
	if (state.removed) return
	if (state.connecting) return
	if (state.ws && state.ws.readyState === WebSocket.OPEN) {
		return
	}
	state.connecting = true
	try {
		const resolved = await resolveInstance(state.instance, 4_000)
		if (state.removed) return
		const fallbackHosts: string[] = []
		const registerFallback = (candidate?: string) => {
			const normalized = normalizeHostCandidate(candidate)
			if (!normalized) return
			if (!fallbackHosts.includes(normalized)) {
				fallbackHosts.push(normalized)
			}
		}
		const domainPart = stripTrailingDot(state.instance.domain) || "local"
		const rawInstance = stripTrailingDot(state.instance.name)
		const sanitizedInstance =
			sanitizeIdentifier(state.instance.name) || rawInstance
		if (sanitizedInstance) {
			registerFallback(`${sanitizedInstance}.${domainPart}`)
		}
		registerFallback(resolved.host)
		registerFallback(resolved.txt.host)
		registerFallback(resolved.txt.hostname)
		registerFallback(resolved.txt.address)
		registerFallback(resolved.txt.addr)
		if (sanitizedInstance) {
			registerFallback(sanitizedInstance)
		}
		if (rawInstance && rawInstance !== sanitizedInstance) {
			registerFallback(`${rawInstance}.${domainPart}`)
			registerFallback(rawInstance)
		}

		const triedHosts = new Set<string>()
		let addresses: string[] = []
		let resolvedHostCandidate =
			normalizeHostCandidate(resolved.host) || fallbackHosts[0] || ""
		for (const candidate of fallbackHosts) {
			if (!candidate) continue
			const key = candidate.toLowerCase()
			if (triedHosts.has(key)) continue
			triedHosts.add(key)
			try {
				const candidateAddrs = await getAddresses(candidate)
				if (candidateAddrs.length > 0) {
					addresses = candidateAddrs
					resolvedHostCandidate = candidate
					break
				}
			} catch (error) {
				console.log(`Failed to resolve IPs for ${candidate}:`, error)
			}
		}
		const addrs = [...new Set(addresses)]
		const bestHost = chooseBestHost(
			resolvedHostCandidate,
			addrs,
			fallbackHosts,
		)
		if (!bestHost) {
			throw new Error(
				`No reachable host for ${state.instance.name} (candidates: ${fallbackHosts.join(
					", ",
				)})`,
			)
		}
		const port = resolved.port || 80
		const formattedHost =
			bestHost.includes(":") && !bestHost.startsWith("[")
				? `[${bestHost}]`
				: bestHost
		const url = `ws://${formattedHost}${port === 80 ? "" : `:${port}`}/ws`
		console.log(
			`Connecting to bot via mDNS: ${state.instance.name} -> ${url}`,
		)
		const ws = new WebSocket(url)
		ws.binaryType = "arraybuffer"
		state.ws = ws
		const botId = deriveBotIdFromMdns(
			state.instance,
			resolved.host,
			resolved.txt,
			bestHost,
		)
		state.botId = botId
		ws.addEventListener("open", () => {
			if (state.removed) {
				ws.close()
				return
			}
			const connection = attachBotConnection(
				botId,
				createClientSocketAdapter(ws),
			)
			state.connection = connection
			connection.handlePong()
			setTimeout(() => {
				try {
					connection.send({ type: "ping" })
				} catch (error) {
					console.log("Error sending initial ping:", error)
				}
			}, 500)
		})
		ws.addEventListener("message", async (event) => {
			if (!state.botId) return
			const { data } = event
			if (typeof data === "string") {
				console.log("received bot text message", data)
				if (data === "ping") {
					botConnections.get(state.botId)?.handlePong()
					ws.send("pong")
				}
				return
			}
			const buffer = await dataToBuffer(data)
			if (!buffer) return
			try {
				const msg = decodeBotMsg(buffer)
				await handleBotMsg(state.botId, msg)
			} catch (error) {
				console.log("Error handling bot message:", error)
			}
		})
		ws.addEventListener("close", () => handleMdnsSocketClose(state, ws))
		ws.addEventListener("error", (error) => {
			console.log("mDNS websocket error:", error)
		})
	} catch (error) {
		if (!state.removed) {
			console.error(
				`Failed to connect to mDNS service ${state.instance.name}:`,
				error,
			)
		}
		if (state.reconnectTimer) {
			clearTimeout(state.reconnectTimer)
		}
		state.reconnectTimer = setTimeout(() => {
			state.reconnectTimer = undefined
			void connectToMdnsService(state)
		}, 5_000)
	} finally {
		state.connecting = false
	}
}

const handleMdnsAdd = (instance: Instance) => {
	const key = mdnsInstanceKey(instance)
	let state = mdnsStates.get(key)
	if (!state) {
		state = {
			key,
			instance,
			connecting: false,
			removed: false,
		}
		mdnsStates.set(key, state)
	} else {
		state.instance = instance
		state.removed = false
	}
	void connectToMdnsService(state)
}

const handleMdnsRemove = (instance: Instance) => {
	const key = mdnsInstanceKey(instance)
	const state = mdnsStates.get(key)
	if (!state) return
	state.removed = true
	if (state.reconnectTimer) {
		clearTimeout(state.reconnectTimer)
		state.reconnectTimer = undefined
	}
	if (state.botId && state.connection) {
		detachBotConnection(state.botId, state.connection)
		state.connection = undefined
	}
	if (state.ws) {
		try {
			state.ws.close()
		} catch (error) {
			console.log("Error closing mDNS websocket:", error)
		}
	} else {
		mdnsStates.delete(state.key)
	}
}

const startMdnsDiscovery = () => {
	try {
		mdnsWatcher = watchInstances("_ws._tcp", "local.")
		mdnsWatcher.on("added", (instance) => {
			handleMdnsAdd(instance)
		})
		mdnsWatcher.on("removed", (instance) => {
			handleMdnsRemove(instance)
		})
		console.log("mDNS discovery started for _ws._tcp")
	} catch (error) {
		console.error("Unable to start mDNS watcher:", error)
	}
}

startMdnsDiscovery()

if (typeof process !== "undefined") {
	process.on("exit", () => {
		mdnsWatcher?.stop()
	})
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
				if (!ws.data.botId) {
					console.log("Bot connection missing botId; closing")
					ws.close()
					return
				}
				const connection = attachBotConnection(
					ws.data.botId,
					createServerSocketAdapter(ws),
				)
				ws.data.connection = connection
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
					const message = buildConfigBroadcast(botId)
					if (message) {
						conn.send(message)
					}
				}
			}
		},
		close(ws) {
			console.log(`${ws.data.clientType} connection closed`)
			if (ws.data.clientType === "bot") {
				if (ws.data.botId) {
					detachBotConnection(ws.data.botId, ws.data.connection)
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
						const botId = ws.data.botId
						if (message === "ping" && botId) {
							// Treat as liveness signal
							botConnections.get(botId)?.handlePong()
							ws.send("pong")
						}
						return
					}
					console.log("received bot message", message)
					const binary = Buffer.isBuffer(message)
						? (message as Buffer)
						: Buffer.from(message as Uint8Array)
					const msg = decodeBotMsg(binary)
					if (ws.data.botId) {
						await handleBotMsg(ws.data.botId, msg)
					}
				}
			} catch (error) {
				console.log("Error handling message:", error)
			}
		},
	},
	development: true,
})

console.log("listening on http://localhost:7775")
