import { state } from "./state"
import { Table, type Container } from "./ui"

export const botsPage = (container: Container) => {
	container.clear()

	const table = new Table()

	state.bots.onChange((bots) => {
		table.update({
			headers: ["ID", "State", "Version", "Variant"],
			rows: bots.map((bot) => [
				{ href: `/bot/${bot.id}`, value: bot.id },
				bot.connected ? "Connected" : "Disconnected",
				bot.version || "-",
				bot.variant || "-",
			]),
		})
	})
	container.add(table)
}
