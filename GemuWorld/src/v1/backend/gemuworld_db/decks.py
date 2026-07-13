from __future__ import annotations

import json
import sqlite3

from .cards import VersionConflict


class DeckWriteError(ValueError):
    pass


DECK_TYPES = {"default", "role", "tutorial", "temporary"}


def get_deck(connection: sqlite3.Connection, deck_id: int) -> dict[str, object]:
    deck = connection.execute("SELECT * FROM decks WHERE id=?", (deck_id,)).fetchone()
    if not deck:
        raise DeckWriteError("deck not found")
    translations = {row["language"]: {"name": row["name"], "summary": row["summary"], "description": row["description"]} for row in connection.execute("SELECT * FROM deck_translations WHERE deck_id=?", (deck_id,))}
    members = []
    rows = connection.execute(
        "SELECT dc.*,mc.card_id AS monster_code,mt.title AS monster_title,pc.card_id AS prophecy_code,pt.title AS prophecy_title "
        "FROM deck_cards dc "
        "LEFT JOIN monster_cards mc ON mc.id=dc.monster_card_id "
        "LEFT JOIN monster_card_translations mt ON mt.monster_card_id=mc.id AND mt.language='zh' "
        "LEFT JOIN prophecy_cards pc ON pc.id=dc.prophecy_card_id "
        "LEFT JOIN prophecy_card_translations pt ON pt.prophecy_card_id=pc.id AND pt.language='zh' "
        "WHERE dc.deck_id=? ORDER BY dc.position",
        (deck_id,),
    )
    for row in rows:
        card_type = "monster" if row["monster_card_id"] is not None else "prophecy"
        members.append({"card_type": card_type, "card_id": row[f"{card_type}_card_id"], "card_code": row[f"{card_type}_code"], "title": row[f"{card_type}_title"], "position": row["position"], "section": row["section"], "quantity": row["quantity"]})
    return {"id": deck["id"], "code": deck["code"], "deck_type": deck["deck_type"], "display_order": deck["display_order"], "status": deck["status"], "version": deck["version"], "translations": translations, "members": members, "source_filename": deck["source_filename"], "source_markdown_zh": deck["source_markdown_zh"], "created_at": deck["created_at"], "updated_at": deck["updated_at"]}


def _sync_translations(connection: sqlite3.Connection, deck_id: int, translations: object, code: str) -> None:
    if not isinstance(translations, dict):
        raise DeckWriteError("translations must be an object")
    for language in ("zh", "en"):
        value = translations.get(language)
        name = str(value.get("name", "")).strip() if isinstance(value, dict) else ""
        if language == "en" and not name:
            connection.execute("DELETE FROM deck_translations WHERE deck_id=? AND language='en'", (deck_id,))
            continue
        if language == "zh" and not name:
            name = code
        connection.execute("INSERT INTO deck_translations(deck_id,language,name,summary,description) VALUES (?,?,?,?,?) ON CONFLICT(deck_id,language) DO UPDATE SET name=excluded.name,summary=excluded.summary,description=excluded.description", (deck_id, language, name, str(value.get("summary", "")) if isinstance(value, dict) else "", str(value.get("description", "")) if isinstance(value, dict) else ""))


def _sync_members(connection: sqlite3.Connection, deck_id: int, members: object) -> list[dict[str, object]]:
    if not isinstance(members, list):
        raise DeckWriteError("members must be an array")
    normalized = []
    seen = set()
    for index, member in enumerate(members):
        if not isinstance(member, dict):
            raise DeckWriteError(f"member {index + 1} must be an object")
        card_type = str(member.get("card_type", ""))
        if card_type not in {"monster", "prophecy"}:
            raise DeckWriteError(f"invalid member card type: {card_type}")
        card_id = int(member.get("card_id", 0))
        key = (card_type, card_id)
        if key in seen:
            raise DeckWriteError(f"duplicate deck member: {card_type} {card_id}")
        seen.add(key)
        table = f"{card_type}_cards"
        card = connection.execute(f"SELECT id FROM {table} WHERE id=? AND status='active'", (card_id,)).fetchone()
        if not card:
            raise DeckWriteError(f"active {card_type} card {card_id} not found")
        normalized.append({"card_type": card_type, "card_id": card_id, "position": index, "section": str(member.get("section", "")), "quantity": max(1, int(member.get("quantity", 1)))})
    connection.execute("DELETE FROM deck_cards WHERE deck_id=?", (deck_id,))
    for member in normalized:
        owner_column = f"{member['card_type']}_card_id"
        connection.execute(f"INSERT INTO deck_cards(deck_id,{owner_column},position,section,quantity) VALUES (?,?,?,?,?)", (deck_id, member["card_id"], member["position"], member["section"], member["quantity"]))
    return normalized


