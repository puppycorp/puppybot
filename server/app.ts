import { botPage } from "./bot";
import { botsPage } from "./bots";
import { routes } from "./router";
import { Container } from "./ui";

window.onload = () => {

    console.log("Page loaded successfully");
	const container = new Container(document.body)
	routes({
		"/": () => botsPage(container),
		"/bot/:id": () => botPage(container),
		"*": () => {
			container.clear()
			container.root.innerHTML = "<h1>404 Not Found</h1>"
		}
	})
}