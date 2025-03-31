
import index from "./index.html"

Bun.serve({
	port: 7775,
	routes: {
		"/api/bots": () => {
			return new Response(JSON.stringify({ bots: [] }), {
				headers: { "Content-Type": "application/json" }
			})
		},
		"/*": index
	},
	development: true
})