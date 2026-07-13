from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime


class CardWriteError(ValueError):
    pass


class VersionConflict(CardWriteError):
    pass


ALLOWED_EFFECTS = {
    "monster": {"monster_skill", "monster_attribute", "monster_reactive_attribute"},
    "prophecy": {"prophecy_effect", "prophecy_reactive_effect"},
}


def get_effect_professions(connection: sqlite3.Connection, effect_id: int) -> list[str]:
    return [row["profession"] for row in connection.execute("SELECT profession FROM effect_professions WHERE effect_id=? ORDER BY position", (effect_id,))]


def sync_effect_professions(connection: sqlite3.Connection, effect_id: int, values: object) -> None:
    if not isinstance(values, list):
        raise CardWriteError("effect professions must be an array")
    professions = [str(value).strip() for value in values]
    if any(not value for value in professions) or len(professions) != len(set(professions)):
        raise CardWriteError("effect professions must be unique non-empty strings")
    connection.execute("DELETE FROM effect_professions WHERE effect_id=?", (effect_id,))
    for position, profession in enumerate(professions):
        connection.execute("INSERT INTO effect_professions(effect_id,profession,position) VALUES (?,?,?)", (effect_id, profession, position))


def effect_marker(value: object) -> str:
    marker = str(value or "").strip()
    if len(marker) > 10:
        raise CardWriteError("effect marker must be at most 10 characters")
    return marker


def _names(card_type: str) -> tuple[str, str, str]:
    if card_type not in {"monster", "prophecy"}:
        raise CardWriteError("card type must be monster or prophecy")
    return f"{card_type}_cards", f"{card_type}_card_translations", f"{card_type}_card_id"


def _generated_id(card_type: str) -> str:
    prefix = "m" if card_type == "monster" else "p"
    return f"{datetime.now():%Y%m%d}-web-{prefix}{uuid.uuid4().hex[:8]}"


def get_card(connection: sqlite3.Connection, card_type: str, owner_id: int) -> dict[str, object]:
    card_table, translation_table, owner_column = _names(card_type)
    card = connection.execute(f"SELECT * FROM {card_table} WHERE id=?", (owner_id,)).fetchone()
    if not card:
        raise CardWriteError("card not found")
    translations = {}
    for row in connection.execute(f"SELECT * FROM {translation_table} WHERE {owner_column}=?", (owner_id,)):
        if card_type == "monster":
            translations[row["language"]] = {"title": row["title"], "monster_type": row["monster_type"], "description": row["description"]}
        else:
            translations[row["language"]] = {"title": row["title"], "introduction": row["introduction"]}
    effects = []
    for effect in connection.execute(f"SELECT * FROM effects WHERE {owner_column}=? ORDER BY effect_type,position,id", (owner_id,)):
        effect_translations = {row["language"]: {"name": row["name"], "text": row["text"]} for row in connection.execute("SELECT * FROM effect_translations WHERE effect_id=?", (effect["id"],))}
        effects.append({"id": effect["id"], "type": effect["effect_type"], "position": effect["position"], "energy_cost": effect["energy_cost"], "professions": get_effect_professions(connection, effect["id"]), "valuation": effect["valuation"], "marker": effect["marker"], "notes": effect["notes"], "version": effect["version"], "translations": effect_translations})
    decks = [dict(row) for row in connection.execute(
        f"SELECT d.id,d.code,d.deck_type,dc.position,dc.section FROM deck_cards dc JOIN decks d ON d.id=dc.deck_id WHERE dc.{owner_column}=? ORDER BY d.display_order,dc.position",
        (owner_id,),
    )]
    base = {key: card[key] for key in card.keys() if key not in {"created_at", "updated_at"}}
    return {"type": card_type, "base": base, "translations": translations, "effects": effects, "decks": decks, "created_at": card["created_at"], "updated_at": card["updated_at"]}


def _validate_title(connection: sqlite3.Connection, card_type: str, owner_id: int | None, title: str, old_title: str | None) -> None:
    _, translation_table, owner_column = _names(card_type)
    if not title.strip():
        raise CardWriteError("Chinese title is required")
    if owner_id is not None and title == old_title:
        return
    row = connection.execute(f"SELECT {owner_column} FROM {translation_table} WHERE language='zh' AND title=? LIMIT 1", (title,)).fetchone()
    if row:
        raise CardWriteError(f"Chinese title {title!r} already exists")


