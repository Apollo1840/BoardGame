from __future__ import annotations

import json
import re
import sqlite3

from .cards import ALLOWED_EFFECTS, CardWriteError, VersionConflict, effect_marker, get_effect_professions, reorder_monster_skills, sync_effect_professions


class EffectWriteError(ValueError):
    pass


def _row_to_effect(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, object]:
    owner_type = "monster" if row["monster_card_id"] is not None else "prophecy"
    owner_id = row[f"{owner_type}_card_id"]
    card_table = f"{owner_type}_cards"
    translation_table = f"{owner_type}_card_translations"
    owner_column = f"{owner_type}_card_id"
    card = connection.execute(f"SELECT c.card_id,t.title FROM {card_table} c JOIN {translation_table} t ON t.{owner_column}=c.id AND t.language='zh' WHERE c.id=?", (owner_id,)).fetchone()
    translations = {value["language"]: {"name": value["name"], "text": value["text"]} for value in connection.execute("SELECT * FROM effect_translations WHERE effect_id=?", (row["id"],))}
    return {"id": row["id"], "type": row["effect_type"], "position": row["position"], "energy_cost": row["energy_cost"], "professions": get_effect_professions(connection, row["id"]), "valuation": row["valuation"], "marker": row["marker"], "notes": row["notes"], "version": row["version"], "owner": {"card_type": owner_type, "id": owner_id, "card_id": card["card_id"], "title": card["title"]}, "translations": translations, "created_at": row["created_at"], "updated_at": row["updated_at"]}


def get_effect(connection: sqlite3.Connection, effect_id: int) -> dict[str, object]:
    row = connection.execute("SELECT * FROM effects WHERE id=?", (effect_id,)).fetchone()
    if not row:
        raise EffectWriteError("effect not found")
    effect = _row_to_effect(connection, row)
    normalized = _normalized(effect["translations"].get("zh", {}).get("text", ""))
    effect["duplicate_ids"] = [] if not normalized else [
        value["effect_id"]
        for value in connection.execute("SELECT effect_id,text FROM effect_translations WHERE language='zh' AND effect_id<>? ORDER BY effect_id", (effect_id,))
        if _normalized(value["text"]) == normalized
    ]
    return effect


def _normalized(text: str) -> str:
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE).casefold()


def list_professions(connection: sqlite3.Connection) -> list[str]:
    return [
        row["profession"]
        for row in connection.execute(
            "SELECT DISTINCT profession FROM effect_professions ORDER BY profession COLLATE NOCASE"
        )
    ]


def profession_counts(connection: sqlite3.Connection) -> dict[str, int]:
    counts = {
        row["profession"]: row["effect_count"]
        for row in connection.execute(
            "SELECT profession, COUNT(*) AS effect_count FROM effect_professions GROUP BY profession ORDER BY profession COLLATE NOCASE"
        )
    }
    counts["__unset__"] = connection.execute("SELECT COUNT(*) FROM effects e WHERE NOT EXISTS (SELECT 1 FROM effect_professions p WHERE p.effect_id=e.id)").fetchone()[0]
    return counts


def list_effects(connection: sqlite3.Connection, *, effect_type: str = "", keyword: str = "", card_type: str = "", profession: str | list[str] = "", sort_by: str = "id", direction: str = "asc") -> list[dict[str, object]]:
    if sort_by not in {"id", "owner", "type", "profession", "text", "text_length", "valuation"}:
        raise EffectWriteError("invalid effect sort field")
    if direction not in {"asc", "desc"}:
        raise EffectWriteError("effect sort direction must be asc or desc")
    rows = connection.execute("SELECT * FROM effects ORDER BY effect_type,id")
    all_effects = [_row_to_effect(connection, row) for row in rows]
    groups = {}
    for effect in all_effects:
        text = effect["translations"].get("zh", {}).get("text", "")
        normalized = _normalized(text)
        if normalized:
            groups.setdefault(normalized, []).append(effect["id"])
    effects = []
    stripped_keyword = keyword.strip()
    id_match = re.fullmatch(r"#?(\d+)", stripped_keyword)
    requested_id = int(id_match.group(1)) if id_match else None
    selected_professions = {profession} if isinstance(profession, str) and profession else set(profession)
    for effect in all_effects:
        if effect_type and effect["type"] != effect_type:
            continue
        if card_type and effect["owner"]["card_type"] != card_type:
            continue
        effect_professions = set(effect["professions"])
        if selected_professions and not (effect_professions & selected_professions or (not effect_professions and "__unset__" in selected_professions)):
            continue
        if requested_id is not None and effect["id"] != requested_id:
            continue
        haystack = json.dumps(effect, ensure_ascii=False).casefold()
        if requested_id is None and stripped_keyword and stripped_keyword.casefold() not in haystack:
            continue
        normalized = _normalized(effect["translations"].get("zh", {}).get("text", ""))
        effect["duplicate_ids"] = [value for value in groups.get(normalized, []) if value != effect["id"]]
        effects.append(effect)
    reverse = direction == "desc"
    if sort_by == "valuation":
        valued = [effect for effect in effects if effect["valuation"] is not None]
        missing = [effect for effect in effects if effect["valuation"] is None]
        effects = sorted(valued, key=lambda effect: (float(effect["valuation"]), effect["id"]), reverse=reverse) + missing
    else:
        key_functions = {
            "id": lambda effect: effect["id"],
            "owner": lambda effect: (str(effect["owner"]["title"]).casefold(), effect["id"]),
            "type": lambda effect: (str(effect["type"]), effect["id"]),
            "profession": lambda effect: (tuple(value.casefold() for value in effect["professions"]), effect["id"]),
            "text": lambda effect: (str(effect["translations"].get("zh", {}).get("text", "")).casefold(), effect["id"]),
            "text_length": lambda effect: (
                len(str(effect["translations"].get("zh", {}).get("text", "")).strip()),
                str(effect["translations"].get("zh", {}).get("text", "")).casefold(),
                effect["id"],
            ),
        }
        effects.sort(key=key_functions[sort_by], reverse=reverse)
    return effects


