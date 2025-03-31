import { Database } from "bun:sqlite"
import { readdirSync, readFileSync } from "fs"
import path from "path"
import { DATABASE_FILE } from "./config"

/**
 * Runs the SQLite migrations using the init.sql file.
 */
export function runMigrations() {
	const DB_FILE = path.resolve(DATABASE_FILE)
	const MIGRATIONS_FOLDER = path.resolve("migrations")

	// Connect to the SQLite database (creates file if missing)
	const db = new Database(DB_FILE, { create: true })

	try {
		// Get all migration files and sort them in ascending order
		const migrationFiles = readdirSync(MIGRATIONS_FOLDER)
			.filter(file => file.endsWith(".sql"))
			.sort()

		// Wrap migration execution in a transaction
		const transaction = db.transaction(() => {
			for (const file of migrationFiles) {
				const filePath = path.join(MIGRATIONS_FOLDER, file)
				const migrationSQL = readFileSync(filePath, "utf-8")

				console.log(`🚀 Applying migration: ${file}`)
				db.run(migrationSQL)
			}
		})

		transaction()
		console.log("✅ All migrations applied successfully.")
	} catch (error) {
		console.error("❌ Migration failed:", error)
	} finally {
		db.close(false)
	}
}