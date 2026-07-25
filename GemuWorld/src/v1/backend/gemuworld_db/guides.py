from __future__ import annotations

import json
import re
import sqlite3

from .cards import VersionConflict


class GuideWriteError(ValueError):
    pass


def list_guides(connection: sqlite3.Connection) -> list[dict[str, object]]:
    return [dict(row) for row in connection.execute("SELECT * FROM design_guides WHERE status='active' ORDER BY code")]


def update_guide(connection: sqlite3.Connection, guide_id: int, payload: dict[str, object]) -> dict[str, object]:
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute("SELECT * FROM design_guides WHERE id=?", (guide_id,)).fetchone()
        if not row:
            raise GuideWriteError("guide not found")
        if int(payload.get("version", 0)) != row["version"]:
            raise VersionConflict("guide changed since it was opened")
        title = str(payload.get("title", "")).strip()
        if not title:
            raise GuideWriteError("guide title is required")
        connection.execute("UPDATE design_guides SET title=?,content=?,version=version+1,updated_at=CURRENT_TIMESTAMP WHERE id=?", (title, str(payload.get("content", "")), guide_id))
        connection.execute("INSERT INTO change_log(entity_type,entity_id,action,details_json) VALUES ('design_guide',?,'update',?)", (guide_id, json.dumps({"title": title}, ensure_ascii=False)))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return dict(connection.execute("SELECT * FROM design_guides WHERE id=?", (guide_id,)).fetchone())


def list_benchmarks(connection: sqlite3.Connection) -> list[dict[str, object]]:
    return [dict(row) for row in connection.execute("SELECT * FROM monster_stat_benchmarks ORDER BY level,total_stats DESC,effect_tier")]


def _table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _table_number(value: str) -> int | float | None:
    value = value.strip()
    if not value or value == "-":
        return None
    number = float(value)
    return int(number) if number.is_integer() else number


def _limit_number(value: str) -> int | float | None:
    matches = re.findall(r"-?\d+(?:\.\d+)?", value)
    return _table_number(matches[-1]) if matches else None


def list_monster_design_rows(connection: sqlite3.Connection) -> list[dict[str, object]]:
    """Read the editable monster-design markdown table as structured rows."""
    guide = connection.execute("SELECT content FROM design_guides WHERE code='monster_design_table' AND status='active'").fetchone()
    if not guide:
        return []
    lines = str(guide["content"]).splitlines()
    header_index = next((index for index, line in enumerate(lines) if _table_cells(line)[:4] == ["等级", "数值总数", "攻击上限", "防御上限"]), None)
    if header_index is None:
        return []
    rows: list[dict[str, object]] = []
    for line in lines[header_index + 2:]:
        if not line.strip().startswith("|"):
            break
        cells = _table_cells(line)
        if len(cells) < 8:
            continue
        rows.append({
            "level": _table_number(cells[0]),
            "total_stats": _table_number(cells[1]),
            "attack_limit": cells[2],
            "attack_max": _limit_number(cells[2]),
            "defence_limit": cells[3],
            "defence_max": _limit_number(cells[3]),
            "effect_tier": _table_number(cells[4]),
            "one_bonus": _table_number(cells[5]),
            "two_bonus": _table_number(cells[6]),
            "multi_bonus": _table_number(cells[7]),
        })
    return rows


def update_benchmark(connection: sqlite3.Connection, benchmark_id: int, payload: dict[str, object]) -> dict[str, object]:
    fields = ("level", "total_stats", "attack_max", "defence_max", "effect_tier", "one_bonus", "two_bonus", "multi_bonus")
    connection.execute("BEGIN IMMEDIATE")
    try:
        row = connection.execute("SELECT * FROM monster_stat_benchmarks WHERE id=?", (benchmark_id,)).fetchone()
        if not row:
            raise GuideWriteError("benchmark not found")
        if int(payload.get("version", 0)) != row["version"]:
            raise VersionConflict("benchmark changed since it was opened")
        values = [payload.get(field, row[field]) for field in fields]
        connection.execute("UPDATE monster_stat_benchmarks SET level=?,total_stats=?,attack_max=?,defence_max=?,effect_tier=?,one_bonus=?,two_bonus=?,multi_bonus=?,version=version+1 WHERE id=?", (*values, benchmark_id))
        connection.execute("INSERT INTO change_log(entity_type,entity_id,action) VALUES ('monster_stat_benchmark',?,'update')", (benchmark_id,))
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return dict(connection.execute("SELECT * FROM monster_stat_benchmarks WHERE id=?", (benchmark_id,)).fetchone())
