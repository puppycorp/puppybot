import { onRouteChange } from "./router"

const getBotIdFromPath = (path: string) => {
	const match = path.match(/^\/bot\/([^/]+)(?:\/rover|\/arm)?\/?$/)
	return match ? match[1] : null
}

export const mountNavbar = (root: HTMLElement) => {
	root.innerHTML = ""

	const inner = document.createElement("aside")
	inner.className = "sidebar"

	const hero = document.createElement("div")
	hero.className = "sidebar-hero"
	hero.innerHTML = `
		<div class="ship-visual" aria-hidden="true">
			<div class="ship-body"></div>
			<div class="ship-wing ship-wing-left"></div>
			<div class="ship-wing ship-wing-right"></div>
			<div class="ship-light"></div>
		</div>
		<div class="sidebar-brand-row">
			<div class="brand-dog" aria-hidden="true">🐶</div>
			<div>
				<a class="sidebar-brand" href="/">PuppyBot<br />Mothership</a>
				<div class="sidebar-subtitle">Fleet Command Center</div>
			</div>
		</div>
	`
	inner.appendChild(hero)

	const links = document.createElement("nav")
	links.className = "sidebar-links"
	links.setAttribute("aria-label", "Mothership navigation")

	const makeLink = (icon: string, text: string, href: string) => {
		const link = document.createElement("a")
		link.className = "nav-link"
		link.href = href
		const iconEl = document.createElement("span")
		iconEl.className = "nav-icon"
		iconEl.textContent = icon
		const textEl = document.createElement("span")
		textEl.textContent = text
		link.append(iconEl, textEl)
		return link
	}

	const mothershipLink = makeLink("⌂", "Overview", "/")
	const botsLink = makeLink("▣", "Robots", "/robots")

	links.append(
		mothershipLink,
		botsLink,
	)
	inner.appendChild(links)

	const account = document.createElement("div")
	account.className = "sidebar-account"
	account.innerHTML = `
		<div class="account-avatar" aria-hidden="true">🐶</div>
		<div class="account-copy">
			<div class="account-name">PuppyBot Admin</div>
			<div class="account-email">admin@puppybot.ai</div>
		</div>
		<div class="account-chevron" aria-hidden="true">⌄</div>
	`
	inner.appendChild(account)
	root.append(inner)

	const updateActive = (path: string) => {
		const botId = getBotIdFromPath(path)

		const isOverview = path === "/" || path === ""
		const isRobots = path === "/robots"
		const allLinks = [mothershipLink, botsLink]
		for (const link of allLinks) link.removeAttribute("aria-current")
		if (isOverview) mothershipLink.setAttribute("aria-current", "page")
		if (isRobots) botsLink.setAttribute("aria-current", "page")

		if (botId) {
			botsLink.href = "/robots"
			botsLink.setAttribute("aria-current", "page")
		} else {
			botsLink.href = "/robots"
		}
	}

	onRouteChange((info) => updateActive(info.path))
	updateActive(window.location.pathname)
}