def _sync_translations(connection: sqlite3.Connection, card_type: str, owner_id: int, translations: dict[str, object], timestamp: str) -> None:
    _, table, owner_column = _names(card_type)
    for language in ("zh", "en"):
        value = translations.get(language)
        title = str(value.get("title", "")).strip() if isinstance(value, dict) else ""
        if language == "en" and not title:
            connection.execute(f"DELETE FROM {table} WHERE {owner_column}=? AND language='en'", (owner_id,))
            continue
        if not title:
            raise CardWriteError("Chinese title is required")
        if card_type == "monster":
            connection.execute(f"INSERT INTO {table}({owner_column},language,title,monster_type,description,source_updated_at) VALUES (?,?,?,?,?,?) ON CONFLICT({owner_column},language) DO UPDATE SET title=excluded.title,monster_type=excluded.monster_type,description=excluded.description,source_updated_at=excluded.source_updated_at", (owner_id, language, title, str(value.get("monster_type", "")), str(value.get("description", "")), timestamp))
        else:
            connection.execute(f"INSERT INTO {table}({owner_column},language,title,introduction,source_updated_at) VALUES (?,?,?,?,?) ON CONFLICT({owner_column},language) DO UPDATE SET title=excluded.title,introduction=excluded.introduction,source_updated_at=excluded.source_updated_at", (owner_id, language, title, str(value.get("introduction", "")), timestamp))


def reorder_monster_skills(connection: sqlite3.Connection, owner_id: int) -> None:
    rows = list(connection.execute(
        "SELECT e.id,e.energy_cost,COALESCE(t.text,'') AS zh_text "
        "FROM effects e LEFT JOIN effect_translations t ON t.effect_id=e.id AND t.language='zh' "
        "WHERE e.monster_card_id=? AND e.effect_type='monster_skill'",
        (owner_id,),
    ))
    rows.sort(key=lambda row: (float(row["energy_cost"] or 0), str(row["zh_text"]).casefold(), row["id"]))
    if not rows:
        return
    connection.execute("UPDATE effects SET position=position+100000 WHERE monster_card_id=? AND effect_type='monster_skill'", (owner_id,))
    for position, row in enumerate(rows):
        connection.execute("UPDATE effects SET position=? WHERE id=?", (position, row["id"]))


def _sync_effects(connection: sqlite3.Connection, card_type: str, owner_id: int, effects: object) -> None:
    if not isinstance(effects, list):
        raise CardWriteError("effects must be an array")
    owner_column = f"{card_type}_card_id"
    existing = {row["id"]: row for row in connection.execute(f"SELECT * FROM effects WHERE {owner_column}=?", (owner_id,))}
    # Free unique (owner,type,position) slots before arbitrary reordering.
    if existing:
        connection.execute(f"UPDATE effects SET position=position+100000 WHERE {owner_column}=?", (owner_id,))
    retained = set()
    slots = set()
    for index, value in enumerate(effects):
        if not isinstance(value, dict):
            raise CardWriteError(f"effect {index + 1} must be an object")
        effect_type = str(value.get("type", ""))
        if effect_type not in ALLOWED_EFFECTS[card_type]:
            raise CardWriteError(f"invalid {card_type} effect type: {effect_type}")
        position = int(value.get("position", index))
        slot = (effect_type, position)
        if slot in slots:
            raise CardWriteError(f"duplicate effect slot: {effect_type} #{position}")
        slots.add(slot)
        effect_id = value.get("id")
        if effect_id is not None:
            effect_id = int(effect_id)
            if effect_id not in existing:
                raise CardWriteError(f"effect {effect_id} does not belong to this card")
            if int(value.get("version", 0)) != existing[effect_id]["version"]:
                raise VersionConflict(f"effect {effect_id} changed since the card was opened")
            connection.execute("UPDATE effects SET effect_type=?,position=?,energy_cost=?,valuation=?,marker=?,notes=?,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=?", (effect_type, position, value.get("energy_cost"), value.get("valuation"), effect_marker(value.get("marker")), str(value.get("notes", "")), effect_id))
        else:
            effect_id = connection.execute(f"INSERT INTO effects({owner_column},effect_type,position,energy_cost,valuation,marker,notes) VALUES (?,?,?,?,?,?,?)", (owner_id, effect_type, position, value.get("energy_cost"), value.get("valuation"), effect_marker(value.get("marker")), str(value.get("notes", "")))).lastrowid
        sync_effect_professions(connection, effect_id, value.get("professions", []))
        retained.add(effect_id)
        effect_translations = value.get("translations", {})
        if not isinstance(effect_translations, dict):
            raise CardWriteError("effect translations must be an object")
        for language in ("zh", "en"):
            translated = effect_translations.get(language)
            if not isinstance(translated, dict) or (language == "en" and not translated.get("name") and not translated.get("text")):
                if language == "en":
                    connection.execute("DELETE FROM effect_translations WHERE effect_id=? AND language='en'", (effect_id,))
                continue
            connection.execute("INSERT INTO effect_translations(effect_id,language,name,text) VALUES (?,?,?,?) ON CONFLICT(effect_id,language) DO UPDATE SET name=excluded.name,text=excluded.text", (effect_id, language, str(translated.get("name", "")), str(translated.get("text", ""))))
    for effect_id in set(existing) - retained:
        connection.execute("DELETE FROM effects WHERE id=?", (effect_id,))
    if card_type == "monster":
        reorder_monster_skills(connection, owner_id)


