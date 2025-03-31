export class UiComponent<T> {
	public readonly root: T

	constructor(root: T) {
		this.root = root
	}
}

export class Container extends UiComponent<HTMLElement> {
	constructor(root: HTMLElement) {
		super(root)
	}

	public add(...components: UiComponent<HTMLElement>[]) {
		this.root.append(...components.map(c => c.root))
	}

	public clear() {
		this.root.innerHTML = ""
	}
}

export class VList extends UiComponent<HTMLDivElement> {
	constructor(args?: {
		style?: Partial<CSSStyleDeclaration>
	}) {
		super(document.createElement("div"))
		this.root.style.display = "flex"
		this.root.style.flexDirection = "column"
		if (args?.style) Object.assign(this.root.style, args.style)
	}

	public add(...components: UiComponent<HTMLElement>[]) {
		this.root.append(...components.map(c => c.root))
		return this
	}
}

export class HList extends UiComponent<HTMLDivElement> {
	constructor() {
		super(document.createElement("div"))
		this.root.style.display = "flex"
		this.root.style.flexDirection = "row"
	}

	public add(...components: (UiComponent<HTMLElement> | HTMLElement)[]) {
		this.root.append(...components.map(c => c instanceof HTMLElement ? c : c.root))
	}
}

export class Button extends UiComponent<HTMLButtonElement> {
	constructor(args: { text: string }) {
		super(document.createElement("button"))
		this.root.textContent = args.text
	}

	public set onClick(callback: () => void) {
		this.root.onclick = callback
	}
}

export class Label extends UiComponent<HTMLLabelElement> {
	constructor(args: { text: string }) {
		super(document.createElement("label"))
		this.root.textContent = args.text
	}
}

type SelectOption = {
	value: string
	text: string
}

export class Select extends UiComponent<HTMLSelectElement> {
	constructor(args: {
		label?: string
		value?: string
		options: SelectOption[]
	}) {
		super(document.createElement("select"))
		args.options.forEach(option => {
			const optionEl = document.createElement("option")
			optionEl.value = option.value
			optionEl.textContent = option.text
			this.root.appendChild(optionEl)
		})
		this.root.value = args.value || ""
	}

	public get value(): string {
		return this.root.value
	}

	public set onChange(callback: (value: string) => void) {
		this.root.onchange = () => callback(this.root.value)
	}
}

export class SelectGroup extends UiComponent<HTMLDivElement> {
	private select: Select

	constructor(args: {
		label: string
		value: string
		options: SelectOption[]
	}) {
		super(document.createElement("div"))
		this.root.style.display = "flex"
		this.root.style.flexDirection = "column"
		const labelEl = document.createElement("label")
		labelEl.textContent = args.label
		this.root.appendChild(labelEl)
		this.select = new Select({
			value: args.value,
			options: args.options
		})
		this.root.appendChild(this.select.root)
	}

	public get value(): string {
		return this.select.value
	}

	public set onChange(callback: (value: string) => void) {
		this.select.onChange = callback
	}
}

export class TextInput extends UiComponent<HTMLDivElement> {
	private input: HTMLInputElement

	constructor(args: {
		label?: string
		value?: string
		placeholder?: string
	}) {
		super(document.createElement("div"))
		this.root.style.display = "flex"
		this.root.style.flexDirection = "column"

		if (args.label) {
			const labelEl = document.createElement("label")
			labelEl.textContent = args.label
			this.root.appendChild(labelEl)
		}

		this.input = document.createElement("input")
		this.input.type = "text"
		this.input.placeholder = args.placeholder || ""
		this.input.value = args.value || ""
		this.root.appendChild(this.input)
	}

	public get value(): string {
		return this.input.value
	}
}

export class MultiCheckboxSelect extends UiComponent<HTMLDivElement> {
	private checkboxes: HTMLInputElement[] = []
	private checkboxContainer: HTMLDivElement

