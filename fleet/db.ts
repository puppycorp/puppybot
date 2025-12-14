import { Database } from "bun:sqlite"
import type { Bot } from "./types"

export type MigrationRow = {
	name: string
	applied_at: string
}

export type BotRow = {
	id: string
	version: string
	variant: string
	name: string | null
	ip: string | null
	client_id: string | null
	connected: number
	first_seen: string
	last_seen: string
}

const MIGRATIONS_TABLE_SQL = `
	CREATE TABLE IF NOT EXISTS migrations (
		name TEXT PRIMARY KEY,
		applied_at TEXT NOT NULL
	);
`

const BOTS_TABLE_SQL = `
	CREATE TABLE IF NOT EXISTS bots (
		id TEXT PRIMARY KEY,
		version TEXT NOT NULL DEFAULT '',
		variant TEXT NOT NULL DEFAULT '',
		name TEXT,
		ip TEXT,
		client_id TEXT,
		connected INTEGER NOT NULL DEFAULT 0,
		first_seen TEXT NOT NULL DEFAULT (datetime('now')),
		last_seen TEXT NOT NULL DEFAULT (datetime('now'))
	);
`

export class DataAccess {
	private readonly db: Database

	constructor(path: string) {
		this.db = new Database(path, { create: true })
		this.db.run("PRAGMA journal_mode = WAL;")
	}

	public close(force = false) {
		this.db.close(force)
	}

	public ensureMigrationsTable() {
		this.db.run(MIGRATIONS_TABLE_SQL)
	}

	public getAppliedMigrations() {
		const rows = this.db
			.query("SELECT name FROM migrations")
			.all() as MigrationRow[]

		return new Set(rows.map((row) => row.name))
	}

	public recordMigration(name: string) {
		this.db.query(`
			INSERT INTO migrations (name, applied_at)
			VALUES (?, datetime('now'))
		`).run(name)
	}

	public ensureBotsTable() {
		this.db.run(BOTS_TABLE_SQL)
	}

	public syncBot(bot: Bot) {
		this.db.query(`
			INSERT INTO bots (id, version, variant, name, ip, client_id, connected)
			VALUES (?, ?, ?, ?, ?, ?, ?)
			ON CONFLICT(id) DO UPDATE SET
				version = excluded.version,
				variant = excluded.variant,
				name = excluded.name,
				ip = excluded.ip,
				client_id = excluded.client_id,
				connected = excluded.connected,
				last_seen = datetime('now')
		`).run(
			bot.id,
			bot.version ?? "",
			bot.variant ?? "",
			bot.name ?? null,
			bot.ip ?? null,
			bot.clientId ?? null,
			bot.connected ? 1 : 0,
		)
	}

	public getStoredBots() {
		const rows = this.db
			.query(
				`
				SELECT id, version, variant, name, ip, client_id, connected
				FROM bots
				ORDER BY last_seen DESC
			`,
			)
			.all() as BotRow[]

		return rows.map((row) => ({
			id: row.id,
			version: row.version,
			variant: row.variant,
			name: row.name ?? undefined,
			ip: row.ip ?? undefined,
			clientId: row.client_id ?? undefined,
			connected: row.connected === 1,
		}))
	}

	public exec(sql: string) {
		this.db.exec(sql)
	}

	public transaction<T>(fn: () => T) {
		return this.db.transaction(fn)
	}
}
