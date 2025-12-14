import { onRouteChange } from "./router"

const getBotIdFromPath = (path: string) => {
	const match = path.match(/^\/bot\/([^/]+)(?:\/rover)?\/?$/)
	return match ? match[1] : null
}

export const mountNavbar = (root: HTMLElement) => {
	root.innerHTML = ""

	const inner = document.createElement("div")
	inner.className = "navbar"

	const left = document.createElement("div")
	left.className = "navbar-left"

	const brand = document.createElement("a")
	brand.className = "navbar-brand"
	brand.href = "/"
	brand.textContent = "PuppyBot"
	left.appendChild(brand)

	const links = document.createElement("div")
	links.className = "navbar-links"

	const botsLink = document.createElement("a")
	botsLink.className = "nav-link"
	botsLink.href = "/"
	botsLink.textContent = "Bots"
	links.appendChild(botsLink)

	const roverLink = document.createElement("a")
	roverLink.className = "nav-link"
	roverLink.textContent = "Rover"
	roverLink.style.display = "none"
	links.appendChild(roverLink)

	left.appendChild(links)

	const right = document.createElement("div")
	right.className = "navbar-right"

	const location = document.createElement("div")
	location.className = "nav-location"
	right.appendChild(location)

	inner.append(left, right)
	root.append(inner)

	const updateActive = (path: string) => {
		const botId = getBotIdFromPath(path)
		const isRover = /^\/bot\/[^/]+\/rover\/?$/.test(path)

		const isBots = path === "/" || path === ""
		if (isBots) botsLink.setAttribute("aria-current", "page")
		else botsLink.removeAttribute("aria-current")

		if (botId) {
			roverLink.href = `/bot/${botId}/rover`
			roverLink.style.display = ""
			if (isRover) roverLink.setAttribute("aria-current", "page")
			else roverLink.removeAttribute("aria-current")
		} else {
			roverLink.style.display = "none"
			roverLink.removeAttribute("aria-current")
		}

		location.textContent = botId
			? isRover
				? `Rover · Bot ${botId}`
				: `Bot ${botId}`
			: isBots
				? "Bots"
				: path
		location.title = location.textContent || ""
	}

	onRouteChange((info) => updateActive(info.path))
	updateActive(window.location.pathname)
}