	constructor(args: {
		label?: string
		options: { value: string, text: string, checked?: boolean }[]
		expanded?: boolean
	}) {
		super(document.createElement("div"))
		this.root.style.display = "flex"
		this.root.style.flexDirection = "column"

		const isExpanded = args.expanded !== undefined ? args.expanded : false

		const header = document.createElement("div")
		header.style.display = "flex"
		header.style.alignItems = "center"
		header.style.cursor = "pointer"

		const toggleIcon = document.createElement("span")
		toggleIcon.textContent = isExpanded ? "▾" : "▸"
		toggleIcon.style.marginRight = "5px"

		if (args.label) {
			const labelEl = document.createElement("label")
			labelEl.textContent = args.label
			header.appendChild(toggleIcon)
			header.appendChild(labelEl)
		} else {
			header.appendChild(toggleIcon)
		}

		this.root.appendChild(header)

		this.checkboxContainer = document.createElement("div")
		this.checkboxContainer.style.display = isExpanded ? "flex" : "none"
		this.checkboxContainer.style.flexDirection = "column"
		this.checkboxContainer.style.maxHeight = "200px"
		this.checkboxContainer.style.overflowY = "auto"
		this.root.appendChild(this.checkboxContainer)

		for (const option of args.options) {
			const container = document.createElement("div")
			container.style.display = "flex"
			container.style.alignItems = "center"

			const checkbox = document.createElement("input")
			checkbox.type = "checkbox"
			checkbox.value = option.value
			checkbox.checked = option.checked || false

			const optionLabel = document.createElement("span")
			optionLabel.textContent = option.text
			optionLabel.style.marginLeft = "5px"

			container.appendChild(checkbox)
			container.appendChild(optionLabel)
			this.checkboxContainer.appendChild(container)

			this.checkboxes.push(checkbox)
		}

		header.onclick = () => {
			const isVisible = this.checkboxContainer.style.display !== "none"
			this.checkboxContainer.style.display = isVisible ? "none" : "flex"
			toggleIcon.textContent = isVisible ? "▸" : "▾"
		}
	}

	public get values(): string[] {
		return this.checkboxes.filter(chk => chk.checked).map(chk => chk.value)
	}

	public set onChange(callback: () => void) {
		this.checkboxes.forEach(checkbox => {
			checkbox.onchange = callback
		})
	}
}

export class InfiniteScroll extends UiComponent<HTMLElement> {
    private isLoading: boolean
    private onLoadMoreCallback: (() => Promise<void>) | null
    private sentinel: HTMLElement
    private observer: IntersectionObserver

    constructor(args: { container: UiComponent<HTMLElement> }) {
        super(document.createElement("div"))
		this.root.style.minHeight = "100px"

        // Append the custom container to our own root
        this.root.appendChild(args.container.root)
        this.isLoading = false
        this.onLoadMoreCallback = null

        // Create the sentinel element at the bottom
        this.sentinel = document.createElement("div")
        this.sentinel.style.height = "1px"
        this.sentinel.style.marginTop = "1px"
        this.root.appendChild(this.sentinel)

        // Use the custom container’s root as the observer's root
        const observerRoot = args.container.root
        const options: IntersectionObserverInit = {
            threshold: 0.1
        }
        this.observer = new IntersectionObserver((entries: IntersectionObserverEntry[]) => {
            entries.forEach((entry: IntersectionObserverEntry) => {
                if (!this.isLoading && entry.isIntersecting) {
                    this.loadMore()
                }
            })
        }, options)
        this.observer.observe(this.sentinel)
    }

    private async loadMore(): Promise<void> {
        this.isLoading = true
        if (this.onLoadMoreCallback) {
            await this.onLoadMoreCallback()
        }
        this.isLoading = false
    }

    public set onLoadMore(callback: () => Promise<void>) {
        this.onLoadMoreCallback = callback
    }
}

export class Header extends UiComponent<HTMLDivElement> {
	constructor(args: {
		title: string
		rightSide?: UiComponent<HTMLElement>
	}) {
		super(document.createElement("div"))
		this.root.className = "page-header"
		const title = document.createElement("h1")
		title.textContent = args.title
		title.style.flexGrow = "1"
		this.root.appendChild(title)
		if (args.rightSide) {
			this.root.append(args.rightSide.root)
		}
	}
}

export class WrapList implements UiComponent<HTMLDivElement> {
	public readonly root: HTMLDivElement

	constructor() {
		this.root = document.createElement("div")
		this.root.style.display = "flex"
		this.root.style.flexDirection = "row"
		this.root.style.flexWrap = "wrap"
		this.root.style.gap = "5px"
		this.root.style.overflowX = "auto"
		this.root.style.padding = "16px"
	}

	public add(device: UiComponent<HTMLElement>) {
		this.root.appendChild(device.root)
	}

	public set status(message: string) {
		this.root.innerHTML = `<p>${message}</p>`
	}

	public clear() {
		this.root.innerHTML = ""
	}
}

type KeyValue = {
	key: string
	value: string
	href?: string
}

export class KeyValueTable extends VList {
	constructor(items: KeyValue[]) {
		super()
		this.root.className = "list-row"
		for (const item of items) {
			const container = document.createElement("div")
			container.className = "table-cell"
			container.style.fontWeight = "bold"
			this.root.appendChild(container)
			const key = document.createElement("strong")
			key.textContent = item.key
			container.appendChild(key)
			if (item.href) {
				const link = document.createElement("a")
				link.href = item.href
				link.textContent = item.value
				container.appendChild(link)
			} else {
				container.appendChild(document.createTextNode(`: ${item.value}`))
			}
		}
	}
}

