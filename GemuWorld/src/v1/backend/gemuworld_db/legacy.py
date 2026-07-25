from __future__ import annotations

import csv
import json
import re
import sqlite3
from uuid import uuid4
from dataclasses import dataclass, field
from pathlib import Path

from .cards import reorder_monster_skills
from .image_paths import card_image_path, legacy_image_path
from .pipe_csv import read_records, write_records


MONSTER_HEADER = ["card_id", "card_title", "level", "monster_type", "description", "attack", "defence", "magic", "attributes", "skills", "image", "last_update_datetime"]
PROPHECY_HEADER = ["card_id", "card_title", "introduction", "effect", "responsive_effect", "image", "last_update_datetime"]
ROLE_CODES = {"⚔️assassin", "🛡️tank", "🏹shooter", "🧠strategy", "🪄magician"}
GUIDE_TITLES = {"monster_design_table": "怪物设计表"}
DECK_TYPE_BY_CODE = {
    "Intro": "story",
    "Wind": "attribute",
    "Rock": "attribute",
    "Thunder": "attribute",
    "Wood": "attribute",
    "Sea": "attribute",
    "Fire": "attribute",
    "Frost": "tribe",
    "Human": "tribe",
    "Goblin": "race",
    "Immortal": "race",
    "WalkingDead": "race",
    "Poker": "culture",
    "3kings": "culture",
    "FairyTell": "culture",
    "Animal": "race",
    "Dragon": "race",
    "Insects": "race",
    "Robot": "race",
    "Party": "story",
}
DECK_ZH_NAME_BY_CODE = {
    "Intro": "灵坛村",
    "Wind": "风",
    "Rock": "岩",
    "Thunder": "雷",
    "Wood": "木",
    "Sea": "水",
    "Fire": "火",
    "Frost": "北境霜毒",
    "Human": "将军城",
    "Goblin": "哥布林族",
    "Immortal": "仙族",
    "WalkingDead": "不死族",
    "Poker": "扑克牌",
    "3kings": "三国",
    "FairyTell": "邪恶童话",
    "Animal": "兽族",
    "Dragon": "龙族",
    "Insects": "虫族",
    "Robot": "机器人族",
    "Party": "梦汐岛",
}


def _text(value: str) -> str:
    return value.replace("\\n", "\n")


@dataclass
class ImportReport:
    counts: dict[str, int] = field(default_factory=dict)
    warnings: list[dict[str, object]] = field(default_factory=list)
    errors: list[dict[str, object]] = field(default_factory=list)

    def issue(self, severity: str, source: str, message: str, **details: object) -> None:
        getattr(self, severity + "s").append({"severity": severity, "source": source, "message": message, "details": details})

    def as_dict(self) -> dict[str, object]:
        return {"counts": self.counts, "warnings": self.warnings, "errors": self.errors}


