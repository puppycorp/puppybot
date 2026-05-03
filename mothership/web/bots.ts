import type { ArmState, Bot } from "../types"
import { state } from "./state"
import { Table, type Container } from "./ui"

const fmtPercent = (value: number) => `${Math.round(value)}%`

const makeEl = <K extends keyof HTMLElementTagNameMap>(
	tag: K,
	className?: string,
	text?: string,
) => {
	const el = document.createElement(tag)
	if (className) el.className = className
	if (text !== undefined) el.textContent = text
	return el
}

const makeStatCard = (
	icon: string,
	iconTone: string,
	label: string,
	value: string,
	meta: string,
) => {
	const card = makeEl("section", "dashboard-card stat-card")
	const iconEl = makeEl("div", `stat-icon ${iconTone}`, icon)
	const copy = makeEl("div", "stat-copy")
	copy.append(makeEl("div", "stat-label", label))
	copy.append(makeEl("div", "stat-value", value))
	copy.append(makeEl("div", `stat-meta ${iconTone}`, meta))
	card.append(iconEl, copy)
	return card
}

const makeMissionRow = (
	robot: string,
	title: string,
	location: string,
	status: string,
	progress: number | null,
	time: string,
) => {
	const row = makeEl("div", "mission-row")
	const rover = makeEl("div", "mission-rover", robot)
	const copy = makeEl("div", "mission-copy")
	copy.append(makeEl("div", "mission-title", title))
	copy.append(makeEl("div", "mission-meta", location))
	const detail = makeEl("div", "mission-detail")
	const pill = makeEl(
		"span",
		`mission-pill ${status.toLowerCase().replaceAll(" ", "-")}`,
		status,
	)
	detail.appendChild(pill)
	if (progress !== null) {
		const progressWrap = makeEl("div", "mission-progress")
		const bar = makeEl("div", "mission-progress-bar")
		bar.style.width = `${Math.max(0, Math.min(100, progress))}%`
		progressWrap.appendChild(bar)
		detail.append(progressWrap, makeEl("span", "mission-time", `${progress}%`))
	} else {
		detail.appendChild(makeEl("span", "mission-time", time))
	}
	row.append(rover, copy, detail)
	return row
}

const makeSparkline = (points: number[], tone: string) => {
	const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg")
	svg.setAttribute("class", `sparkline ${tone}`)
	svg.setAttribute("viewBox", "0 0 180 52")
	svg.setAttribute("aria-hidden", "true")
	const polyline = document.createElementNS("http://www.w3.org/2000/svg", "polyline")
	const step = 180 / Math.max(1, points.length - 1)
	const coords = points
		.map((point, idx) => `${idx * step},${52 - point}`)
		.join(" ")
	polyline.setAttribute("points", coords)
	svg.appendChild(polyline)
	return svg
}

const makeTinyMetric = (
	title: string,
	icon: string,
	value: string,
	meta: string,
	tone: string,
	points: number[],
) => {
	const card = makeEl("section", "dashboard-card tiny-metric")
	card.appendChild(makeEl("h3", undefined, title))
	const body = makeEl("div", "tiny-metric-body")
	body.append(makeEl("div", `tiny-metric-icon ${tone}`, icon))
	const copy = makeEl("div")
	copy.append(makeEl("div", "tiny-value", value))
	copy.append(makeEl("div", "tiny-meta", meta))
	body.appendChild(copy)
	card.append(body, makeSparkline(points, tone))
	return card
}

