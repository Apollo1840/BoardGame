from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone


VERSION_PATTERN = re.compile(r"^v\d+(?:\.\d+)*$", re.IGNORECASE)


def _data_version(connection: sqlite3.Connection) -> str:
    row = connection.execute("SELECT value FROM app_settings WHERE key='data_version'").fetchone()
    value = str(row[0]).strip() if row else "v1"
    return value if VERSION_PATTERN.fullmatch(value) else "v1"


def _version_token(version: str) -> str:
    return "V" + "P".join(version.lower().removeprefix("v").split("."))


def _card_token(card_id: str) -> str:
    token = re.sub(r"[^A-Za-z0-9]", "", card_id).upper()
    if not token:
        raise ValueError("card_id must contain at least one ASCII letter or digit")
    return "C" + token


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _next_timestamp(previous: str = "") -> datetime:
    value = _utc_now()
    value = value.replace(microsecond=(value.microsecond // 1000) * 1000)
    prior = _parse_timestamp(previous)
    if prior is not None and value <= prior:
        value = prior + timedelta(milliseconds=1)
    return value


def _timestamp_values(value: datetime) -> tuple[str, str]:
    milliseconds = value.microsecond // 1000
    stored = value.replace(microsecond=milliseconds * 1000).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    token = value.strftime("%Y%m%dT%H%M%S") + f"{milliseconds:03d}Z"
    return stored, "U" + token


def build_serial_number(version: str, card_id: str, timestamp: datetime) -> str:
    _, timestamp_token = _timestamp_values(timestamp)
    return f"{_version_token(version)}-{_card_token(card_id)}-{timestamp_token}"


def refresh_card_serial(
    connection: sqlite3.Connection,
    card_type: str,
    owner_id: int,
    *,
    data_version: str | None = None,
) -> str:
    if card_type not in {"monster", "prophecy"}:
        raise ValueError("card type must be monster or prophecy")
    table = f"{card_type}_cards"
    row = connection.execute(
        f"SELECT card_id,serial_updated_at FROM {table} WHERE id=?",
        (owner_id,),
    ).fetchone()
    if not row:
        raise ValueError("card not found")
    timestamp = _next_timestamp(str(row["serial_updated_at"] or ""))
    stored_timestamp, _ = _timestamp_values(timestamp)
    serial_number = build_serial_number(data_version or _data_version(connection), str(row["card_id"]), timestamp)
    connection.execute(
        f"UPDATE {table} SET serial_number=?,serial_updated_at=? WHERE id=?",
        (serial_number, stored_timestamp, owner_id),
    )
    return serial_number


def refresh_all_card_serials(
    connection: sqlite3.Connection,
    *,
    data_version: str | None = None,
    active_only: bool = False,
) -> int:
    refreshed = 0
    condition = " WHERE status='active'" if active_only else ""
    for card_type in ("monster", "prophecy"):
        rows = list(connection.execute(f"SELECT id FROM {card_type}_cards{condition} ORDER BY id"))
        for row in rows:
            refresh_card_serial(connection, card_type, int(row["id"]), data_version=data_version)
            refreshed += 1
    return refreshed


def backfill_card_serials(connection: sqlite3.Connection) -> int:
    refreshed = 0
    for card_type in ("monster", "prophecy"):
        rows = list(connection.execute(
            f"SELECT id FROM {card_type}_cards WHERE serial_number='' OR serial_updated_at='' ORDER BY id"
        ))
        for row in rows:
            refresh_card_serial(connection, card_type, int(row["id"]))
            refreshed += 1
    if refreshed:
        connection.commit()
    return refreshed


def card_face_signature(connection: sqlite3.Connection, card_type: str, owner_id: int) -> str:
    if card_type not in {"monster", "prophecy"}:
        raise ValueError("card type must be monster or prophecy")
    card_table = f"{card_type}_cards"
    translation_table = f"{card_type}_card_translations"
    owner_column = f"{card_type}_card_id"
    base_fields = "card_id,image_path"
    if card_type == "monster":
        base_fields += ",level,monster_type,attack,defence,magic"
    card = connection.execute(f"SELECT {base_fields} FROM {card_table} WHERE id=?", (owner_id,)).fetchone()
    if not card:
        raise ValueError("card not found")
    translations = []
    translation_fields = "language,title,monster_type,description" if card_type == "monster" else "language,title,introduction"
    for row in connection.execute(
        f"SELECT {translation_fields} FROM {translation_table} WHERE {owner_column}=? ORDER BY language",
        (owner_id,),
    ):
        translations.append(dict(row))
    effects = []
    for effect in connection.execute(
        f"SELECT id,effect_type,position,energy_cost FROM effects WHERE {owner_column}=? ORDER BY effect_type,position,id",
        (owner_id,),
    ):
        effect_value = {
            "effect_type": effect["effect_type"],
            "position": effect["position"],
            "energy_cost": effect["energy_cost"],
        }
        effect_value["translations"] = [
            dict(row)
            for row in connection.execute(
                "SELECT language,name,text FROM effect_translations WHERE effect_id=? ORDER BY language",
                (effect["id"],),
            )
        ]
        effects.append(effect_value)
    return json.dumps(
        {"type": card_type, "base": dict(card), "translations": translations, "effects": effects},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
