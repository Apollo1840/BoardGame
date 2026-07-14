from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from .cards import ALLOWED_EFFECTS, CardWriteError, effect_energy_cost, effect_marker, effect_translation_name, sync_effect_professions, validate_monster_effect_counts
from .effects import EffectWriteError, get_effect


BACKUP_FORMAT = "gemuworld.effect-backup"
BACKUP_SCHEMA_VERSION = 1


def _backup_effect(effect: dict[str, object]) -> dict[str, object]:
    owner = effect["owner"]
    stable_owner = None if owner is None else {
        "card_type": owner["card_type"],
        "card_id": owner["card_id"],
        "title": owner["title"],
        "database_id": owner["id"],
    }
    return {
        "id": effect["id"],
        "type": effect["type"],
        "position": effect["position"],
        "energy_cost": effect["energy_cost"],
        "professions": effect["professions"],
        "valuation": effect["valuation"],
        "marker": effect["marker"],
        "notes": effect["notes"],
        "version": effect["version"],
        "owner": stable_owner,
        "translations": effect["translations"],
        "created_at": effect["created_at"],
        "updated_at": effect["updated_at"],
    }


def export_effect_backup(
    connection: sqlite3.Connection,
    effect_ids: object,
    output_dir: Path,
    filters: object = None,
) -> dict[str, object]:
    if not isinstance(effect_ids, list) or not effect_ids:
        raise EffectWriteError("effect_ids must be a non-empty array")
    try:
        ids = [int(value) for value in effect_ids]
    except (TypeError, ValueError) as error:
        raise EffectWriteError("effect_ids must contain integers") from error
    if len(ids) != len(set(ids)):
        raise EffectWriteError("effect_ids contains duplicates")
    if filters is not None and not isinstance(filters, dict):
        raise EffectWriteError("filters must be an object")

    items = [_backup_effect(get_effect(connection, effect_id)) for effect_id in ids]
    exported_at = datetime.now().astimezone().isoformat(timespec="seconds")
    backup = {
        "format": BACKUP_FORMAT,
        "schema_version": BACKUP_SCHEMA_VERSION,
        "exported_at": exported_at,
        "scope": "current_effect_list",
        "filters": filters or {},
        "count": len(items),
        "items": items,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"effects_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    destination = output_dir / filename
    temporary_name = ""
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=output_dir, prefix=".effects_", suffix=".tmp", delete=False) as temporary:
            temporary_name = temporary.name
            json.dump(backup, temporary, ensure_ascii=False, indent=2)
            temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, destination)
    finally:
        if temporary_name and Path(temporary_name).exists():
            Path(temporary_name).unlink()
    return {"filename": filename, "path": str(destination.resolve()), "count": len(items), "exported_at": exported_at}


def _resolve_owner(connection: sqlite3.Connection, owner: object, effect_type: str) -> tuple[int | None, int | None, tuple[str, int] | None]:
    if owner is None:
        return None, None, None
    if not isinstance(owner, dict):
        raise EffectWriteError("effect owner must be an object or null")
    card_type = str(owner.get("card_type", ""))
    card_id = str(owner.get("card_id", ""))
    if card_type not in ALLOWED_EFFECTS or effect_type not in ALLOWED_EFFECTS[card_type]:
        raise EffectWriteError(f"effect type {effect_type!r} is incompatible with backup owner")
    if not card_id:
        raise EffectWriteError("backup owner is missing stable card_id")
    row = connection.execute(f"SELECT id FROM {card_type}_cards WHERE card_id=?", (card_id,)).fetchone()
    if not row:
        raise EffectWriteError(f"backup owner card not found: {card_type} {card_id}")
    owner_id = int(row["id"])
    return (owner_id, None, (card_type, owner_id)) if card_type == "monster" else (None, owner_id, (card_type, owner_id))


