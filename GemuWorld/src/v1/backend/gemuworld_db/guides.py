from __future__ import annotations

import json
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
