from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from _bootstrap import V1_ROOT  # noqa: F401
from gemuworld_db.database import connect, migrate
from gemuworld_db.profession_deck_sync import ProfessionDeckSyncError, sync_profession_decks


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Append profession-matching cards to the five profession decks while preserving existing order.")
    parser.add_argument("--database", type=Path, default=V1_ROOT / "data" / "gemuworld.sqlite3")
    parser.add_argument("--apply", action="store_true", help="Commit additions. Without this flag the command previews and rolls back all changes.")
    parser.add_argument("--verbose", action="store_true", help="Include every appended card in the JSON output.")
    args = parser.parse_args()
    connection = connect(args.database)
    try:
        migrate(connection)
        output = sync_profession_decks(connection, dry_run=not args.apply)
        if not args.verbose:
            output["decks"] = [{key: value for key, value in deck.items() if key != "added"} for deck in output["decks"]]
    except (ProfessionDeckSyncError, sqlite3.Error) as exc:
        print(json.dumps({"applied": False, "error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    finally:
        connection.close()
    print(json.dumps({"applied": args.apply, **output}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
