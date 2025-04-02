import { state } from "./state";
import { Table, type Container } from "./ui";


export const botsPage = (container: Container) => {
	container.clear()

	const table = new Table({
		headers: ["ID", "Name", "Description", "Version", "Enabled"],
		rows: [
			[{ href: `/bot/1`, value: "1" }, "Bot 1", "Description 1", "1.0.0", true],
			[{ href: `/bot/2`, value: "2" }, "Bot 2", "Description 2", "1.0.1", false],
			[{ href: `/bot/3`, value: "3" }, "Bot 3", "Description 3", "1.0.2", true],
		]
	})

	state.bots.onChange((bots) => {
		
	})
	container.add(table)
}