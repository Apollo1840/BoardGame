from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import V1_ROOT  # noqa: F401
from gemuworld_db.database import connect, migrate


CHECKS = {
    "foreign_keys": "PRAGMA foreign_key_check",
    "ownerless_or_shared_effects": "SELECT id FROM effects WHERE (monster_card_id IS NULL) = (prophecy_card_id IS NULL)",
    "effect_type_owner_mismatch": "SELECT id FROM effects WHERE (monster_card_id IS NOT NULL AND effect_type NOT LIKE 'monster_%') OR (prophecy_card_id IS NOT NULL AND effect_type NOT LIKE 'prophecy_%')",
    "ownerless_or_shared_deck_cards": "SELECT deck_id,position FROM deck_cards WHERE (monster_card_id IS NULL) = (prophecy_card_id IS NULL)",
    "missing_zh_monster_translation": "SELECT id,card_id FROM monster_cards WHERE NOT EXISTS (SELECT 1 FROM monster_card_translations t WHERE t.monster_card_id=monster_cards.id AND language='zh')",
    "missing_zh_prophecy_translation": "SELECT id,card_id FROM prophecy_cards WHERE NOT EXISTS (SELECT 1 FROM prophecy_card_translations t WHERE t.prophecy_card_id=prophecy_cards.id AND language='zh')",
    "oversized_effect_marker": "SELECT id,marker FROM effects WHERE LENGTH(marker)>10",
    "noncanonical_monster_skill_order": """
        WITH ordered AS (
            SELECT e.id, e.monster_card_id, e.position,
                   COALESCE(e.energy_cost, 0) AS energy_cost,
                   COALESCE(t.text, '') AS effect_text,
                   ROW_NUMBER() OVER (PARTITION BY e.monster_card_id ORDER BY e.position) - 1 AS expected_position,
                   LAG(COALESCE(e.energy_cost, 0)) OVER (PARTITION BY e.monster_card_id ORDER BY e.position) AS previous_energy,
                   LAG(COALESCE(t.text, '')) OVER (PARTITION BY e.monster_card_id ORDER BY e.position) AS previous_text
            FROM effects e
            LEFT JOIN effect_translations t ON t.effect_id=e.id AND t.language='zh'
            WHERE e.effect_type='monster_skill'
        )
        SELECT id, monster_card_id, position
        FROM ordered
        WHERE position<>expected_position
           OR previous_energy>energy_cost
           OR (previous_energy=energy_cost AND previous_text COLLATE NOCASE>effect_text COLLATE NOCASE)
    """,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the GemuWorld SQLite database.")
    parser.add_argument("--database", type=Path, default=V1_ROOT / "data" / "gemuworld.sqlite3")
    parser.add_argument("--include-import-errors", action="store_true")
    args = parser.parse_args()
    connection = connect(args.database)
    try:
        migrate(connection)
        failures = {}
        effect_columns = {row["name"] for row in connection.execute("PRAGMA table_info(effects)")}
        if "profession" in effect_columns or "role" in effect_columns:
            failures["effect_profession_schema"] = sorted(effect_columns)
        for name, sql in CHECKS.items():
            rows = [dict(row) for row in connection.execute(sql)]
            if rows:
                failures[name] = rows
        if args.include_import_errors:
            rows = [dict(row) for row in connection.execute("SELECT * FROM import_issues WHERE severity='error'")]
            if rows:
                failures["import_errors"] = rows
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("monster_cards", "prophecy_cards", "effects", "effect_professions", "decks", "deck_cards", "design_guides", "monster_stat_benchmarks")
        }
    finally:
        connection.close()
    print(json.dumps({"valid": not failures, "counts": counts, "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