def _sync_decks(connection: sqlite3.Connection, card_type: str, owner_id: int, deck_codes: object) -> None:
    if not isinstance(deck_codes, list) or any(not isinstance(code, str) for code in deck_codes):
        raise CardWriteError("deck_codes must be an array of strings")
    if len(deck_codes) != len(set(deck_codes)):
        raise CardWriteError("deck_codes contains duplicates")
    owner_column = f"{card_type}_card_id"
    decks = {row["code"]: row for row in connection.execute("SELECT id,code FROM decks WHERE status='active'")}
    missing = [code for code in deck_codes if code not in decks]
    if missing:
        raise CardWriteError(f"unknown decks: {', '.join(missing)}")
    existing = {row["deck_id"]: row for row in connection.execute(f"SELECT * FROM deck_cards WHERE {owner_column}=?", (owner_id,))}
    selected_ids = {decks[code]["id"] for code in deck_codes}
    for deck_id in set(existing) - selected_ids:
        connection.execute(f"DELETE FROM deck_cards WHERE deck_id=? AND {owner_column}=?", (deck_id, owner_id))
    for code in deck_codes:
        deck_id = decks[code]["id"]
        if deck_id in existing:
            continue
        position = connection.execute("SELECT COALESCE(MAX(position),-1)+1 FROM deck_cards WHERE deck_id=?", (deck_id,)).fetchone()[0]
        connection.execute(f"INSERT INTO deck_cards(deck_id,{owner_column},position) VALUES (?,?,?)", (deck_id, owner_id, position))


