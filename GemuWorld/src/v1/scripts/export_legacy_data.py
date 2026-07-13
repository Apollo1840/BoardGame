from __future__ import annotations

import argparse
from pathlib import Path

from _bootstrap import V1_ROOT  # noqa: F401
from gemuworld_db.database import connect, migrate
from gemuworld_db.legacy import export_legacy_cards, export_legacy_decks


def main() -> int:
    parser = argparse.ArgumentParser(description="Export database content in the legacy GemuWorld layout.")
    parser.add_argument("--database", type=Path, default=V1_ROOT / "data" / "gemuworld.sqlite3")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    connection = connect(args.database)
    try:
        migrate(connection)
        export_legacy_cards(connection, args.output / "cards")
        export_legacy_decks(connection, args.output / "clans")
    finally:
        connection.close()
    print(f"Exported legacy data to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