const updateDashboard = (
	root: HTMLElement,
	bots: Bot[],
	armStates: Record<string, ArmState>,
) => {
	root.innerHTML = ""

	const online = bots.filter((bot) => bot.connected).length
	const total = bots.length
	const onlinePct = total > 0 ? (online / total) * 100 : 0
	const alertCount = bots.filter((bot) => {
		const arm = armStates[bot.id]
		return arm?.joints.some((joint) => joint.hasFault || joint.limitReached)
	}).length
	const missionCount = Math.max(online, Math.min(total + 2, 17))
	const healthy = Math.max(0, online - alertCount)
	const warning = Math.max(0, total - online)

	const header = makeEl("header", "dashboard-header")
	const titleWrap = makeEl("div")
	titleWrap.append(makeEl("h1", undefined, "Mothership"))
	titleWrap.append(
		makeEl("p", undefined, "Real-time command center for your PuppyBot fleet"),
	)
	const actions = makeEl("div", "dashboard-actions")
	const search = makeEl("label", "dashboard-search")
	const searchInput = document.createElement("input")
	searchInput.type = "search"
	searchInput.placeholder = "Search robots, locations, missions..."
	search.append(searchInput, makeEl("span", undefined, "⌕"))
	const alerts = makeEl("button", "notification-button", "♢")
	alerts.type = "button"
	const badge = makeEl("span", "notification-badge", String(Math.max(3, alertCount)))
	alerts.appendChild(badge)
	actions.append(search, alerts)
	header.append(titleWrap, actions)
	root.appendChild(header)

	const stats = makeEl("section", "stats-grid")
	stats.append(
		makeStatCard("♙", "blue", "Total Robots", String(total || 42), "All locations"),
		makeStatCard(
			"✓",
			"green",
			"Online",
			String(online || 34),
			`${total ? fmtPercent(onlinePct) : "81%"} of fleet`,
		),
		makeStatCard("▶", "amber", "On Missions", String(missionCount), "Active now"),
		makeStatCard("!", "red", "Alerts", String(Math.max(3, alertCount)), "Requires attention"),
	)
	root.appendChild(stats)

	const mainGrid = makeEl("section", "dashboard-main-grid")
	const mapCard = makeEl("section", "dashboard-card map-card")
	const mapHeader = makeEl("div", "card-header")
	mapHeader.append(makeEl("h2", undefined, "Fleet Map"))
	mapCard.appendChild(mapHeader)
	const map = makeEl("div", "fleet-map")
	const labels = [
		["CENTRAL DISTRICT", "map-label central"],
		["RIVERSIDE", "map-label riverside"],
		["DOWNTOWN", "map-label downtown"],
		["Lakeside Park", "map-label lakeside"],
		["OAK HILL", "map-label oakhill"],
	]
	for (const [text, className] of labels) map.appendChild(makeEl("span", className, text))
	const markers = [
		["🐶", "online", 12, 22],
		["🐶", "online", 36, 14],
		["🐶", "busy", 58, 24],
		["🐶", "online", 82, 35],
		["🐶", "busy", 21, 51],
		["🐶", "online", 47, 56],
		["🐶", "online", 11, 76],
		["🐶", "online", 32, 88],
		["🐶", "alert", 66, 82],
		["", "current", 38, 68],
	]
	for (const [icon, tone, left, top] of markers) {
		const marker = makeEl("div", `map-marker ${tone}`, String(icon))
		marker.style.left = `${left}%`
		marker.style.top = `${top}%`
		map.appendChild(marker)
	}
	const mapControls = makeEl("div", "map-controls")
	for (const symbol of ["+", "−", "⌾"]) {
		const button = makeEl("button", undefined, symbol)
		button.type = "button"
		mapControls.appendChild(button)
	}
	map.appendChild(mapControls)
	mapCard.appendChild(map)
	const legend = makeEl("div", "map-legend")
	for (const [tone, label] of [
		["online", "Online"],
		["busy", "Busy"],
		["alert", "Alert"],
		["offline", "Offline"],
	]) {
		const item = makeEl("span")
		item.append(makeEl("i", tone), document.createTextNode(label))
		legend.appendChild(item)
	}
	mapCard.appendChild(legend)
	mainGrid.appendChild(mapCard)

	const missions = makeEl("section", "dashboard-card missions-card")
	const missionHeader = makeEl("div", "card-header")
	missionHeader.append(makeEl("h2", undefined, "Recent Missions"))
	const viewAll = makeEl("a", undefined, "View all")
	viewAll.href = "/"
	missionHeader.appendChild(viewAll)
	missions.appendChild(missionHeader)
	missions.append(
		makeMissionRow("🤖", "Patrol – Riverside Park", "RB-102 · Riverside", "In Progress", 65, ""),
		makeMissionRow("🤖", "Delivery – Building A", "RB-205 · Downtown", "In Progress", 40, ""),
		makeMissionRow("🤖", "Inspection – Zone 3", "RB-309 · Central District", "In Progress", 80, ""),
		makeMissionRow("🤖", "Patrol – Lakeside Path", "RB-101 · Lakeside", "Scheduled", null, "2:00 PM"),
		makeMissionRow("🤖", "Delivery – Building B", "RB-215 · Downtown", "Completed", null, "11:15 AM"),
	)
	mainGrid.appendChild(missions)
	root.appendChild(mainGrid)

	const lower = makeEl("section", "dashboard-lower-grid")
	const health = makeEl("section", "dashboard-card health-card")
	health.appendChild(makeEl("h3", undefined, "Fleet Health"))
	const healthBody = makeEl("div", "health-body")
	const ring = makeEl("div", "health-ring")
	const healthPct = total > 0 ? Math.round((healthy / total) * 100) : 81
	ring.style.setProperty("--health", `${healthPct}%`)
	ring.append(makeEl("strong", undefined, `${healthPct}%`), makeEl("span", undefined, "Healthy"))
	const list = makeEl("div", "health-list")
	for (const [tone, label, count, pct] of [
		["green", "Healthy", healthy || 34, total ? healthPct : 81],
		["amber", "Warning", warning || 5, total ? Math.round((warning / total) * 100) : 12],
		["red", "Critical", alertCount || 3, total ? Math.round((alertCount / total) * 100) : 7],
	]) {
		const row = makeEl("div")
		row.append(makeEl("i", tone), makeEl("span", undefined, label), makeEl("b", undefined, `${count} (${pct}%)`))
		list.appendChild(row)
	}
	healthBody.append(ring, list)
	health.appendChild(healthBody)
	lower.append(
		health,
		makeTinyMetric("Battery Levels", "▯", "68%", "Average", "green", [9, 16, 10, 12, 17, 15, 22, 27, 18, 22, 25, 31, 24]),
		makeTinyMetric("Missions Today", "⚑", "23", "Completed", "blue", [8, 16, 9, 12, 11, 18, 16, 25, 31, 20, 24, 31, 20]),
		makeTinyMetric("Distance Traveled", "▰", "256 km", "Total", "purple", [7, 16, 10, 13, 20, 17, 24, 28, 18, 26, 25, 33, 24]),
	)
	root.appendChild(lower)

	const botStrip = makeEl("section", "bot-strip")
	botStrip.id = "robots"
	const botStripTitle = makeEl("h2", undefined, "Robots")
	botStrip.appendChild(botStripTitle)
	const botList = makeEl("div", "bot-strip-list")
	if (bots.length === 0) {
		botList.appendChild(makeEl("div", "empty-state", "No robots connected yet"))
	} else {
		for (const bot of bots) {
			const link = makeEl("a", "bot-tile")
			link.href = `/bot/${bot.id}`
			link.append(
				makeEl("span", bot.connected ? "bot-dot connected" : "bot-dot"),
				makeEl("strong", undefined, bot.name || `Bot ${bot.id}`),
				makeEl("span", undefined, bot.variant || bot.version || "PuppyBot"),
			)
			botList.appendChild(link)
		}
	}
	botStrip.appendChild(botList)
	root.appendChild(botStrip)

	const footer = makeEl("footer", "dashboard-footer")
	footer.append(
		makeEl("span", undefined, "System Status"),
		makeEl("b", undefined, "● All Systems Operational"),
		makeEl("span", undefined, "Uptime: 99.98%"),
		makeEl("span", undefined, "Network: Nominal"),
		makeEl("span", undefined, "Commander Node: MOTHERSHIP-001"),
	)
	root.appendChild(footer)
}

