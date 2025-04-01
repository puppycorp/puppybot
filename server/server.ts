
import index from "./index.html"
import type { MsgToServer } from "./types"


const handleMsg = (ws: WebSocket, msg: MsgToServer) => {
	
}

Bun.serve({
	port: 7775,
	routes: {
		"/api/bots": () => {
			return new Response(JSON.stringify({ bots: [] }), {
				headers: { "Content-Type": "application/json" }
			})
		},
		"/api/bot/:id/ws": (req) => {
			const { id } = req.params as { id: string }
			if (!id) {
				return new Response("Bot ID is required", { status: 400 })
			}

			req.up

			return ws
		},
		"/*": index
	},
	websocket: {
		open(ws) {
			console.log("WebSocket connection opened")
			ws.send("Hello from server")
		},
		message(ws, message) {
			const msg = JSON.parse(message.toString()) as MsgToServer

			console.log("Message received:", message)
			// Handle the message here
			// For example, you can send a response back to the client
			ws.send("Message received")
		},
	},
	development: true
})