def save_card(connection: sqlite3.Connection, card_type: str, payload: dict[str, object], owner_id: int | None = None) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise CardWriteError("request body must be an object")
    card_table, translation_table, owner_column = _names(card_type)
    translations = payload.get("translations", {})
    if not isinstance(translations, dict) or not isinstance(translations.get("zh"), dict):
        raise CardWriteError("Chinese translation is required")
    title = str(translations["zh"].get("title", "")).strip()
    base = payload.get("base", {})
    if not isinstance(base, dict):
        raise CardWriteError("base must be an object")
    connection.execute("BEGIN IMMEDIATE")
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        old_title = None
        if owner_id is not None:
            current = connection.execute(f"SELECT c.version,t.title FROM {card_table} c JOIN {translation_table} t ON t.{owner_column}=c.id AND t.language='zh' WHERE c.id=?", (owner_id,)).fetchone()
            if not current:
                raise CardWriteError("card not found")
            expected_version = int(payload.get("version", 0))
            if expected_version != current["version"]:
                raise VersionConflict(f"card changed since it was opened (expected version {expected_version}, current {current['version']})")
            old_title = current["title"]
        _validate_title(connection, card_type, owner_id, title, old_title)
        if owner_id is None:
            card_id = str(base.get("card_id", "")).strip() or _generated_id(card_type)
            for table in ("monster_cards", "prophecy_cards"):
                if connection.execute(f"SELECT 1 FROM {table} WHERE card_id=?", (card_id,)).fetchone():
                    raise CardWriteError("card_id already exists")
            if card_type == "monster":
                owner_id = connection.execute("INSERT INTO monster_cards(card_id,level,monster_type,attack,defence,magic,image_path,source_updated_at) VALUES (?,?,?,?,?,?,?,?)", (card_id, int(base.get("level", 0)), str(base.get("monster_type", "")), float(base.get("attack", 0)), float(base.get("defence", 0)), float(base.get("magic", 0)), str(base.get("image", "")), timestamp)).lastrowid
            else:
                owner_id = connection.execute("INSERT INTO prophecy_cards(card_id,image_path,source_updated_at) VALUES (?,?,?)", (card_id, str(base.get("image", "")), timestamp)).lastrowid
            action = "create"
        else:
            if card_type == "monster":
                connection.execute("UPDATE monster_cards SET level=?,monster_type=?,attack=?,defence=?,magic=?,image_path=?,source_updated_at=?,updated_at=CURRENT_TIMESTAMP,version=version+1 WHERE id=?", (int(base.get("level", 0)), str(base.get("monster_type", "")), float(base.get("attack", 0)), float(base.get("defence", 0)), float(base.get("magic", 0)), str(base.get("image", "")), timestamp, owner_id))
            else:
                connection.execute("UPDATE prophecy_cards SET image_path=?,source_updated_at=?,updated_at=CURRENT_TIMESTAMP,version=version+1 WHERE id=?", (str(base.get("image", "")), timestamp, owner_id))
            action = "update"
        _sync_translations(connection, card_type, owner_id, translations, timestamp)
        _sync_effects(connection, card_type, owner_id, payload.get("effects", []))
        _sync_decks(connection, card_type, owner_id, payload.get("deck_codes", []))
        connection.execute("INSERT INTO change_log(entity_type,entity_id,action,details_json) VALUES (?,?,?,?)", (f"{card_type}_card", owner_id, action, json.dumps({"title": title}, ensure_ascii=False)))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return get_card(connection, card_type, owner_id)


def delete_card(connection: sqlite3.Connection, card_type: str, owner_id: int, *, permanent: bool, version: int) -> None:
    card_table, _, _ = _names(card_type)
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute(f"SELECT version FROM {card_table} WHERE id=?", (owner_id,)).fetchone()
        if not row:
            raise CardWriteError("card not found")
        if version != row["version"]:
            raise VersionConflict("card changed since it was opened")
        if permanent:
            connection.execute(f"DELETE FROM {card_table} WHERE id=?", (owner_id,))
            action = "delete"
        else:
            connection.execute(f"UPDATE {card_table} SET status='archived',version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=?", (owner_id,))
            action = "archive"
        connection.execute("INSERT INTO change_log(entity_type,entity_id,action) VALUES (?,?,?)", (f"{card_type}_card", owner_id, action))
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def copy_card(connection: sqlite3.Connection, card_type: str, owner_id: int) -> dict[str, object]:
    source = get_card(connection, card_type, owner_id)
    payload = {"base": dict(source["base"]), "translations": json.loads(json.dumps(source["translations"], ensure_ascii=False)), "effects": [], "deck_codes": [deck["code"] for deck in source["decks"]]}
    payload["base"].pop("id", None)
    payload["base"].pop("version", None)
    payload["base"]["card_id"] = ""
    payload["base"]["image"] = payload["base"].pop("image_path", "")
    base_title = payload["translations"]["zh"]["title"] + "副本"
    candidate = base_title
    number = 2
    _, translation_table, owner_column = _names(card_type)
    while connection.execute(f"SELECT 1 FROM {translation_table} WHERE language='zh' AND title=?", (candidate,)).fetchone():
        candidate = f"{base_title}{number}"
        number += 1
    payload["translations"]["zh"]["title"] = candidate
    if payload["translations"].get("en", {}).get("title"):
        payload["translations"]["en"]["title"] += " Copy"
    for effect in source["effects"]:
        payload["effects"].append({key: value for key, value in effect.items() if key != "id"})
    return save_card(connection, card_type, payload)
