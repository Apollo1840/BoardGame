from __future__ import annotations

import io
import json
import re
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from .legacy import MONSTER_HEADER, PROPHECY_HEADER
from .image_paths import legacy_image_path
from .pipe_csv import render_records
from .queries import list_cards


VERSION_PATTERN = re.compile(r"^v(\d+)(?:\.(\d+))*$")


def available_versions(data_root: Path) -> list[str]:
    versions = []
    if data_root.is_dir():
        for path in data_root.iterdir():
            if path.is_dir() and VERSION_PATTERN.fullmatch(path.name):
                versions.append(path.name)
    return sorted(versions, key=lambda value: tuple(int(part) for part in value[1:].split(".")))


def next_version(data_root: Path) -> str:
    versions = available_versions(data_root)
    if not versions:
        return "v1"
    latest_major = int(versions[-1][1:].split(".")[0])
    return f"v{latest_major + 1}"


def current_data_version(connection: sqlite3.Connection, data_root: Path) -> str:
    row = connection.execute("SELECT value FROM app_settings WHERE key='data_version'").fetchone()
    if row and VERSION_PATTERN.fullmatch(str(row[0])):
        return str(row[0])
    return next_version(data_root)


def set_data_version(connection: sqlite3.Connection, version: str) -> str:
    version = version.strip()
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError("version must look like v3 or v3.1")
    connection.execute("INSERT INTO app_settings(key,value) VALUES ('data_version',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP", (version,))
    connection.commit()
    return version


def export_version_snapshot(database: Path, data_root: Path, version: str, export_format: str) -> dict[str, object]:
    if export_format not in {"csv", "database"}:
        raise ValueError("export format must be csv or database")
    data_root.mkdir(parents=True, exist_ok=True)
    version = version.strip()
    if export_format == "database":
        if not VERSION_PATTERN.fullmatch(version):
            raise ValueError("version must look like v3 or v3.1")
        target = data_root / version
        if target.exists():
            raise ValueError(f"data version already exists: {version}")
        prefix = f".{version}-"
    else:
        target = data_root / "tmp"
        prefix = ".tmp-export-"

    with tempfile.TemporaryDirectory(prefix=prefix, dir=data_root) as temporary:
        staging = Path(temporary)
        files: list[str] = []
        if export_format == "database":
            filename = "gemuworld.sqlite3"
            source = sqlite3.connect(database)
            destination = sqlite3.connect(staging / filename)
            try:
                source.backup(destination)
            finally:
                destination.close()
                source.close()
            files.append(filename)
        else:
            connection = sqlite3.connect(database)
            connection.row_factory = sqlite3.Row
            try:
                for language in ("zh", "en"):
                    for card_type in ("monster", "prophecy"):
                        cards = list_cards(connection, language=language, card_type=card_type, sort_by="database_order", direction="asc")
                        body, filename, _ = export_cards(cards, language)
                        (staging / filename).write_bytes(body)
                        files.append(filename)
            finally:
                connection.close()
        if export_format == "database":
            staging.replace(target)
        else:
            target.mkdir(exist_ok=True)
            for filename in files:
                (staging / filename).replace(target / filename)
    return {"version": version if export_format == "database" else None, "format": export_format, "path": str(target.resolve()), "files": files}


def cards_to_records(cards: list[dict[str, object]]) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    monsters: list[dict[str, object]] = []
    prophecies: list[dict[str, object]] = []
    for card in cards:
        effect_types = {effect["type"]: effect for effect in card["effects"]}
        if card["type"] == "monster":
            attributes = {}
            if "monster_attribute" in effect_types:
                attributes["normal_attribute"] = effect_types["monster_attribute"]["text"]
            if "monster_reactive_attribute" in effect_types:
                attributes["responsive_attribute"] = effect_types["monster_reactive_attribute"]["text"]
            skills = [effect for effect in card["effects"] if effect["type"] == "monster_skill"]
            skills.sort(key=lambda effect: (effect["position"], effect["id"]))
            monsters.append({"card_id": card["card_id"], "card_title": card["title"], "level": card["level"], "monster_type": card["monster_type"], "description": card["description"], "attack": card["attack"], "defence": card["defence"], "magic": card["magic"], "attributes": json.dumps(attributes, ensure_ascii=False, separators=(",", ":")), "skills": json.dumps([{"name": effect["name"], "energy_cost": effect["energy_cost"] or 0, "effect": effect["text"]} for effect in skills], ensure_ascii=False, separators=(",", ":")), "image": legacy_image_path(card.get("image_path", card["image"])), "last_update_datetime": card["updated_at"]})
        else:
            prophecies.append({"card_id": card["card_id"], "card_title": card["title"], "introduction": card["introduction"], "effect": effect_types.get("prophecy_effect", {}).get("text", ""), "responsive_effect": effect_types.get("prophecy_reactive_effect", {}).get("text", ""), "image": legacy_image_path(card.get("image_path", card["image"])), "last_update_datetime": card["updated_at"]})
    return monsters, prophecies


def export_cards(cards: list[dict[str, object]], language: str) -> tuple[bytes, str, str]:
    monsters, prophecies = cards_to_records(cards)
    suffix = "" if language == "zh" else "_en"
    if monsters and not prophecies:
        return render_records(MONSTER_HEADER, monsters).encode("utf-8"), f"monster_cards{suffix}.csv", "text/csv; charset=utf-8"
    if prophecies and not monsters:
        return render_records(PROPHECY_HEADER, prophecies).encode("utf-8"), f"prophecy_cards{suffix}.csv", "text/csv; charset=utf-8"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"monster_cards{suffix}.csv", render_records(MONSTER_HEADER, monsters))
        archive.writestr(f"prophecy_cards{suffix}.csv", render_records(PROPHECY_HEADER, prophecies))
    return buffer.getvalue(), f"gemuworld_cards_{language}.zip", "application/zip"


def order_cards(cards: list[dict[str, object]], card_ids: list[str]) -> list[dict[str, object]]:
    by_id = {str(card["card_id"]): card for card in cards}
    return [by_id[card_id] for card_id in card_ids if card_id in by_id]