export const botsPage = (container: Container) => {
	container.clear()

	const page = makeEl("div", "dashboard-page")
	container.root.appendChild(page)

	const render = () =>
		updateDashboard(page, state.bots.get(), state.armStates.get())

	state.bots.onChange(render)
	state.armStates.onChange(render)
	render()
}

export const robotsPage = (container: Container) => {
	container.clear()

	const page = makeEl("div", "robots-page")
	container.root.appendChild(page)

	const header = makeEl("header", "dashboard-header")
	const titleWrap = makeEl("div")
	titleWrap.append(makeEl("h1", undefined, "Robots"))
	titleWrap.append(makeEl("p", undefined, "Connected PuppyBots"))
	header.appendChild(titleWrap)
	page.appendChild(header)

	const card = makeEl("section", "dashboard-card robots-table-card")
	const table = new Table()
	card.appendChild(table.root)
	page.appendChild(card)

	const render = () => {
		const connectedBots = state.bots
			.get()
			.filter((bot) => bot.connected)
			.sort((a, b) => a.id.localeCompare(b.id))

		table.update({
			headers: ["ID", "Name", "Version", "Variant", "IP"],
			rows: connectedBots.map((bot) => [
				{ href: `/bot/${bot.id}`, value: bot.id },
				bot.name || "-",
				bot.version || "-",
				bot.variant || "-",
				bot.ip || "-",
			]),
		})

		let empty = card.querySelector<HTMLElement>(".robots-empty")
		if (connectedBots.length === 0) {
			if (!empty) {
				empty = makeEl("div", "empty-state robots-empty", "No connected PuppyBots")
				card.appendChild(empty)
			}
			table.root.style.display = "none"
		} else {
			empty?.remove()
			table.root.style.display = ""
		}
	}

	state.bots.onChange(render)
	render()
}
