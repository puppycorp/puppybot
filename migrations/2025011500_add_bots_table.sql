CREATE TABLE bots (
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
