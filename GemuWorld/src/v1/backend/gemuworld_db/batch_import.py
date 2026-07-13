from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from .legacy import MONSTER_HEADER, PROPHECY_HEADER
from .pipe_csv import parse_records


class BatchImportError(ValueError):
    pass


@dataclass
class BatchImportResult:
    card_type: str
    created: list[dict[str, str]] = field(default_factory=list)
    updated: list[dict[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dry_run: bool = False

    def as_dict(self) -> dict[str, object]:
        return {"card_type": self.card_type, "created": self.created, "updated": self.updated, "warnings": self.warnings, "created_count": len(self.created), "updated_count": len(self.updated), "dry_run": self.dry_run}


def _json(value: str, expected: type, context: str):
    try:
        parsed = json.loads(value or ("{}" if expected is dict else "[]"))
    except json.JSONDecodeError as exc:
        raise BatchImportError(f"{context}: invalid JSON: {exc}") from exc
    if not isinstance(parsed, expected):
        raise BatchImportError(f"{context}: expected a JSON {expected.__name__}")
    return parsed


def _float(value: str, context: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise BatchImportError(f"{context}: invalid number {value!r}") from exc


def _generated_card_id(card_type: str) -> str:
    prefix = "m" if card_type == "monster" else "p"
    return f"{datetime.now():%Y%m%d}-import-{prefix}{uuid.uuid4().hex[:8]}"


def _assert_headers(records_text: str, card_type: str) -> list[dict[str, str]]:
    expected = MONSTER_HEADER if card_type == "monster" else PROPHECY_HEADER
    first = records_text.lstrip("\ufeff").splitlines()[0] if records_text.strip() else ""
    actual = first.split("|")
    missing = [field for field in expected if field not in actual]
    if missing:
        raise BatchImportError(f"missing required columns: {', '.join(missing)}")
    return parse_records(records_text, f"{card_type}_cards.csv")


def _find_owner(connection: sqlite3.Connection, card_type: str, title: str, incoming_card_id: str) -> int | None:
    table = f"{card_type}_card_translations"
    owner = f"{card_type}_card_id"
    card_table = f"{card_type}_cards"
    rows = connection.execute(f"SELECT t.{owner},c.card_id FROM {table} t JOIN {card_table} c ON c.id=t.{owner} WHERE t.language='zh' AND t.title=?", (title,)).fetchall()
    if len(rows) > 1:
        matches = [row for row in rows if incoming_card_id and row["card_id"] == incoming_card_id]
        if len(matches) == 1:
            return matches[0][owner]
        raise BatchImportError(f"card title {title!r} is ambiguous ({len(rows)} Chinese cards); provide the matching existing card_id")
    return rows[0][0] if rows else None


def _assert_card_id_available(connection: sqlite3.Connection, card_id: str) -> None:
    for table in ("monster_cards", "prophecy_cards"):
        if connection.execute(f"SELECT 1 FROM {table} WHERE card_id=?", (card_id,)).fetchone():
            raise BatchImportError(f"card_id {card_id!r} already belongs to another card")


def _sync_effects(connection: sqlite3.Connection, card_type: str, owner_id: int, specs: list[dict[str, object]]) -> None:
    owner_column = f"{card_type}_card_id"
    existing = {(row["effect_type"], row["position"]): row for row in connection.execute(f"SELECT * FROM effects WHERE {owner_column}=?", (owner_id,))}
    retained: set[int] = set()
    for spec in specs:
        key = (str(spec["type"]), int(spec["position"]))
        row = existing.get(key)
        if row:
            effect_id = row["id"]
            connection.execute("UPDATE effects SET energy_cost=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (spec.get("energy_cost"), effect_id))
        else:
            effect_id = connection.execute(f"INSERT INTO effects({owner_column},effect_type,position,energy_cost) VALUES (?,?,?,?)", (owner_id, key[0], key[1], spec.get("energy_cost"))).lastrowid
        retained.add(effect_id)
        connection.execute("INSERT INTO effect_translations(effect_id,language,name,text) VALUES (?,?,?,?) ON CONFLICT(effect_id,language) DO UPDATE SET name=excluded.name,text=excluded.text", (effect_id, "zh", spec.get("name", ""), spec.get("text", "")))
    for row in existing.values():
        if row["id"] not in retained:
            connection.execute("DELETE FROM effects WHERE id=?", (row["id"],))


def _monster_specs(row: dict[str, str], context: str) -> list[dict[str, object]]:
    attributes = _json(row["attributes"], dict, context)
    skills = _json(row["skills"], list, context)
    specs = []
    if "normal_attribute" in attributes:
        specs.append({"type": "monster_attribute", "position": 0, "text": str(attributes["normal_attribute"])})
    if "responsive_attribute" in attributes:
        specs.append({"type": "monster_reactive_attribute", "position": 1, "text": str(attributes["responsive_attribute"])})
    for position, skill in enumerate(skills):
        if not isinstance(skill, dict):
            raise BatchImportError(f"{context}: skill {position + 1} must be an object")
        specs.append({"type": "monster_skill", "position": position, "name": str(skill.get("name", "")), "energy_cost": _float(str(skill.get("energy_cost", 0) or 0), context), "text": str(skill.get("effect", ""))})
    return specs


def _prophecy_specs(row: dict[str, str]) -> list[dict[str, object]]:
    specs = []
    if row["effect"]:
        specs.append({"type": "prophecy_effect", "position": 0, "text": row["effect"].replace("\\n", "\n")})
    if row["responsive_effect"]:
        specs.append({"type": "prophecy_reactive_effect", "position": 1, "text": row["responsive_effect"].replace("\\n", "\n")})
    return specs


def import_cards(connection: sqlite3.Connection, card_type: str, csv_text: str, *, dry_run: bool = False) -> BatchImportResult:
    if card_type not in {"monster", "prophecy"}:
        raise BatchImportError("card_type must be monster or prophecy")
    records = _assert_headers(csv_text, card_type)
    titles = [row["card_title"].replace("\\n", "\n").strip() for row in records]
    if any(not title for title in titles):
        raise BatchImportError("card_title cannot be empty")
    duplicates = sorted({title for title in titles if titles.count(title) > 1})
    for duplicate in duplicates:
        duplicate_ids = [row["card_id"].strip() for row, title in zip(records, titles, strict=True) if title == duplicate]
        if any(not card_id for card_id in duplicate_ids) or len(duplicate_ids) != len(set(duplicate_ids)):
            raise BatchImportError(f"duplicate title {duplicate!r} requires distinct existing card_id values")
    result = BatchImportResult(card_type=card_type, dry_run=dry_run)
    connection.execute("BEGIN IMMEDIATE")
    try:
        for row, title in zip(records, titles, strict=True):
            context = f"{card_type} {title!r}"
            incoming_id = row["card_id"].strip()
            owner_id = _find_owner(connection, card_type, title, incoming_id)
            timestamp = row["last_update_datetime"].strip() or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if owner_id is None:
                card_id = incoming_id or _generated_card_id(card_type)
                _assert_card_id_available(connection, card_id)
                if card_type == "monster":
                    owner_id = connection.execute("INSERT INTO monster_cards(card_id,level,monster_type,attack,defence,magic,image_path,source_updated_at) VALUES (?,?,?,?,?,?,?,?)", (card_id, int(_float(row["level"], context)), row["monster_type"], _float(row["attack"], context), _float(row["defence"], context), _float(row["magic"], context), row["image"], timestamp)).lastrowid
                    connection.execute("INSERT INTO monster_card_translations(monster_card_id,language,title,monster_type,description,source_updated_at) VALUES (?,?,?,?,?,?)", (owner_id, "zh", title, row["monster_type"], row["description"].replace("\\n", "\n"), timestamp))
                else:
                    owner_id = connection.execute("INSERT INTO prophecy_cards(card_id,image_path,source_updated_at) VALUES (?,?,?)", (card_id, row["image"], timestamp)).lastrowid
                    connection.execute("INSERT INTO prophecy_card_translations(prophecy_card_id,language,title,introduction,source_updated_at) VALUES (?,?,?,?,?)", (owner_id, "zh", title, row["introduction"].replace("\\n", "\n"), timestamp))
                result.created.append({"card_id": card_id, "title": title})
                action = "create"
            else:
                card_table = f"{card_type}_cards"
                stable_id = connection.execute(f"SELECT card_id FROM {card_table} WHERE id=?", (owner_id,)).fetchone()[0]
                if incoming_id and incoming_id != stable_id:
                    result.warnings.append(f"{title}: incoming card_id {incoming_id} ignored; preserved {stable_id}")
                if card_type == "monster":
                    connection.execute("UPDATE monster_cards SET level=?,monster_type=?,attack=?,defence=?,magic=?,image_path=?,source_updated_at=?,updated_at=CURRENT_TIMESTAMP,version=version+1 WHERE id=?", (int(_float(row["level"], context)), row["monster_type"], _float(row["attack"], context), _float(row["defence"], context), _float(row["magic"], context), row["image"], timestamp, owner_id))
                    connection.execute("UPDATE monster_card_translations SET title=?,monster_type=?,description=?,source_updated_at=? WHERE monster_card_id=? AND language='zh'", (title, row["monster_type"], row["description"].replace("\\n", "\n"), timestamp, owner_id))
                else:
                    connection.execute("UPDATE prophecy_cards SET image_path=?,source_updated_at=?,updated_at=CURRENT_TIMESTAMP,version=version+1 WHERE id=?", (row["image"], timestamp, owner_id))
                    connection.execute("UPDATE prophecy_card_translations SET title=?,introduction=?,source_updated_at=? WHERE prophecy_card_id=? AND language='zh'", (title, row["introduction"].replace("\\n", "\n"), timestamp, owner_id))
                result.updated.append({"card_id": stable_id, "title": title})
                action = "update"
            specs = _monster_specs(row, context) if card_type == "monster" else _prophecy_specs(row)
            _sync_effects(connection, card_type, owner_id, specs)
            connection.execute("INSERT INTO change_log(entity_type,entity_id,action,details_json) VALUES (?,?,?,?)", (f"{card_type}_card", owner_id, f"batch_import_{action}", json.dumps({"title": title}, ensure_ascii=False)))
        if dry_run:
            connection.rollback()
        else:
            connection.commit()
    except Exception:
        connection.rollback()
        raise
    return result
