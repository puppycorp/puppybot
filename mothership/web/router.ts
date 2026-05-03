// First, allow “*” in the type so it remains a valid pattern:
type ExtractRouteParams<T extends string> =
	// If there is a “*” anywhere, treat that pattern as producing no named params
	T extends `${infer _Start}*${infer _Rest}`
		? Record<string, string>
		: // Else look for :param in the route
			T extends `${infer _Start}:${infer Param}/${infer Rest}`
			? { [K in Param]: string } & ExtractRouteParams<Rest>
			: T extends `${infer _Start}:${infer Param}`
				? { [K in Param]: string }
				: Record<string, string>

// Keep the rest of your definitions as they were:
type RouteHandler<Pattern extends string, Result> = (
	params: ExtractRouteParams<Pattern>,
) => Result

type PatternMatcherHandlers = {
	[Pattern in string]: RouteHandler<Pattern, any>
}

type InferHandlerReturn<H> = H extends RouteHandler<any, infer R> ? R : never

type MatchResult<T extends PatternMatcherHandlers> = {
	pattern: keyof T
	params: Record<string, string>
	result: InferHandlerReturn<T[keyof T]>
} | null

function patternMatcher<T extends Record<string, (params: any) => any>>(
	handlers: T,
) {
	type TypedHandlers = {
		[K in keyof T]: (
			params: ExtractRouteParams<K & string>,
		) => ReturnType<T[K]>
	}
	const typedHandlers = handlers as TypedHandlers

	const routes = Object.keys(typedHandlers).sort((a, b) => {
		// Basic sort so that literal paths come first, then “:” params, then “*”
		if (!a.includes("*") && !a.includes(":")) return -1
		if (!b.includes("*") && !b.includes(":")) return 1

		if (a.includes(":") && !b.includes(":")) return -1
		if (!a.includes(":") && b.includes(":")) return 1

		if (a.includes("*") && !b.includes("*")) return 1
		if (!a.includes("*") && b.includes("*")) return -1

		// Finally, if both patterns look structurally similar, sort by length descending
		return b.length - a.length
	})

	return {
		match(
			path: string,
		): { pattern: keyof T; params: Record<string, string>; result: ReturnType<T[keyof T]> } | null {
			for (const route of routes) {
				const params = matchRoute(route, path)
				if (params !== null) {
					const result = typedHandlers[route](params)
					return { pattern: route, params, result }
				}
			}
			return null
		},
	}
}

// Your match logic:
function matchRoute(
	pattern: string,
	path: string,
): Record<string, string> | null {
	const patternParts = pattern
		.split("/")
		.filter((segment) => segment.length > 0)
	const pathParts = path.split("/").filter((segment) => segment.length > 0)

	// Special case “/*” => matches anything
	if (pattern === "/*") return {}

	// If lengths differ, check trailing “*”
	if (patternParts.length !== pathParts.length) {
		const lastPattern = patternParts[patternParts.length - 1]
		if (
			lastPattern === "*" &&
			pathParts.length >= patternParts.length - 1
		) {
			return {}
		}
		return null
	}

	const params: Record<string, string> = {}

	for (let i = 0; i < patternParts.length; i++) {
		const patternPart = patternParts[i]
		const pathPart = pathParts[i]

		if (patternPart === "*") {
			// Don’t need to store anything; treat as "match the rest"
			return params
		}
		if (patternPart.startsWith(":")) {
			const paramName = patternPart.slice(1)
			params[paramName] = pathPart
		} else if (patternPart !== pathPart) {
			return null
		}
	}

	return params
}

let matcher: any

type RouteChangeInfo = {
	path: string
	match: { pattern: string; params: Record<string, string> } | null
}

const routeChangeListeners: ((info: RouteChangeInfo) => void)[] = []

export const onRouteChange = (listener: (info: RouteChangeInfo) => void) => {
	routeChangeListeners.push(listener)
	return () => {
		const idx = routeChangeListeners.indexOf(listener)
		if (idx >= 0) routeChangeListeners.splice(idx, 1)
	}
}

const handleRoute = (path: string) => {
	if (!matcher) return
	const m = matcher.match(path)
	if (!m) console.error("No route found for", path)
	console.log("match result", m)
	const info: RouteChangeInfo = {
		path,
		match: m ? { pattern: String(m.pattern), params: m.params ?? {} } : null,
	}
	for (const listener of routeChangeListeners) listener(info)
}
window.addEventListener("popstate", () => {
	handleRoute(window.location.pathname)
})

export const routes = (routes: any) => {
	matcher = patternMatcher(routes)
	handleRoute(window.location.pathname)
}

export const navigate = (path: string) => {
	window.history.pushState({}, "", path)
	handleRoute(path)
}
