from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _bootstrap import V1_ROOT  # noqa: F401
from gemuworld_db.batch_import import BatchImportError, import_cards
from gemuworld_db.database import connect, migrate


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Create or overwrite cards by exact Chinese title from a legacy pipe-delimited CSV.")
    parser.add_argument("card_type", nargs="?", choices=("monster", "prophecy"), help="Omit to import both default transport files.")
    parser.add_argument("csv_file", nargs="?", type=Path, help="Omit to use data/transport/<type>_cards.csv.")
    parser.add_argument("--database", type=Path, default=V1_ROOT / "data" / "gemuworld.sqlite3")
    parser.add_argument("--transport-dir", type=Path, default=V1_ROOT / "data" / "transport")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.csv_file is not None and args.card_type is None:
        parser.error("csv_file requires card_type")
    if args.card_type:
        jobs = [(args.card_type, args.csv_file or args.transport_dir / f"{args.card_type}_cards.csv")]
    else:
        jobs = [(card_type, args.transport_dir / f"{card_type}_cards.csv") for card_type in ("monster", "prophecy")]
    missing = [str(path) for _, path in jobs if not path.is_file()]
    if missing:
        print(json.dumps({"error": "transport CSV file not found", "missing": missing}, ensure_ascii=False, indent=2))
        return 1
    connection = connect(args.database)
    try:
        migrate(connection)
        # Validate every input before the first write so a malformed second
        # transport file cannot leave a partially applied default run.
        if not args.dry_run:
            for card_type, path in jobs:
                import_cards(connection, card_type, path.read_text(encoding="utf-8-sig"), dry_run=True)
        results = [import_cards(connection, card_type, path.read_text(encoding="utf-8-sig"), dry_run=args.dry_run).as_dict() | {"source": str(path)} for card_type, path in jobs]
    except (BatchImportError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
        return 1
    finally:
        connection.close()
    print(json.dumps({"dry_run": args.dry_run, "imports": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
