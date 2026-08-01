from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS = ROOT / "migrations"


def connect(path: str | Path) -> sqlite3.Connection:
    connection = sqlite3.connect(Path(path))
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def migrate(connection: sqlite3.Connection) -> list[str]:
    connection.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    applied = {
        row[0] for row in connection.execute("SELECT version FROM schema_migrations")
    }
    installed: list[str] = []
    for migration in sorted(MIGRATIONS.glob("*.sql")):
        if migration.name in applied:
            continue
        script = migration.read_text(encoding="utf-8")
        foreign_keys_off = script.startswith("-- migrate: foreign_keys_off")
        if foreign_keys_off:
            connection.commit()
            connection.execute("PRAGMA foreign_keys = OFF")
        # executescript controls its own transaction; the migration itself is atomic.
        try:
            connection.executescript(
                "BEGIN IMMEDIATE;\n"
                + script
                + "\nINSERT INTO schema_migrations(version) VALUES ("
                + repr(migration.name)
                + ");\nCOMMIT;"
            )
        finally:
            if foreign_keys_off:
                connection.execute("PRAGMA foreign_keys = ON")
        installed.append(migration.name)
    if "020_card_serial_numbers.sql" in applied or "020_card_serial_numbers.sql" in installed:
        from .serials import backfill_card_serials

        backfill_card_serials(connection)
    return installed