export class Collapsible extends UiComponent<HTMLDivElement> {
    private expandButton: HTMLButtonElement
    private content: UiComponent<HTMLElement>
    private contentContainer: HTMLDivElement
    private isOpen: boolean

    constructor(args: { 
        buttonText: string
        content: UiComponent<HTMLElement>
    }) {
        super(document.createElement("div"))
        // Position the root relative, so we can absolutely position the content
        this.root.style.position = "relative"

        // Create the expand button
        this.expandButton = document.createElement("button")
        this.expandButton.textContent = args.buttonText
        this.expandButton.style.cursor = "pointer"
        this.root.appendChild(this.expandButton)

        // Store the user-defined content
        this.content = args.content

        // Create a container for the content with absolute positioning
        this.contentContainer = document.createElement("div")
        this.contentContainer.style.position = "absolute"
        // Default to the right side
        this.contentContainer.style.top = "0"
        this.contentContainer.style.left = "100%"
        this.contentContainer.style.zIndex = "1000"
        // Hide by default
        this.contentContainer.style.display = "none"

        // Add the content's root into the container
        this.contentContainer.appendChild(this.content.root)
        this.root.appendChild(this.contentContainer)

        this.isOpen = false

        // Toggle the content on button click
        this.expandButton.addEventListener("click", (e: MouseEvent) => {
            e.stopPropagation()
            this.toggle()
        })

        // Hide the content if clicked outside
        document.addEventListener("click", this.handleDocumentClick.bind(this))
    }

    private toggle(): void {
        if (this.isOpen) {
            this.hide()
        } else {
            this.show()
        }
    }

    private show(): void {
        this.isOpen = true
        this.contentContainer.style.display = "block"

        // Reset to default (open on right)
        this.contentContainer.style.left = "100%"
        this.contentContainer.style.right = "auto"

        // Measure if it goes offscreen
        const rect = this.contentContainer.getBoundingClientRect()
        if (rect.right > window.innerWidth) {
            // Flip to open on the left
            this.contentContainer.style.left = "auto"
            this.contentContainer.style.right = "100%"
        }
    }

    private hide(): void {
        this.isOpen = false
        this.contentContainer.style.display = "none"
    }

    private handleDocumentClick(e: MouseEvent): void {
        if (!this.root.contains(e.target as Node)) {
            this.hide()
        }
    }
}

type TableColumnValue = string | number | boolean | HTMLElement | {
	value: string | number | boolean | HTMLElement
	href?: string
}

export class Table extends UiComponent<HTMLTableElement> {
	constructor(args: {
		headers: string[]
		rows: TableColumnValue[][]
	}) {
		super(document.createElement("table"))
		this.root.className = "table"
		const thead = document.createElement("thead")
		const tbody = document.createElement("tbody")

		const headerRow = document.createElement("tr")
		args.headers.forEach(header => {
			const th = document.createElement("th")
			th.textContent = header
			headerRow.appendChild(th)
		})
		thead.appendChild(headerRow)

		for (const row of args.rows) {
			const tr = document.createElement("tr")
			for (const cell of row) {
				const td = document.createElement("td")
				if (typeof cell === "string") {
					td.textContent = cell
				} else if (typeof cell === "boolean") {
					td.textContent = cell ? "True" : "False"
				} else if (typeof cell === "number") {
					td.textContent = cell.toString()
				} else if (typeof cell === "object" && cell !== null) {
					if ("value" in cell) {
						if (cell.href) {
							const link = document.createElement("a")
							link.href = cell.href
							link.textContent = String(cell.value)
							td.appendChild(link)
						} else {
							td.textContent = String(cell.value)
						}
					} else {
						td.appendChild(cell as HTMLElement)
					}
				}
				tr.appendChild(td)
			}
			tbody.appendChild(tr)
		}

		// args.rows.forEach(row => {
		// 	const tr = document.createElement("tr")
		// 	row.forEach(cell => {
		// 		const td = document.createElement("td")
		// 		if (typeof cell === "string") {
		// 			td.textContent = cell
		// 		} else if (typeof cell === "boolean") {
		// 			td.textContent = cell ? "True" : "False"
		// 		} else if (typeof cell === "number") {
		// 			td.textContent = cell.toString()
		// 		} else {
		// 			td.appendChild(cell)
		// 		}
		// 		tr.appendChild(td)
		// 	})
		// 	tbody.appendChild(tr)
		// })

		this.root.appendChild(thead)
		this.root.appendChild(tbody)
	}

}