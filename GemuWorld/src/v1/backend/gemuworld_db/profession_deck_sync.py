from __future__ import annotations

import json
import sqlite3

from .decks import _legacy_markdown


PROFESSION_DECK_CODES = {
    "刺客": ("⚔️assassin", "assassin"),
    "坦克": ("🛡️tank", "tank"),
    "射手": ("🏹shooter", "shooter"),
    "法师": ("🪄magician", "magician"),
    "辅助": ("🧠strategy", "strategy"),
}


class ProfessionDeckSyncError(ValueError):
    pass


def _target_decks(connection: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    rows = list(connection.execute("SELECT id,code FROM decks WHERE status='active' AND deck_type='role'"))
    targets: dict[str, sqlite3.Row] = {}
    for profession, aliases in PROFESSION_DECK_CODES.items():
        matches = [row for row in rows if any(row["code"].casefold() == alias.casefold() for alias in aliases)]
        if len(matches) != 1:
            raise ProfessionDeckSyncError(f"expected exactly one active {profession} deck ({' / '.join(aliases)}), found {len(matches)}")
        targets[profession] = matches[0]
    return targets


def _card_professions(connection: sqlite3.Connection) -> dict[tuple[str, int], set[str]]:
    professions: dict[tuple[str, int], set[str]] = {}
    for row in connection.execute(
        "SELECT e.monster_card_id,e.prophecy_card_id,p.profession "
        "FROM effects e JOIN effect_professions p ON p.effect_id=e.id "
        "WHERE e.monster_card_id IS NOT NULL OR e.prophecy_card_id IS NOT NULL"
    ):
        card_type = "monster" if row["monster_card_id"] is not None else "prophecy"
        owner_id = row[f"{card_type}_card_id"]
        professions.setdefault((card_type, owner_id), set()).add(row["profession"])
    for row in connection.execute("SELECT id,level,attack,defence FROM monster_cards WHERE status='active'"):
        key = ("monster", row["id"])
        threshold = (max(0, row["level"] or 0) + 1) * 5
        if (row["attack"] or 0) > threshold:
            professions.setdefault(key, set()).add("刺客")
        if (row["defence"] or 0) > threshold:
            professions.setdefault(key, set()).add("坦克")
    return professions


def _active_cards(connection: sqlite3.Connection) -> dict[tuple[str, int], dict[str, object]]:
    cards: dict[tuple[str, int], dict[str, object]] = {}
    for card_type in ("monster", "prophecy"):
        table = f"{card_type}_cards"
        translation_table = f"{card_type}_card_translations"
        owner_column = f"{card_type}_card_id"
        title_column = "title"
        for row in connection.execute(
            f"SELECT c.id,c.card_id,COALESCE(t.{title_column},c.card_id) title FROM {table} c "
            f"LEFT JOIN {translation_table} t ON t.{owner_column}=c.id AND t.language='zh' "
            "WHERE c.status='active' ORDER BY c.id"
        ):
            cards[(card_type, row["id"])] = {"card_type": card_type, "card_id": row["id"], "stable_id": row["card_id"], "title": row["title"]}
    return cards


def sync_profession_decks(connection: sqlite3.Connection, *, dry_run: bool = False) -> dict[str, object]:
    targets = _target_decks(connection)
    professions = _card_professions(connection)
    cards = _active_cards(connection)
    result: dict[str, object] = {"dry_run": dry_run, "decks": [], "total_added": 0}
    connection.execute("BEGIN IMMEDIATE")
    try:
        for profession, deck in targets.items():
            existing_rows = list(connection.execute("SELECT monster_card_id,prophecy_card_id,position FROM deck_cards WHERE deck_id=? ORDER BY position", (deck["id"],)))
            existing = {
                ("monster", row["monster_card_id"]) if row["monster_card_id"] is not None else ("prophecy", row["prophecy_card_id"])
                for row in existing_rows
            }
            qualifying = [key for key in cards if profession in professions.get(key, set()) and key not in existing]
            qualifying.sort(key=lambda key: (0 if key[0] == "monster" else 1, key[1]))
            position = max((row["position"] for row in existing_rows), default=-1) + 1
            added = []
            for key in qualifying:
                card = cards[key]
                owner_column = f"{key[0]}_card_id"
                connection.execute(f"INSERT INTO deck_cards(deck_id,{owner_column},position) VALUES (?,?,?)", (deck["id"], key[1], position))
                position += 1
                added.append(card)
            if added:
                description_row = connection.execute("SELECT description FROM deck_translations WHERE deck_id=? AND language='zh'", (deck["id"],)).fetchone()
                markdown = _legacy_markdown(connection, deck["id"], description_row["description"] if description_row else "")
                connection.execute("UPDATE decks SET source_markdown_zh=?,updated_at=CURRENT_TIMESTAMP,version=version+1 WHERE id=?", (markdown, deck["id"]))
                connection.execute(
                    "INSERT INTO change_log(entity_type,entity_id,action,details_json) VALUES ('deck',?,'sync_profession_members',?)",
                    (deck["id"], json.dumps({"profession": profession, "added": [{"card_type": card["card_type"], "card_id": card["stable_id"]} for card in added]}, ensure_ascii=False)),
                )
            deck_result = {"profession": profession, "deck_code": deck["code"], "existing_count": len(existing_rows), "added_count": len(added), "added": added}
            result["decks"].append(deck_result)
            result["total_added"] += len(added)
        if dry_run:
            connection.rollback()
        else:
            connection.commit()
    except Exception:
        connection.rollback()
        raise
    return result
