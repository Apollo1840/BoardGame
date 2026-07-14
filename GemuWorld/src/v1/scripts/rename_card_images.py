from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import V1_ROOT  # noqa: F401
from gemuworld_db.database import connect, migrate
from gemuworld_db.image_renamer import apply_image_renames, plan_image_renames


def main() -> int:
    parser = argparse.ArgumentParser(description="Rename linked card artwork to <card_id>.png and synchronize SQLite paths.")
    parser.add_argument("--database", type=Path, default=V1_ROOT / "data" / "gemuworld.sqlite3")
    parser.add_argument("--pics", type=Path, default=V1_ROOT / "data" / "current" / "pics")
    parser.add_argument("--manifest-dir", type=Path, default=V1_ROOT / "data" / "tmp")
    parser.add_argument("--apply", action="store_true", help="Apply the checked plan. Without this flag the command is read-only.")
    parser.add_argument("--verbose", action="store_true", help="Include every card mapping in dry-run JSON output.")
    args = parser.parse_args()
    connection = connect(args.database)
    try:
        migrate(connection)
        if args.apply:
            output = apply_image_renames(connection, args.pics, args.manifest_dir)
        else:
            output = {"applied": False, **plan_image_renames(connection, args.pics)}
            if not args.verbose:
                output.pop("items", None)
    except ValueError as exc:
        output = {"applied": False, "error": str(exc)}
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 2
    finally:
        connection.close()
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if not output.get("errors") else 2


if __name__ == "__main__":
    raise SystemExit(main())
