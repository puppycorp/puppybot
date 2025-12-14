import { botPage } from "./bot"
import { botsPage } from "./bots"
import { mountNavbar } from "./navbar"
import { roverPage } from "./rover"
import { routes } from "./router"
import { Container } from "./ui"

window.onload = () => {
	console.log("Page loaded successfully")
	const navbarRoot = document.getElementById("navbar")
	if (navbarRoot) mountNavbar(navbarRoot)

	const appRoot = document.getElementById("app")
	if (!appRoot) throw new Error("App root not found")

	const container = new Container(appRoot)
	routes({
		"/": () => botsPage(container),
		"/bot/:id/rover": (params) => roverPage(container, params.id),
		"/bot/:id": (params) => botPage(container, params.id),
		"*": () => {
			container.clear()
			container.root.innerHTML = "<h1>404 Not Found</h1>"
		},
	})
}