def import_effect_backup(connection: sqlite3.Connection, backup: object) -> dict[str, object]:
    if not isinstance(backup, dict) or backup.get("format") != BACKUP_FORMAT or backup.get("schema_version") != BACKUP_SCHEMA_VERSION:
        raise EffectWriteError("unsupported effect backup format or schema version")
    items = backup.get("items")
    if not isinstance(items, list) or not items:
        raise EffectWriteError("effect backup contains no items")
    ids: list[int] = []
    for item in items:
        if not isinstance(item, dict):
            raise EffectWriteError("every backup effect must be an object")
        try:
            ids.append(int(item.get("id")))
        except (TypeError, ValueError) as error:
            raise EffectWriteError("every backup effect requires an integer id") from error
    if len(ids) != len(set(ids)):
        raise EffectWriteError("effect backup contains duplicate ids")

    created = 0
    updated = 0
    touched_cards: set[tuple[str, int]] = set()
    connection.execute("BEGIN IMMEDIATE")
    try:
        for effect_id, item in zip(ids, items, strict=True):
            effect_type = str(item.get("type", ""))
            if effect_type not in set().union(*ALLOWED_EFFECTS.values()):
                raise EffectWriteError(f"invalid effect type in backup: {effect_type!r}")
            position = int(item.get("position", 0))
            if position < 0:
                raise EffectWriteError("effect position must be non-negative")
            monster_id, prophecy_id, touched = _resolve_owner(connection, item.get("owner"), effect_type)
            if touched:
                touched_cards.add(touched)
            professions = item.get("professions", [])
            translations = item.get("translations")
            if not isinstance(translations, dict) or not isinstance(translations.get("zh"), dict):
                raise EffectWriteError(f"effect {effect_id} is missing its Chinese translation")
            try:
                marker = effect_marker(item.get("marker"))
            except CardWriteError as error:
                raise EffectWriteError(str(error)) from error
            existing = connection.execute("SELECT * FROM effects WHERE id=?", (effect_id,)).fetchone()
            if existing:
                if (existing["monster_card_id"], existing["prophecy_card_id"]) != (monster_id, prophecy_id):
                    raise EffectWriteError(f"effect {effect_id} already exists with a different owner")
                connection.execute(
                    "UPDATE effects SET effect_type=?,position=?,energy_cost=?,valuation=?,marker=?,notes=?,version=?,created_at=?,updated_at=? WHERE id=?",
                    (effect_type, position, effect_energy_cost(effect_type, item.get("energy_cost")), item.get("valuation"), marker, str(item.get("notes", "")), max(1, int(item.get("version", 1))), str(item.get("created_at", "")) or datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(item.get("updated_at", "")) or datetime.now().strftime("%Y-%m-%d %H:%M:%S"), effect_id),
                )
                updated += 1
            else:
                connection.execute(
                    "INSERT INTO effects(id,monster_card_id,prophecy_card_id,effect_type,position,energy_cost,valuation,marker,notes,version,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (effect_id, monster_id, prophecy_id, effect_type, position, effect_energy_cost(effect_type, item.get("energy_cost")), item.get("valuation"), marker, str(item.get("notes", "")), max(1, int(item.get("version", 1))), str(item.get("created_at", "")) or datetime.now().strftime("%Y-%m-%d %H:%M:%S"), str(item.get("updated_at", "")) or datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                )
                created += 1
            try:
                sync_effect_professions(connection, effect_id, professions)
            except CardWriteError as error:
                raise EffectWriteError(str(error)) from error
            connection.execute("DELETE FROM effect_translations WHERE effect_id=?", (effect_id,))
            for language, value in translations.items():
                if not str(language).strip() or not isinstance(value, dict):
                    raise EffectWriteError(f"effect {effect_id} has an invalid translation")
                connection.execute(
                    "INSERT INTO effect_translations(effect_id,language,name,text) VALUES (?,?,?,?)",
                    (effect_id, str(language), effect_translation_name(effect_type, value.get("name")), str(value.get("text", ""))),
                )
        for card_type, owner_id in touched_cards:
            if card_type == "monster":
                effect_types = [
                    str(row["effect_type"])
                    for row in connection.execute(
                        "SELECT effect_type FROM effects WHERE monster_card_id=?",
                        (owner_id,),
                    )
                ]
                try:
                    validate_monster_effect_counts(effect_types)
                except CardWriteError as error:
                    raise EffectWriteError(str(error)) from error
            connection.execute(f"UPDATE {card_type}_cards SET version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=?", (owner_id,))
        connection.execute(
            "INSERT INTO change_log(entity_type,entity_id,action,details_json) VALUES ('effect_backup',0,'import',?)",
            (json.dumps({"created": created, "updated": updated, "effect_ids": ids}, ensure_ascii=False),),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {"created": created, "updated": updated, "count": len(ids), "effect_ids": ids}
