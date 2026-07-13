from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from _bootstrap import REPOSITORY_ROOT, V1_ROOT  # noqa: F401
from gemuworld_db.database import connect, migrate
from gemuworld_db.legacy import import_legacy


DEFAULT_DATABASE = V1_ROOT / "data" / "gemuworld.sqlite3"
DEFAULT_MANUAL = REPOSITORY_ROOT / "GemuWorld" / "manual"


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Import current GemuWorld CSV, clan and design data into SQLite.")
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--manual-dir", type=Path, default=DEFAULT_MANUAL)
    parser.add_argument("--dry-run", action="store_true", help="Import into a temporary database and leave the target untouched.")
    parser.add_argument("--strict", action="store_true", help="Return failure when migration warnings are present.")
    parser.add_argument("--report", type=Path, help="Optional JSON report path.")
    args = parser.parse_args()

    temporary = tempfile.TemporaryDirectory(prefix="gemuworld-import-") if args.dry_run else None
    database = Path(temporary.name) / "dry-run.sqlite3" if temporary else args.database
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(database)
    try:
        migrations = migrate(connection)
        report = import_legacy(connection, V1_ROOT, args.manual_dir)
        output = report.as_dict() | {"database": str(database), "dry_run": args.dry_run, "migrations": migrations}
        rendered = json.dumps(output, ensure_ascii=False, indent=2)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 1 if report.errors or (args.strict and report.warnings) else 0
    finally:
        connection.close()
        if temporary:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