def update_effect(connection: sqlite3.Connection, effect_id: int, payload: dict[str, object]) -> dict[str, object]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute("SELECT * FROM effects WHERE id=?", (effect_id,)).fetchone()
        if not row:
            raise EffectWriteError("effect not found")
        if int(payload.get("version", 0)) != row["version"]:
            raise VersionConflict("effect changed since it was opened")
        owner_type = "monster" if row["monster_card_id"] is not None else "prophecy"
        effect_type = str(payload.get("type", row["effect_type"]))
        if effect_type not in ALLOWED_EFFECTS[owner_type]:
            raise EffectWriteError("effect type does not match owner card type")
        position = int(payload.get("position", row["position"]))
        owner_column = f"{owner_type}_card_id"
        conflict = connection.execute(f"SELECT 1 FROM effects WHERE {owner_column}=? AND effect_type=? AND position=? AND id<>?", (row[owner_column], effect_type, position, effect_id)).fetchone()
        if conflict:
            raise EffectWriteError("effect slot is already occupied")
        try:
            marker = effect_marker(payload.get("marker"))
            sync_effect_professions(connection, effect_id, payload.get("professions", []))
        except CardWriteError as error:
            raise EffectWriteError(str(error)) from error
        connection.execute("UPDATE effects SET effect_type=?,position=?,energy_cost=?,valuation=?,marker=?,notes=?,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=?", (effect_type, position, payload.get("energy_cost"), payload.get("valuation"), marker, str(payload.get("notes", "")), effect_id))
        connection.execute(f"UPDATE {owner_type}_cards SET version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=?", (row[f"{owner_type}_card_id"],))
        translations = payload.get("translations", {})
        if not isinstance(translations, dict):
            raise EffectWriteError("translations must be an object")
        for language in ("zh", "en"):
            value = translations.get(language)
            if language == "en" and (not isinstance(value, dict) or (not value.get("name") and not value.get("text"))):
                connection.execute("DELETE FROM effect_translations WHERE effect_id=? AND language='en'", (effect_id,))
                continue
            if not isinstance(value, dict):
                raise EffectWriteError("Chinese effect translation is required")
            connection.execute("INSERT INTO effect_translations(effect_id,language,name,text) VALUES (?,?,?,?) ON CONFLICT(effect_id,language) DO UPDATE SET name=excluded.name,text=excluded.text", (effect_id, language, str(value.get("name", "")), str(value.get("text", ""))))
        if owner_type == "monster":
            reorder_monster_skills(connection, row["monster_card_id"])
        connection.execute("INSERT INTO change_log(entity_type,entity_id,action,details_json) VALUES ('effect',?,'update',?)", (effect_id, json.dumps({"owner_type": owner_type, "type": effect_type}, ensure_ascii=False)))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return get_effect(connection, effect_id)


def copy_effect(connection: sqlite3.Connection, effect_id: int, target_type: str, target_id: int) -> dict[str, object]:
    source = get_effect(connection, effect_id)
    if target_type not in {"monster", "prophecy"} or source["type"] not in ALLOWED_EFFECTS[target_type]:
        raise EffectWriteError("effect type is incompatible with target card")
    card = connection.execute(f"SELECT id FROM {target_type}_cards WHERE id=? AND status='active'", (target_id,)).fetchone()
    if not card:
        raise EffectWriteError("target card not found")
    owner_column = f"{target_type}_card_id"
    position = connection.execute(f"SELECT COALESCE(MAX(position),-1)+1 FROM effects WHERE {owner_column}=? AND effect_type=?", (target_id, source["type"])).fetchone()[0]
    connection.execute("BEGIN IMMEDIATE")
    try:
        new_id = connection.execute(f"INSERT INTO effects({owner_column},effect_type,position,energy_cost,valuation,marker,notes) VALUES (?,?,?,?,?,?,?)", (target_id, source["type"], position, source["energy_cost"], source["valuation"], source["marker"], source["notes"])).lastrowid
        sync_effect_professions(connection, new_id, source["professions"])
        for language, value in source["translations"].items():
            connection.execute("INSERT INTO effect_translations(effect_id,language,name,text) VALUES (?,?,?,?)", (new_id, language, value["name"], value["text"]))
        if target_type == "monster":
            reorder_monster_skills(connection, target_id)
        connection.execute(f"UPDATE {target_type}_cards SET version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=?", (target_id,))
        connection.execute("INSERT INTO change_log(entity_type,entity_id,action,details_json) VALUES ('effect',?,'copy',?)", (new_id, json.dumps({"source_effect_id": effect_id, "target_type": target_type, "target_id": target_id})))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return get_effect(connection, new_id)