def _number(value: str, source: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{source}: invalid number {value!r}") from exc


def _json(value: str, expected: type, source: str):
    try:
        parsed = json.loads(value or ("{}" if expected is dict else "[]"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{source}: invalid JSON: {exc}") from exc
    if not isinstance(parsed, expected):
        raise ValueError(f"{source}: expected {expected.__name__} JSON")
    return parsed


def _upsert_translation(connection: sqlite3.Connection, table: str, owner_column: str, owner_id: int, language: str, values: dict[str, str]) -> None:
    columns = [owner_column, "language", *values]
    placeholders = ",".join("?" for _ in columns)
    updates = ",".join(f"{column}=excluded.{column}" for column in values)
    connection.execute(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders}) "
        f"ON CONFLICT({owner_column},language) DO UPDATE SET {updates}",
        [owner_id, language, *values.values()],
    )


def _insert_effect(connection: sqlite3.Connection, owner: str, owner_id: int, effect_type: str, position: int, energy_cost: float | None, translations: dict[str, tuple[str, str]]) -> None:
    cursor = connection.execute(
        f"INSERT INTO effects({owner}_card_id,effect_type,position,energy_cost) VALUES (?,?,?,?)",
        (owner_id, effect_type, position, energy_cost),
    )
    for language, (name, text) in translations.items():
        connection.execute(
            "INSERT INTO effect_translations(effect_id,language,name,text) VALUES (?,?,?,?)",
            (cursor.lastrowid, language, name, text),
        )


def _indexed(records: list[dict[str, str]], source: str, report: ImportReport) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for record in records:
        card_id = record.get("card_id", "")
        if not card_id:
            report.issue("error", source, "card has no card_id", title=record.get("card_title", ""))
        elif card_id in result:
            previous = result[card_id]
            # Translation files contain a few historical duplicates. Keep the newest
            # translation deterministically and report the cleanup.
            if record.get("last_update_datetime", "") >= previous.get("last_update_datetime", ""):
                result[card_id] = record
            report.issue("warning", source, "duplicate card_id; newest translation selected", card_id=card_id)
        else:
            result[card_id] = record
    return result


def _import_monsters(connection: sqlite3.Connection, zh_path: Path, en_path: Path, report: ImportReport) -> None:
    zh_records = read_records(zh_path)
    en = _indexed(read_records(en_path), str(en_path), report)
    seen_en: set[str] = set()
    for row in zh_records:
        card_id = row["card_id"]
        cursor = connection.execute(
            "INSERT INTO monster_cards(card_id,level,monster_type,attack,defence,magic,image_path,source_updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (card_id, int(_number(row["level"], card_id)), row["monster_type"], _number(row["attack"], card_id), _number(row["defence"], card_id), _number(row["magic"], card_id), card_image_path(card_id), row["last_update_datetime"]),
        )
        owner_id = cursor.lastrowid
        _upsert_translation(connection, "monster_card_translations", "monster_card_id", owner_id, "zh", {"title": _text(row["card_title"]), "monster_type": _text(row["monster_type"]), "description": _text(row["description"]), "source_updated_at": row["last_update_datetime"]})
        en_row = en.get(card_id)
        if en_row:
            seen_en.add(card_id)
            for shared_field in ("level", "attack", "defence", "magic", "image"):
                if en_row[shared_field] != row[shared_field]:
                    report.issue("warning", str(en_path), "translated row differs from canonical Chinese shared field", card_id=card_id, field=shared_field, zh=row[shared_field], en=en_row[shared_field])
            _upsert_translation(connection, "monster_card_translations", "monster_card_id", owner_id, "en", {"title": _text(en_row["card_title"]), "monster_type": _text(en_row["monster_type"]), "description": _text(en_row["description"]), "source_updated_at": en_row["last_update_datetime"]})
        else:
            report.issue("warning", str(en_path), "missing English translation", card_id=card_id, title=row["card_title"])

        attrs_zh = _json(row["attributes"], dict, card_id)
        attrs_en = _json(en_row["attributes"], dict, card_id) if en_row else {}
        attr_types = [("normal_attribute", "monster_attribute"), ("responsive_attribute", "monster_reactive_attribute")]
        for position, (key, effect_type) in enumerate(attr_types):
            if key in attrs_zh or key in attrs_en:
                translations = {}
                if key in attrs_zh:
                    translations["zh"] = ("", str(attrs_zh[key]))
                if en_row and key in attrs_en:
                    translations["en"] = ("", str(attrs_en.get(key, "")))
                _insert_effect(connection, "monster", owner_id, effect_type, position, None, translations)

        skills_zh = _json(row["skills"], list, card_id)
        skills_en = _json(en_row["skills"], list, card_id) if en_row else []
        if en_row and len(skills_zh) != len(skills_en):
            report.issue("warning", str(en_path), "skill count differs from Chinese card", card_id=card_id, zh=len(skills_zh), en=len(skills_en))
        for position, skill in enumerate(skills_zh):
            if not isinstance(skill, dict):
                raise ValueError(f"{card_id}: skill {position} is not an object")
            translated = skills_en[position] if position < len(skills_en) and isinstance(skills_en[position], dict) else {}
            if translated and float(translated.get("energy_cost", 0) or 0) != float(skill.get("energy_cost", 0) or 0):
                report.issue("warning", str(en_path), "translated skill energy cost differs from canonical Chinese value", card_id=card_id, position=position, zh=skill.get("energy_cost", 0), en=translated.get("energy_cost", 0))
            translations = {"zh": (str(skill.get("name", "")), str(skill.get("effect", "")))}
            if en_row and position < len(skills_en) and isinstance(skills_en[position], dict):
                translations["en"] = (str(translated.get("name", "")), str(translated.get("effect", "")))
            _insert_effect(connection, "monster", owner_id, "monster_skill", position, float(skill.get("energy_cost", 0) or 0), translations)
    for card_id in sorted(set(en) - seen_en):
        report.issue("warning", str(en_path), "English row has no Chinese card", card_id=card_id)
    report.counts["monster_cards"] = len(zh_records)


def _import_prophecies(connection: sqlite3.Connection, zh_path: Path, en_path: Path, report: ImportReport) -> None:
    zh_records = read_records(zh_path)
    en = _indexed(read_records(en_path), str(en_path), report)
    seen_en: set[str] = set()
    for row in zh_records:
        card_id = row["card_id"]
        cursor = connection.execute(
            "INSERT INTO prophecy_cards(card_id,image_path,source_updated_at) VALUES (?,?,?)",
            (card_id, card_image_path(card_id), row["last_update_datetime"]),
        )
        owner_id = cursor.lastrowid
        _upsert_translation(connection, "prophecy_card_translations", "prophecy_card_id", owner_id, "zh", {"title": _text(row["card_title"]), "introduction": _text(row["introduction"]), "source_updated_at": row["last_update_datetime"]})
        en_row = en.get(card_id)
        if en_row:
            seen_en.add(card_id)
            if en_row["image"] != row["image"]:
                report.issue("warning", str(en_path), "translated row differs from canonical Chinese shared field", card_id=card_id, field="image", zh=row["image"], en=en_row["image"])
            _upsert_translation(connection, "prophecy_card_translations", "prophecy_card_id", owner_id, "en", {"title": _text(en_row["card_title"]), "introduction": _text(en_row["introduction"]), "source_updated_at": en_row["last_update_datetime"]})
        else:
            report.issue("warning", str(en_path), "missing English translation", card_id=card_id, title=row["card_title"])
        for position, (column, effect_type) in enumerate((("effect", "prophecy_effect"), ("responsive_effect", "prophecy_reactive_effect"))):
            zh_text = _text(row[column])
            en_text = _text(en_row[column]) if en_row else ""
            if zh_text or en_text:
                translations = {}
                if zh_text:
                    translations["zh"] = ("", zh_text)
                if en_row and en_text:
                    translations["en"] = ("", en_text)
                _insert_effect(connection, "prophecy", owner_id, effect_type, position, None, translations)
    for card_id in sorted(set(en) - seen_en):
        report.issue("warning", str(en_path), "English row has no Chinese card", card_id=card_id)
    report.counts["prophecy_cards"] = len(zh_records)


def _deck_type(code: str) -> str:
    if code in ROLE_CODES:
        return "role"
    if code == "_tutorial_":
        return "tutorial"
    if code == "_temp_":
        return "temporary"
    return DECK_TYPE_BY_CODE.get(code, "tribe")


def _card_title_maps(connection: sqlite3.Connection) -> tuple[dict[str, list[int]], dict[str, list[int]]]:
    monsters: dict[str, list[int]] = {}
    prophecies: dict[str, list[int]] = {}
    for row in connection.execute("SELECT monster_card_id,title FROM monster_card_translations WHERE language='zh'"):
        monsters.setdefault(row["title"], []).append(row["monster_card_id"])
    for row in connection.execute("SELECT prophecy_card_id,title FROM prophecy_card_translations WHERE language='zh'"):
        prophecies.setdefault(row["title"], []).append(row["prophecy_card_id"])
    return monsters, prophecies


def _section_hint(section: str) -> str | None:
    normalized = section.replace(" ", "")
    if normalized in ("预言", "预言卡"):
        return "prophecy"
    if normalized in ("怪物", "怪物卡"):
        return "monster"
    return None


def _import_decks(connection: sqlite3.Connection, clan_dir: Path, report: ImportReport) -> None:
    codes = json.loads((clan_dir / "_clans.json").read_text(encoding="utf-8-sig"))
    monsters, prophecies = _card_title_maps(connection)
    for display_order, raw_code in enumerate(codes):
        code = str(raw_code)
        candidates = [clan_dir / f"{code}.md"]
        # Historical index uses 3kings while the checked-in file is 3Kings.md.
        if not candidates[0].exists():
            candidates = [path for path in clan_dir.glob("*.md") if path.stem.casefold() == code.casefold()]
        if not candidates:
            report.issue("error", str(clan_dir / "_clans.json"), "indexed clan file is missing", code=code)
            continue
        path = candidates[0]
        markdown = path.read_text(encoding="utf-8-sig")
        cursor = connection.execute(
            "INSERT INTO decks(deck_id,code,deck_type,display_order,source_filename,source_markdown_zh) VALUES (?,?,?,?,?,?)",
            (f"deck-{uuid4()}", code, _deck_type(code), display_order, path.name, markdown),
        )
        deck_id = cursor.lastrowid
        connection.execute("INSERT INTO deck_translations(deck_id,language,name,description) VALUES (?,?,?,?)", (deck_id, "zh", DECK_ZH_NAME_BY_CODE.get(code, code), markdown))
        connection.execute("INSERT INTO deck_translations(deck_id,language,name) VALUES (?,?,?)", (deck_id, "en", code))
        section = ""
        position = 0
        seen: set[tuple[str, int]] = set()
        for line_number, raw_line in enumerate(markdown.splitlines(), start=1):
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("//"):
                section = line[2:].strip()
                continue
            if line.startswith("#"):
                section = line.lstrip("#").strip()
                continue
            title = re.sub(r"^[-*+]\s+", "", line).strip()
            hint = _section_hint(section)
            monster_ids = monsters.get(title, [])
            prophecy_ids = prophecies.get(title, [])
            choices = [("monster", value) for value in monster_ids] + [("prophecy", value) for value in prophecy_ids]
            if hint:
                choices = [choice for choice in choices if choice[0] == hint]
            if len(choices) != 1:
                severity = "error" if not choices else "warning"
                report.issue(severity, str(path), "card title cannot be resolved uniquely", line=line_number, title=title, section=section, matches=choices)
                continue
            card_type, card_id = choices[0]
            key = (card_type, card_id)
            if key in seen:
                report.issue("warning", str(path), "duplicate card in deck ignored", line=line_number, title=title)
                continue
            seen.add(key)
            column = f"{card_type}_card_id"
            connection.execute(f"INSERT INTO deck_cards(deck_id,{column},position,section) VALUES (?,?,?,?)", (deck_id, card_id, position, section))
            position += 1
    report.counts["decks"] = connection.execute("SELECT COUNT(*) FROM decks").fetchone()[0]
    report.counts["deck_cards"] = connection.execute("SELECT COUNT(*) FROM deck_cards").fetchone()[0]


def _nullable_number(value: str) -> float | None:
    value = value.strip()
    return None if not value or value == "无" else float(value)


def _import_guides(connection: sqlite3.Connection, manual_dir: Path, report: ImportReport) -> None:
    for path in sorted(manual_dir.glob("*.md")):
        connection.execute(
            "INSERT INTO design_guides(code,guide_type,title,content,source_path) VALUES (?,?,?,?,?)",
            (path.stem, "markdown", GUIDE_TITLES.get(path.stem, path.stem), path.read_text(encoding="utf-8-sig"), path.name),
        )
    benchmark_path = manual_dir / "monster_design_table.csv"
    with benchmark_path.open(encoding="utf-8-sig", newline="") as handle:
        for source_row, row in enumerate(csv.DictReader(handle), start=2):
            connection.execute(
                "INSERT INTO monster_stat_benchmarks(level,total_stats,attack_max,defence_max,effect_tier,one_bonus,two_bonus,multi_bonus,source_row) VALUES (?,?,?,?,?,?,?,?,?)",
                (int(row["等级"]), float(row["数值总数"]), float(row["攻击上限"]), float(row["防御上限"]), float(row["效果品阶"]), _nullable_number(row["1增配置"]), _nullable_number(row["2增配置"]), _nullable_number(row["多增配置"]), source_row),
            )
    for table_path in sorted(manual_dir.glob("*.csv")):
        if table_path == benchmark_path:
            continue
        with table_path.open(encoding="utf-8-sig", newline="") as handle:
            for position, row in enumerate(csv.DictReader(handle)):
                connection.execute("INSERT INTO reference_table_rows(table_code,position,data_json) VALUES (?,?,?)", (table_path.stem, position, json.dumps(row, ensure_ascii=False, separators=(",", ":"))))
    report.counts["design_guides"] = connection.execute("SELECT COUNT(*) FROM design_guides").fetchone()[0]
    report.counts["monster_stat_benchmarks"] = connection.execute("SELECT COUNT(*) FROM monster_stat_benchmarks").fetchone()[0]
    report.counts["reference_table_rows"] = connection.execute("SELECT COUNT(*) FROM reference_table_rows").fetchone()[0]


def import_legacy(connection: sqlite3.Connection, v1_root: Path, manual_dir: Path) -> ImportReport:
    report = ImportReport()
    tables = ["import_issues", "deck_cards", "deck_translations", "decks", "effect_translations", "effects", "monster_card_translations", "prophecy_card_translations", "monster_cards", "prophecy_cards", "design_guides", "monster_stat_benchmarks", "reference_table_rows"]
    with connection:
        for table in tables:
            connection.execute(f"DELETE FROM {table}")
        cards = v1_root / "data" / "current" / "cards"
        _import_monsters(connection, cards / "monster_cards.csv", cards / "monster_cards_en.csv", report)
        for row in connection.execute(
            "SELECT DISTINCT monster_card_id FROM effects "
            "WHERE effect_type='monster_skill' AND monster_card_id IS NOT NULL"
        ):
            reorder_monster_skills(connection, row["monster_card_id"])
        _import_prophecies(connection, cards / "prophecy_cards.csv", cards / "prophecy_cards_en.csv", report)
        _import_decks(connection, v1_root / "data" / "current" / "clans", report)
        _import_guides(connection, manual_dir, report)
        for issue in [*report.warnings, *report.errors]:
            connection.execute(
                "INSERT INTO import_issues(severity,source,message,details_json) VALUES (?,?,?,?)",
                (issue["severity"], issue["source"], issue["message"], json.dumps(issue["details"], ensure_ascii=False)),
            )
    return report


def _translations(connection: sqlite3.Connection, table: str, owner: str, language: str) -> dict[int, sqlite3.Row]:
    return {row[owner]: row for row in connection.execute(f"SELECT * FROM {table} WHERE language=?", (language,))}


def export_legacy_cards(connection: sqlite3.Connection, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for language, suffix in (("zh", ""), ("en", "_en")):
        mt = _translations(connection, "monster_card_translations", "monster_card_id", language)
        et = _translations(connection, "effect_translations", "effect_id", language)
        monster_rows = []
        for card in connection.execute("SELECT * FROM monster_cards WHERE status='active' ORDER BY id"):
            translation = mt.get(card["id"])
            if not translation:
                continue
            attrs: dict[str, str] = {}
            skills: list[dict[str, object]] = []
            for effect in connection.execute("SELECT * FROM effects WHERE monster_card_id=? ORDER BY effect_type,position", (card["id"],)):
                text = et.get(effect["id"])
                if not text:
                    continue
                if effect["effect_type"] == "monster_attribute": attrs["normal_attribute"] = text["text"] if text else ""
                elif effect["effect_type"] == "monster_reactive_attribute": attrs["responsive_attribute"] = text["text"] if text else ""
                elif effect["effect_type"] == "monster_skill": skills.append({"name": text["name"] if text else "", "energy_cost": effect["energy_cost"] or 0, "effect": text["text"] if text else ""})
            monster_rows.append({"card_id": card["card_id"], "card_title": translation["title"], "level": card["level"], "monster_type": translation["monster_type"], "description": translation["description"], "attack": card["attack"], "defence": card["defence"], "magic": card["magic"], "attributes": json.dumps(attrs, ensure_ascii=False, separators=(",", ":")), "skills": json.dumps(skills, ensure_ascii=False, separators=(",", ":")), "image": legacy_image_path(card["image_path"]), "last_update_datetime": translation["source_updated_at"]})
        write_records(output_dir / f"monster_cards{suffix}.csv", MONSTER_HEADER, monster_rows)

        pt = _translations(connection, "prophecy_card_translations", "prophecy_card_id", language)
        prophecy_rows = []
        for card in connection.execute("SELECT * FROM prophecy_cards WHERE status='active' ORDER BY id"):
            translation = pt.get(card["id"])
            if not translation:
                continue
            effects = {row["effect_type"]: et.get(row["id"])["text"] if et.get(row["id"]) else "" for row in connection.execute("SELECT * FROM effects WHERE prophecy_card_id=?", (card["id"],))}
            prophecy_rows.append({"card_id": card["card_id"], "card_title": translation["title"], "introduction": translation["introduction"], "effect": effects.get("prophecy_effect", ""), "responsive_effect": effects.get("prophecy_reactive_effect", ""), "image": legacy_image_path(card["image_path"]), "last_update_datetime": translation["source_updated_at"]})
        write_records(output_dir / f"prophecy_cards{suffix}.csv", PROPHECY_HEADER, prophecy_rows)


def export_legacy_decks(connection: sqlite3.Connection, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    codes = []
    for deck in connection.execute("SELECT * FROM decks WHERE status='active' ORDER BY display_order,id"):
        codes.append(deck["code"])
        (output_dir / deck["source_filename"]).write_text(deck["source_markdown_zh"], encoding="utf-8", newline="")
    (output_dir / "_clans.json").write_text(json.dumps(codes, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
