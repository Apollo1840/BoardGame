from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .image_paths import CANONICAL_PREFIX, card_image_path, normalize_image_path


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def _rows(connection: sqlite3.Connection) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for card_type in ("monster", "prophecy"):
        for row in connection.execute(f"SELECT id,card_id,image_path FROM {card_type}_cards ORDER BY id"):
            rows.append({"card_type": card_type, "database_id": row["id"], "card_id": row["card_id"], "image_path": row["image_path"]})
    return rows


def plan_image_renames(connection: sqlite3.Connection, pics_root: Path) -> dict[str, object]:
    pics_root = pics_root.resolve()
    items: list[dict[str, object]] = []
    errors: list[str] = []
    warnings: list[str] = []
    source_owners: dict[str, list[str]] = {}
    target_owners: dict[str, list[str]] = {}
    for row in _rows(connection):
        card_id = str(row["card_id"])
        try:
            source_path = normalize_image_path(row["image_path"])
            target_path = card_image_path(card_id)
        except ValueError as exc:
            errors.append(f"{row['card_type']} {card_id}: {exc}")
            continue
        target = (pics_root / target_path.removeprefix(CANONICAL_PREFIX)).resolve()
        if pics_root not in target.parents:
            errors.append(f"{row['card_type']} {card_id}: artwork path escapes pics directory")
            continue
        if not source_path:
            warnings.append(f"{row['card_type']} {card_id}: no source image; database will be locked to {target.name}")
            items.append({**row, "old_image_path": "", "new_image_path": target_path, "source": "", "target": str(target), "action": "missing"})
            target_owners.setdefault(os.path.normcase(str(target)), []).append(card_id)
            continue
        source = (pics_root / source_path.removeprefix(CANONICAL_PREFIX)).resolve()
        if pics_root not in source.parents:
            errors.append(f"{row['card_type']} {card_id}: artwork path escapes pics directory")
            continue
        source_key = os.path.normcase(str(source))
        target_key = os.path.normcase(str(target))
        source_owners.setdefault(source_key, []).append(card_id)
        target_owners.setdefault(target_key, []).append(card_id)
        if not source.is_file():
            warnings.append(f"{row['card_type']} {card_id}: source image is missing: {source.name}; database path will still be locked")
        elif source.is_file():
            with source.open("rb") as handle:
                if handle.read(8) != PNG_SIGNATURE:
                    errors.append(f"{row['card_type']} {card_id}: source is not a PNG file: {source.name}")
        action = "missing" if not source.is_file() else ("unchanged" if source_key == target_key else "rename")
        items.append({**row, "old_image_path": source_path, "new_image_path": target_path, "source": str(source), "target": str(target), "action": action})
    for source_key, owners in source_owners.items():
        if len(owners) > 1:
            warnings.append(f"shared source image will be copied for: {', '.join(owners)}")
            for item in items:
                if item["source"] and os.path.normcase(str(item["source"])) == source_key and item["action"] in {"rename", "unchanged"}:
                    item["action"] = "copy"
    for owners in target_owners.values():
        if len(owners) > 1:
            errors.append(f"multiple cards resolve to one target filename: {', '.join(owners)}")
    source_keys = {os.path.normcase(str(Path(str(item["source"])))) for item in items if item["source"] and Path(str(item["source"])).is_file()}
    for item in items:
        target = Path(str(item["target"]))
        target_key = os.path.normcase(str(target))
        if item["action"] == "rename" and target.exists() and target_key not in source_keys:
            errors.append(f"{item['card_type']} {item['card_id']}: target already exists: {target.name}")
    referenced = {os.path.normcase(str(Path(str(item["source"])))) for item in items if item["source"]}
    orphans = sorted(path.name for path in pics_root.iterdir() if path.is_file() and os.path.normcase(str(path.resolve())) not in referenced)
    return {"format": "gemuworld.image-rename-plan", "schema_version": 1, "database_count": len(items), "rename_count": sum(item["action"] == "rename" for item in items), "copy_count": sum(item["action"] == "copy" for item in items), "missing_count": sum(item["action"] == "missing" for item in items), "unchanged_count": sum(item["action"] == "unchanged" for item in items), "orphan_files": orphans, "warnings": sorted(set(warnings)), "errors": sorted(set(errors)), "items": items}


def _write_manifest(plan: dict[str, object], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    target = output_dir / f"image_rename_{timestamp}.json"
    payload = {**plan, "created_at": datetime.now(timezone.utc).isoformat(), "status": "applied"}
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".tmp", prefix=".image-rename-", dir=output_dir, delete=False) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(target)
    return target


def apply_image_renames(connection: sqlite3.Connection, pics_root: Path, manifest_dir: Path) -> dict[str, object]:
    plan = plan_image_renames(connection, pics_root)
    if plan["errors"]:
        raise ValueError("image rename preflight failed:\n" + "\n".join(str(error) for error in plan["errors"]))
    mappings = [item for item in plan["items"] if item["action"] in {"rename", "copy"}]
    staged_sources: dict[str, tuple[Path, Path]] = {}
    created_targets: list[Path] = []
    manifest: Path | None = None
    connection.execute("BEGIN IMMEDIATE")
    try:
        for item in mappings:
            source = Path(str(item["source"]))
            source_key = os.path.normcase(str(source))
            if source_key not in staged_sources:
                stage = source.with_name(f".gemuworld-rename-{uuid.uuid4().hex}.tmp")
                source.replace(stage)
                staged_sources[source_key] = (source, stage)
        for item in mappings:
            source_key = os.path.normcase(str(Path(str(item["source"]))))
            stage = staged_sources[source_key][1]
            target = Path(str(item["target"]))
            shutil.copy2(stage, target)
            created_targets.append(target)
        for item in plan["items"]:
            table = f"{item['card_type']}_cards"
            connection.execute(f"UPDATE {table} SET image_path=?,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=?", (item["new_image_path"], item["database_id"]))
            connection.execute("INSERT INTO change_log(entity_type,entity_id,action,details_json) VALUES (?,?,?,?)", (f"{item['card_type']}_card", item["database_id"], "rename_image_to_card_id", json.dumps({"old_image_path": item["old_image_path"], "new_image_path": item["new_image_path"]}, ensure_ascii=False)))
        manifest = _write_manifest(plan, manifest_dir)
        connection.commit()
        for _, stage in staged_sources.values():
            stage.unlink(missing_ok=True)
    except Exception:
        connection.rollback()
        if manifest is not None:
            manifest.unlink(missing_ok=True)
        for target in reversed(created_targets):
            target.unlink(missing_ok=True)
        for source, stage in reversed(list(staged_sources.values())):
            if stage.exists():
                stage.replace(source)
        raise
    return {"applied": True, "renamed": plan["rename_count"], "copied": plan["copy_count"], "missing": plan["missing_count"], "unchanged": plan["unchanged_count"], "manifest": str(manifest.resolve()), "orphan_files": plan["orphan_files"], "warnings": plan["warnings"]}