def _legacy_markdown(connection: sqlite3.Connection, deck_id: int, description: str) -> str:
    lines = [description.rstrip()] if description.strip() else []
    section = None
    rows = connection.execute(
        "SELECT dc.section,COALESCE(mt.title,pt.title) title FROM deck_cards dc "
        "LEFT JOIN monster_card_translations mt ON mt.monster_card_id=dc.monster_card_id AND mt.language='zh' "
        "LEFT JOIN prophecy_card_translations pt ON pt.prophecy_card_id=dc.prophecy_card_id AND pt.language='zh' "
        "WHERE dc.deck_id=? ORDER BY dc.position",
        (deck_id,),
    )
    for row in rows:
        if row["section"] != section:
            section = row["section"]
            if section:
                lines.extend(["", f"// {section}"])
        lines.append(row["title"])
    return "\n".join(lines).strip() + "\n"


def save_deck(connection: sqlite3.Connection, payload: dict[str, object], deck_id: int | None = None) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise DeckWriteError("request body must be an object")
    code = str(payload.get("code", "")).strip()
    if not code:
        raise DeckWriteError("deck code is required")
    deck_type = str(payload.get("deck_type", "default"))
    if deck_type not in DECK_TYPES:
        raise DeckWriteError("invalid deck type")
    connection.execute("BEGIN IMMEDIATE")
    try:
        if deck_id is None:
            if connection.execute("SELECT 1 FROM decks WHERE code=?", (code,)).fetchone():
                raise DeckWriteError("deck code already exists")
            display_order = int(payload.get("display_order", connection.execute("SELECT COALESCE(MAX(display_order),-1)+1 FROM decks").fetchone()[0]))
            deck_id = connection.execute("INSERT INTO decks(code,deck_type,display_order,source_filename) VALUES (?,?,?,?)", (code, deck_type, display_order, f"{code}.md")).lastrowid
            action = "create"
        else:
            current = connection.execute("SELECT * FROM decks WHERE id=?", (deck_id,)).fetchone()
            if not current:
                raise DeckWriteError("deck not found")
            if int(payload.get("version", 0)) != current["version"]:
                raise VersionConflict("deck changed since it was opened")
            duplicate = connection.execute("SELECT 1 FROM decks WHERE code=? AND id<>?", (code, deck_id)).fetchone()
            if duplicate:
                raise DeckWriteError("deck code already exists")
            connection.execute("UPDATE decks SET code=?,deck_type=?,display_order=?,updated_at=CURRENT_TIMESTAMP,version=version+1 WHERE id=?", (code, deck_type, int(payload.get("display_order", current["display_order"])), deck_id))
            action = "update"
        _sync_translations(connection, deck_id, payload.get("translations", {}), code)
        _sync_members(connection, deck_id, payload.get("members", []))
        zh = payload.get("translations", {}).get("zh", {})
        markdown = _legacy_markdown(connection, deck_id, str(zh.get("description", "")) if isinstance(zh, dict) else "")
        connection.execute("UPDATE decks SET source_filename=?,source_markdown_zh=? WHERE id=?", (f"{code}.md", markdown, deck_id))
        connection.execute("INSERT INTO change_log(entity_type,entity_id,action,details_json) VALUES ('deck',?,?,?)", (deck_id, action, json.dumps({"code": code}, ensure_ascii=False)))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return get_deck(connection, deck_id)


def delete_deck(connection: sqlite3.Connection, deck_id: int, *, permanent: bool, version: int) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        deck = connection.execute("SELECT version FROM decks WHERE id=?", (deck_id,)).fetchone()
        if not deck:
            raise DeckWriteError("deck not found")
        if version != deck["version"]:
            raise VersionConflict("deck changed since it was opened")
        if permanent:
            connection.execute("DELETE FROM decks WHERE id=?", (deck_id,))
            action = "delete"
        else:
            connection.execute("UPDATE decks SET status='archived',version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=?", (deck_id,))
            action = "archive"
        connection.execute("INSERT INTO change_log(entity_type,entity_id,action) VALUES ('deck',?,?)", (deck_id, action))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
