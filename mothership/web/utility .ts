export const setQueryParam = (field: string, value: string) => {
	const url = new URL(window.location.href)
	url.searchParams.set(field, value)
	window.history.pushState({}, "", url.toString())
}
export const getQueryParam = (field: string): string | null => {
	const url = new URL(window.location.href)
	return url.searchParams.get(field)
}
export const removeQueryParam = (field: string) => {
	const url = new URL(window.location.href)
	url.searchParams.delete(field)
	window.history.pushState({}, "", url.toString())
}
