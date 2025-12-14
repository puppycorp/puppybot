import { existsSync, readdirSync, readFileSync } from "node:fs"
import { join } from "node:path"
import { DataAccess } from "./fleet/db.ts"

const DATABASE_PATH = process.env.DATABASE_FILE || "puppyfleet.db"
const MIGRATIONS_DIR = "./migrations"
const MIGRATION_NAME_PATTERN = /^\d{10}_.*\.sql$/

function getMigrationFiles() {
	if (!existsSync(MIGRATIONS_DIR)) {
		return []
	}

	return readdirSync(MIGRATIONS_DIR)
		.filter((file) => MIGRATION_NAME_PATTERN.test(file))
		.sort()
}

function applyMigration(db: DataAccess, filename: string) {
	const fullPath = join(MIGRATIONS_DIR, filename)
	const sql = readFileSync(fullPath, "utf8")
	const timestamp = filename.split("_")[0]

	const tx = db.transaction(() => {
		db.exec(sql)
		db.recordMigration(filename)
	})

	tx()
	console.log(`✓ Applied ${filename} (${timestamp})`)
}

function migrate() {
	const db = new DataAccess(DATABASE_PATH)
	try {
		db.ensureMigrationsTable()

		const applied = db.getAppliedMigrations()
		const files = getMigrationFiles()
		const pending = files.filter((file) => !applied.has(file))

		if (pending.length === 0) {
			if (files.length === 0) {
				console.log("No migration files found")
			} else {
				console.log("No pending migrations")
			}
			return
		}

		console.log(`Running ${pending.length} migration(s)...`)
		for (const file of pending) {
			applyMigration(db, file)
		}
		console.log("All migrations applied")
	} catch (error) {
		console.error("Migration failed:", error)
	} finally {
		db.close(false)
	}
}

migrate()
