import { spawn } from "node:child_process"

export type Instance = { name: string; domain: string; type: string }
export type Resolved = {
	name: string
	type: string
	host: string
	port: number
	txt: Record<string, string>
	addrs: string[]
}

function spawnDnsSd(args: string[]) {
	const p = spawn("dns-sd", args)
	// Forward stderr to help debugging parsing issues
	p.stderr.on("data", (d) => process.stderr.write(d))
	return p
}

export function browseInstances(
	type: string,
	domain = "local.",
	timeoutMs = 2000,
): Promise<Instance[]> {
	return new Promise((resolve) => {
		const p = spawnDnsSd(["-B", type, domain])
		const instances = new Map<string, Instance>()

		const onLine = (line: string) => {
			// Typical lines when browsing a type:
			// " 9:12:05.000  Add   ...  local.   _ws._tcp.   PuppyBot"
			// or sometimes without trailing dot on type
			const m = line.match(
				/\s(Add|Rmv)\b.*?\s(\S+)\s+(_[^\s]+?\._tcp\.?|_[^\s]+?\._udp\.?)\s+(.+?)\s*$/,
			)
			if (!m) return
			const action = m[1]
			const domainStr = m[2]
			const typeStr = m[3]
			const instanceName = m[4]
			if (!instanceName) return
			if (action === "Add") {
				instances.set(instanceName, {
					name: instanceName,
					domain: domainStr,
					type,
				})
			} else if (action === "Rmv") {
				instances.delete(instanceName)
			}
		}

		const timer = setTimeout(() => {
			p.kill("SIGINT")
			resolve([...instances.values()])
		}, timeoutMs)

		p.stdout.on("data", (d) => d.toString().split("\n").forEach(onLine))
		p.on("close", () => {
			clearTimeout(timer)
			resolve([...instances.values()])
		})
	})
}

export function resolveInstance(
	inst: Instance,
	timeoutMs = 2000,
): Promise<{
	host: string
	port: number
	txt: Record<string, string>
}> {
	return new Promise((resolve) => {
		const p = spawnDnsSd(["-L", inst.name, inst.type, inst.domain])
		let host = ""
		let port = 0
		const txt: Record<string, string> = {}

		const onLine = (line: string) => {
			// Example: " ... can be reached at puppybot.local.:80 ..."
			const mSRV = line.match(/can be reached at\s+([^\s:]+)\.?:(\d+)/i)
			if (mSRV) {
				host = mSRV[1]
				port = parseInt(mSRV[2], 10)
			}
			// Example: "TXT records: fw=1.3.2 role=gateway"
			const mTXT = line.match(/TXT records:\s*(.*)$/i)
			if (mTXT) {
				mTXT[1]
					.split(/\s+/)
					.filter(Boolean)
					.forEach((pair) => {
						const eq = pair.indexOf("=")
						if (eq > 0) {
							const k = pair.slice(0, eq)
							const v = pair.slice(eq + 1)
							txt[k] = v
						}
					})
			}
		}

		const timer = setTimeout(() => {
			p.kill("SIGINT")
			resolve({ host, port, txt })
		}, timeoutMs)

		p.stdout.on("data", (d) => d.toString().split("\n").forEach(onLine))
		p.on("close", () => {
			clearTimeout(timer)
			resolve({ host, port, txt })
		})
	})
}

export function getAddresses(
	host: string,
	timeoutMs = 1200,
): Promise<string[]> {
	return new Promise((resolve) => {
		const addrs: Set<string> = new Set()
		const p = spawnDnsSd(["-G", "v4v6", host])
		const onLine = (line: string) => {
			// Example: "  Add   ...  v4 puppybot.local. 10.0.0.12"
			const m = line.match(/\s(Add|Rmv)\b.*?\s(v4|v6)\s+\S+\s+([^\s]+)/)
			if (m && m[1] === "Add") addrs.add(m[3])
		}
		const timer = setTimeout(() => {
			p.kill("SIGINT")
			resolve([...addrs])
		}, timeoutMs)
		p.stdout.on("data", (d) => d.toString().split("\n").forEach(onLine))
		p.on("close", () => {
			clearTimeout(timer)
			resolve([...addrs])
		})
	})
}

export async function discover(
	type = "_ws._tcp",
	domain = "local.",
): Promise<Resolved[]> {
	const instances = await browseInstances(type, domain)
	const results: Resolved[] = []
	for (const inst of instances) {
		const { host, port, txt } = await resolveInstance(inst)
		const addrs = host ? await getAddresses(host) : []
		results.push({ name: inst.name, type, host, port, txt, addrs })
	}
	return results
}

// If run directly: perform discovery and print JSON
if (import.meta.main) {
	const type = process.argv[2] || "_ws._tcp"
	const domain = process.argv[3] || "local."
	discover(type, domain)
		.then((list) => {
			console.log(JSON.stringify(list, null, 2))
		})
		.catch((err) => {
			console.error(err)
			process.exit(1)
		})
}
