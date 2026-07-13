from __future__ import annotations

import json
import io
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.parse
import zipfile
from pathlib import Path


V1_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = V1_ROOT.parents[2]
sys.path.insert(0, str(V1_ROOT / "backend"))

from gemuworld_db.database import connect, migrate  # noqa: E402
from gemuworld_db.legacy import export_legacy_cards, export_legacy_decks, import_legacy  # noqa: E402
from gemuworld_db.pipe_csv import parse_line, read_records  # noqa: E402
from gemuworld_db.pipe_csv import render_records  # noqa: E402
from gemuworld_db.queries import list_cards, list_decks  # noqa: E402
from gemuworld_db.server import ViewerServer  # noqa: E402
from gemuworld_db.exports import available_versions, current_data_version, export_cards, export_version_snapshot, next_version, set_data_version  # noqa: E402
from gemuworld_db.statistics import compute_statistics  # noqa: E402
from gemuworld_db.batch_import import BatchImportError, import_cards  # noqa: E402
from gemuworld_db.cards import CardWriteError, VersionConflict, copy_card, delete_card, get_card, save_card  # noqa: E402
from gemuworld_db.decks import DeckWriteError, delete_deck, get_deck, save_deck  # noqa: E402
from gemuworld_db.effects import EffectWriteError, copy_effect, get_effect, list_effects, list_professions, profession_counts, update_effect  # noqa: E402
from gemuworld_db.guides import list_benchmarks, list_guides, update_benchmark, update_guide  # noqa: E402
from gemuworld_db.legacy import MONSTER_HEADER, PROPHECY_HEADER  # noqa: E402


class PipeCsvTests(unittest.TestCase):
    def test_escaped_pipe_newline_and_backslash(self):
        self.assertEqual(parse_line(r"a|b\|c|line\nnext|slash\\end"), ["a", "b|c", r"line\nnext", "slash\\end"])


class MigrationTests(unittest.TestCase):
    def test_migrations_are_repeatable_and_effect_owner_is_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = connect(Path(directory) / "test.sqlite3")
            self.assertEqual(migrate(connection), ["001_initial.sql", "002_deck_versions.sql", "003_effect_guide_versions.sql", "004_effect_role_valuation.sql", "005_app_settings.sql", "006_effect_profession.sql", "007_effect_professions.sql", "008_effect_marker_notes.sql"])
            self.assertEqual(migrate(connection), [])
            monster = connection.execute("INSERT INTO monster_cards(card_id,level,attack,defence,magic) VALUES ('m1',0,1,1,1)").lastrowid
            other = connection.execute("INSERT INTO monster_cards(card_id,level,attack,defence,magic) VALUES ('m2',0,1,1,1)").lastrowid
            effect = connection.execute("INSERT INTO effects(monster_card_id,effect_type) VALUES (?, 'monster_skill')", (monster,)).lastrowid
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE effects SET monster_card_id=? WHERE id=?", (other, effect))
            connection.close()


class LegacyRoundTripTests(unittest.TestCase):
    def test_current_data_import_is_idempotent_and_card_export_is_semantic_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            connection = connect(directory / "test.sqlite3")
            try:
                migrate(connection)
                report1 = import_legacy(connection, V1_ROOT, REPOSITORY_ROOT / "GemuWorld" / "manual")
                counts1 = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in ("monster_cards", "prophecy_cards", "effects", "decks", "deck_cards")}
                report2 = import_legacy(connection, V1_ROOT, REPOSITORY_ROOT / "GemuWorld" / "manual")
                counts2 = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in counts1}
                self.assertEqual(counts1, counts2)
                self.assertEqual(report1.counts, report2.counts)
                self.assertFalse(report1.errors, json.dumps(report1.errors, ensure_ascii=False, indent=2))

                output = directory / "export"
                export_legacy_cards(connection, output)
                export_legacy_decks(connection, output / "clans")
                source = V1_ROOT / "data" / "current" / "cards"
                canonical_monsters = {row["card_id"]: row for row in read_records(source / "monster_cards.csv")}
                canonical_prophecies = {row["card_id"]: row for row in read_records(source / "prophecy_cards.csv")}
                for filename in ("monster_cards.csv", "monster_cards_en.csv", "prophecy_cards.csv", "prophecy_cards_en.csv"):
                    source_rows = read_records(source / filename)
                    # Duplicate translation IDs are legacy dirt; V1.1 selects the newest.
                    expected_by_id = {}
                    for row in source_rows:
                        old = expected_by_id.get(row["card_id"])
                        if old is None or row["last_update_datetime"] >= old["last_update_datetime"]:
                            expected_by_id[row["card_id"]] = row
                    if filename == "monster_cards_en.csv":
                        expected_by_id = {key: value for key, value in expected_by_id.items() if key in canonical_monsters}
                    elif filename == "prophecy_cards_en.csv":
                        expected_by_id = {key: value for key, value in expected_by_id.items() if key in canonical_prophecies}
                    actual = read_records(output / filename)
                    actual_by_id = {row["card_id"]: row for row in actual}
                    self.assertEqual(set(expected_by_id), set(actual_by_id))
                    for card_id, expected_row in expected_by_id.items():
                        actual_row = actual_by_id[card_id]
                        for key in expected_row:
                            if key in ("attributes", "skills"):
                                expected_json = json.loads(expected_row[key])
                                if key == "skills" and filename.startswith("monster_cards"):
                                    canonical_skills = json.loads(canonical_monsters[card_id]["skills"])
                                    canonical_order = sorted(
                                        range(len(canonical_skills)),
                                        key=lambda position: (
                                            float(canonical_skills[position].get("energy_cost", 0) or 0),
                                            str(canonical_skills[position].get("effect", "")).casefold(),
                                            position,
                                        ),
                                    )
                                    if filename == "monster_cards_en.csv":
                                        for position, skill in enumerate(expected_json):
                                            if position < len(canonical_skills):
                                                skill["energy_cost"] = canonical_skills[position].get("energy_cost", 0)
                                    expected_json = [expected_json[position] for position in canonical_order if position < len(expected_json)]
                                self.assertEqual(expected_json, json.loads(actual_row[key]), f"{filename}:{card_id}:{key}")
                            elif key in ("attack", "defence", "magic", "level"):
                                canonical = canonical_monsters[card_id][key] if filename == "monster_cards_en.csv" else expected_row[key]
                                self.assertEqual(float(canonical), float(actual_row[key]), f"{filename}:{card_id}:{key}")
                            elif key == "image" and filename == "monster_cards_en.csv":
                                self.assertEqual(canonical_monsters[card_id][key], actual_row[key], f"{filename}:{card_id}:{key}")
                            else:
                                self.assertEqual(expected_row[key], actual_row[key], f"{filename}:{card_id}:{key}")
                clan_source = V1_ROOT / "data" / "current" / "clans"
                expected_codes = json.loads((clan_source / "_clans.json").read_text(encoding="utf-8-sig"))
                actual_codes = json.loads((output / "clans" / "_clans.json").read_text(encoding="utf-8"))
                self.assertEqual(expected_codes, actual_codes)
                for deck in connection.execute("SELECT source_filename,source_markdown_zh FROM decks"):
                    self.assertEqual(deck["source_markdown_zh"], (output / "clans" / deck["source_filename"]).read_text(encoding="utf-8"))
            finally:
                connection.close()


class VersionExportTests(unittest.TestCase):
    def test_csv_and_database_version_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "source.sqlite3"
            connection = connect(database)
            migrate(connection)
            import_legacy(connection, V1_ROOT, REPOSITORY_ROOT / "GemuWorld" / "manual")
            connection.close()
            data_root = root / "data"
            (data_root / "v2.1").mkdir(parents=True)
            (data_root / "v2.2").mkdir()
            self.assertEqual(available_versions(data_root), ["v2.1", "v2.2"])
            self.assertEqual(next_version(data_root), "v3")
            connection = connect(database)
            self.assertEqual(current_data_version(connection, data_root), "v3")
            self.assertEqual(set_data_version(connection, "v3.1"), "v3.1")
            self.assertEqual(current_data_version(connection, data_root), "v3.1")
            connection.close()

            csv_result = export_version_snapshot(database, data_root, "", "csv")
            self.assertEqual(set(csv_result["files"]), {"monster_cards.csv", "prophecy_cards.csv", "monster_cards_en.csv", "prophecy_cards_en.csv"})
            self.assertIsNone(csv_result["version"])
            self.assertTrue(all((data_root / "tmp" / filename).is_file() for filename in csv_result["files"]))
            export_version_snapshot(database, data_root, "ignored", "csv")
            database_result = export_version_snapshot(database, data_root, "v2.3", "database")
            self.assertEqual(next_version(data_root), "v3")
            snapshot = sqlite3.connect(data_root / "v2.3" / database_result["files"][0])
            try:
                self.assertGreater(snapshot.execute("SELECT COUNT(*) FROM effects").fetchone()[0], 0)
            finally:
                snapshot.close()
            with self.assertRaises(ValueError):
                export_version_snapshot(database, data_root, "v2.3", "database")


class ReadOnlyApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.database = Path(cls.temp.name) / "api.sqlite3"
        connection = connect(cls.database)
        migrate(connection)
        cls.report = import_legacy(connection, V1_ROOT, REPOSITORY_ROOT / "GemuWorld" / "manual")
        connection.close()

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_queries_filter_language_deck_and_sort(self):
        connection = connect(self.database)
        try:
            zh = list_cards(connection, language="zh", card_type="monster", sort_by="title", direction="asc")
            en = list_cards(connection, language="en", card_type="monster")
            self.assertEqual(len(zh), 258)
            self.assertLess(len(en), len(zh))
            intro = list_cards(connection, language="zh", deck_codes=["Intro"])
            self.assertTrue(intro)
            self.assertTrue(all(any(deck["code"] == "Intro" for deck in card["decks"]) for card in intro))
            self.assertEqual([card["title"] for card in zh], sorted(card["title"] for card in zh))
            decks = list_decks(connection)
            self.assertEqual(len(decks), 27)
            self.assertEqual(len([deck for deck in decks if deck["type"] == "role"]), 5)
            stats = compute_statistics(intro)
            self.assertEqual(stats["total"], len(intro))
            self.assertEqual(stats["monster_count"] + stats["prophecy_count"], stats["total"])
            self.assertTrue(all(value > 0 for value in stats["deck_distribution"].values()))
        finally:
            connection.close()

    def test_http_api_and_database_backed_legacy_view(self):
        data_root = Path(self.temp.name) / "data"
        (data_root / "v2.1").mkdir(parents=True, exist_ok=True)
        (data_root / "v2.2").mkdir()
        server = ViewerServer(("127.0.0.1", 0), self.database, data_root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urllib.request.urlopen(base + "/api/health") as response:
                self.assertEqual(json.load(response)["version"], "1.7.5")
            with urllib.request.urlopen(base + "/api/export-info") as response:
                export_info = json.load(response)
                self.assertEqual(export_info["versions"], ["v2.1", "v2.2"])
                self.assertEqual(export_info["default_version"], "v3")
            version_request = urllib.request.Request(base + "/api/data-version", data=json.dumps({"version": "v3.1"}).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(version_request) as response:
                self.assertEqual(json.load(response)["current_version"], "v3.1")
            with urllib.request.urlopen(base + "/api/export-info") as response:
                self.assertEqual(json.load(response)["default_version"], "v3.1")
            with urllib.request.urlopen(base + "/api/cards?language=zh&card_type=prophecy&limit=3") as response:
                payload = json.load(response)
                self.assertEqual(payload["count"], 3)
                self.assertTrue(all(card["type"] == "prophecy" for card in payload["items"]))
            with urllib.request.urlopen(base + "/viewer") as response:
                html = response.read().decode("utf-8")
                self.assertIn("--cols: 3", html)
                self.assertIn("@media print", html)
                self.assertIn("grid-template-columns: repeat(var(--cols), var(--card-w))", html)
                self.assertIn("/api/cards", html)
                self.assertIn("/api/decks", html)
                self.assertNotIn("loadCSVWithHeader", html)
                self.assertNotIn("prophecy_cards_en.csv?t=", html)
                self.assertNotIn("clans/_clans.json", html)
            with urllib.request.urlopen(base + "/monster_cards.csv") as response:
                self.assertEqual(response.readline().decode("utf-8").strip().split("|")[0], "card_id")
            with urllib.request.urlopen(base + "/pictures/coreblossom.png") as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), "image/png")
                self.assertGreater(int(response.headers["Content-Length"]), 0)
            with urllib.request.urlopen(base + "/api/statistics?language=zh&deck=Intro") as response:
                statistics = json.load(response)["statistics"]
                self.assertGreater(statistics["total"], 0)
                self.assertEqual(statistics["deck_distribution"]["Intro"], statistics["total"])
            export_request = urllib.request.Request(base + "/api/export", data=json.dumps({"language": "zh", "card_ids": ["20250914-00052-e348d55e", "20250914-00087-832db507"]}).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(export_request) as response:
                self.assertEqual(response.headers.get_content_type(), "application/zip")
                archive = zipfile.ZipFile(io.BytesIO(response.read()))
                self.assertEqual(set(archive.namelist()), {"monster_cards.csv", "prophecy_cards.csv"})
                monster_export = archive.read("monster_cards.csv").decode("utf-8")
                prophecy_export = archive.read("prophecy_cards.csv").decode("utf-8")
                self.assertIn("20250914-00052-e348d55e", monster_export)
                self.assertIn("20250914-00087-832db507", prophecy_export)
            csv_snapshot_request = urllib.request.Request(base + "/api/export", data=json.dumps({"snapshot": True, "format": "csv", "version": ""}).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(csv_snapshot_request) as response:
                csv_snapshot = json.load(response)
                self.assertEqual(response.status, 201)
                self.assertNotIn("next_version", csv_snapshot)
                self.assertTrue((data_root / "tmp" / "monster_cards.csv").is_file())
            with urllib.request.urlopen(base + "/api/export-info") as response:
                self.assertEqual(json.load(response)["current_version"], "v3.1")
            snapshot_request = urllib.request.Request(base + "/api/export", data=json.dumps({"snapshot": True, "format": "database", "version": "v2.3"}).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(snapshot_request) as response:
                snapshot = json.load(response)
                self.assertEqual(response.status, 201)
                self.assertEqual(snapshot["files"], ["gemuworld.sqlite3"])
                self.assertEqual(snapshot["next_version"], "v3")
                self.assertTrue((data_root / "v2.3" / "gemuworld.sqlite3").is_file())
            with urllib.request.urlopen(base + "/stats") as response:
                stats_html = response.read().decode("utf-8")
                self.assertIn("/api/statistics", stats_html)
                self.assertIn("返回卡牌 Viewer", stats_html)
            with urllib.request.urlopen(base + "/import") as response:
                import_html = response.read().decode("utf-8")
                self.assertIn("/api/import", import_html)
                self.assertIn("预检", import_html)
            with urllib.request.urlopen(base + "/editor") as response:
                editor_html = response.read().decode("utf-8")
                self.assertIn("卡牌编辑器", editor_html)
                self.assertIn("/api/cards/", editor_html)
            with urllib.request.urlopen(base + "/decks") as response:
                decks_html = response.read().decode("utf-8")
                self.assertIn("卡组管理", decks_html)
                self.assertIn("/api/decks/", decks_html)
            with urllib.request.urlopen(base + "/effects") as response:
                effects_html = response.read().decode("utf-8")
                self.assertIn('id="sort"', effects_html)
                self.assertIn('<option value="text:asc">中文效果字典序</option>', effects_html)
                self.assertIn('<option value="text_length:asc">中文效果字数从少到多</option>', effects_html)
                self.assertIn('<option value="text_length:desc">中文效果字数从多到少</option>', effects_html)
                self.assertIn('id="profession"', effects_html)
                self.assertIn("effectLabels", effects_html)
                self.assertIn("detailTitle", effects_html)
                self.assertIn("<strong>${esc(detailTitle(e))}</strong>", effects_html)
                self.assertIn("估值：${e.valuation??'未设置'}", effects_html)
                self.assertNotIn('<span class="muted">#${e.id}</span>', effects_html)
                self.assertIn("所属卡牌：", effects_html)
                self.assertIn('class="profession-tags"', effects_html)
                self.assertIn('id="editing-professions"', effects_html)
                self.assertIn('style="display:flex;gap:12px"', effects_html)
                self.assertIn('<label style="width:140px">${fieldLabel(\'灵力消耗\',skill)}', effects_html)
                self.assertIn('<label style="width:140px">估值', effects_html)
                self.assertIn('<label class="wide">职业标签', effects_html)
                self.assertIn('name="marker" maxlength="10"', effects_html)
                self.assertIn('name="notes"', effects_html)
                self.assertIn("function fieldLabel(label,onCard)", effects_html)
                self.assertIn("fieldLabel('灵力消耗',skill)", effects_html)
                self.assertIn("fieldLabel('中文名称',skill)", effects_html)
                self.assertIn("fieldLabel('中文效果',true)", effects_html)
                self.assertIn("e.marker?` <span class=\"muted\">", effects_html)
                self.assertIn("data-profession=\"${esc(profession)}\"", effects_html)
                self.assertIn("professions:editingProfessions", effects_html)
                self.assertIn("addEditingProfessions", effects_html)
                self.assertIn("async function navigateEffect", effects_html)
                self.assertIn("await persistCurrent(false)", effects_html)
                self.assertIn("['ArrowUp','ArrowDown'].includes(event.key)", effects_html)
                self.assertIn("scrollIntoView({block:'nearest'})", effects_html)
                self.assertIn("/api/effect-professions", effects_html)
                self.assertIn('id="profession-summary"', effects_html)
                self.assertIn("职业词条：", effects_html)
                self.assertIn("selectedProfessions=new Set()", effects_html)
                self.assertIn("function toggleProfession", effects_html)
                self.assertIn("q.append('profession',profession)", effects_html)
                self.assertNotIn("['刺客','坦克','射手','法师','辅助'].map", effects_html)
                self.assertIn("const FIXED_PROFESSIONS=['刺客','坦克','射手','法师','辅助']", effects_html)
                self.assertIn("...stored.filter(profession=>!FIXED_PROFESSIONS.includes(profession))", effects_html)
                self.assertIn("(e.professions||[]).map", effects_html)
                self.assertIn("profession-assassin", effects_html)
                self.assertIn("background:#fecaca", effects_html)
                self.assertIn("background:#d1d5db", effects_html)
                self.assertIn("profession-tag ${professionClasses[profession]||''}", effects_html)
                self.assertNotIn('name="position"', effects_html)
                self.assertIn('id="target-search"', effects_html)
                self.assertIn("function renderTargets", effects_html)
                self.assertIn("c.card_id", effects_html)
                self.assertIn("/api/effects", effects_html)
            with urllib.request.urlopen(base + "/design-guides") as response:
                guides_html = response.read().decode("utf-8")
                self.assertIn("设计指南", guides_html)
                self.assertIn("/api/monster-benchmarks", guides_html)
            with urllib.request.urlopen(base + "/api/effects?effect_type=monster_skill") as response:
                effect_payload = json.load(response)
            with urllib.request.urlopen(base + "/api/effect-professions") as response:
                profession_payload = json.load(response)
                self.assertEqual(profession_payload["items"], sorted(profession_payload["items"], key=str.casefold))
                self.assertEqual(set(profession_payload["counts"]) - {"__unset__"}, set(profession_payload["items"]))
                self.assertIn("__unset__", profession_payload["counts"])
                self.assertTrue(all(value >= 0 for value in profession_payload["counts"].values()))
                self.assertGreater(effect_payload["count"], 0)
                self.assertTrue(all(effect["type"] == "monster_skill" for effect in effect_payload["items"]))
            with urllib.request.urlopen(base + "/api/design-guides") as response:
                self.assertGreater(json.load(response)["count"], 0)
            with urllib.request.urlopen(base + "/api/monster-benchmarks") as response:
                self.assertGreater(json.load(response)["count"], 0)
            http_deck_payload = {"code": "http-deck", "deck_type": "default", "display_order": 100, "translations": {"zh": {"name": "HTTP卡组", "summary": "", "description": "HTTP介绍"}, "en": {"name": "HTTP Deck", "summary": "", "description": "HTTP description"}}, "members": []}
            deck_create_request = urllib.request.Request(base + "/api/decks", data=json.dumps(http_deck_payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(deck_create_request) as response:
                self.assertEqual(response.status, 201)
                http_deck = json.load(response)
            deck_id = http_deck["id"]
            http_deck_payload["version"] = 1
            http_deck_payload["translations"]["zh"]["summary"] = "已更新"
            deck_update_request = urllib.request.Request(base + f"/api/decks/{deck_id}", data=json.dumps(http_deck_payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="PUT")
            with urllib.request.urlopen(deck_update_request) as response:
                self.assertEqual(json.load(response)["version"], 2)
            deck_delete_request = urllib.request.Request(base + f"/api/decks/{deck_id}?version=2&permanent=true", method="DELETE")
            with urllib.request.urlopen(deck_delete_request) as response:
                self.assertTrue(json.load(response)["deleted"])
            crud_payload = {"base": {"card_id": "http-crud-prophecy", "image": "pictures/grid.png"}, "translations": {"zh": {"title": "HTTP CRUD预言", "introduction": "测试"}, "en": {"title": "HTTP CRUD Prophecy", "introduction": "Test"}}, "effects": [{"type": "prophecy_effect", "position": 0, "translations": {"zh": {"name": "", "text": "抽一张牌。"}, "en": {"name": "", "text": "Draw a card."}}}], "deck_codes": ["Intro"]}
            create_request = urllib.request.Request(base + "/api/cards/prophecy", data=json.dumps(crud_payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(create_request) as response:
                self.assertEqual(response.status, 201)
                crud_card = json.load(response)
            crud_id = crud_card["base"]["id"]
            with urllib.request.urlopen(base + f"/api/cards/prophecy/{crud_id}") as response:
                self.assertEqual(json.load(response)["translations"]["zh"]["title"], "HTTP CRUD预言")
            crud_payload["version"] = crud_card["base"]["version"]
            crud_payload["translations"]["zh"]["introduction"] = "已更新"
            crud_payload["effects"][0]["id"] = crud_card["effects"][0]["id"]
            crud_payload["effects"][0]["version"] = crud_card["effects"][0]["version"]
            update_request = urllib.request.Request(base + f"/api/cards/prophecy/{crud_id}", data=json.dumps(crud_payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="PUT")
            with urllib.request.urlopen(update_request) as response:
                updated_crud = json.load(response)
                self.assertEqual(updated_crud["base"]["version"], 2)
            delete_request = urllib.request.Request(base + f"/api/cards/prophecy/{crud_id}?version=2&permanent=true", method="DELETE")
            with urllib.request.urlopen(delete_request) as response:
                self.assertTrue(json.load(response)["deleted"])
            preview_row = read_records(V1_ROOT / "data" / "current" / "cards" / "prophecy_cards.csv")[0]
            preview_request = urllib.request.Request(base + "/api/import", data=json.dumps({"card_type": "prophecy", "csv": render_records(PROPHECY_HEADER, [preview_row]), "dry_run": True}).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(preview_request) as response:
                preview_payload = json.load(response)
                self.assertTrue(preview_payload["dry_run"])
                self.assertEqual(preview_payload["updated_count"], 1)
            # A committed database update is visible through the running service
            # without rebuilding a CSV cache or restarting the server.
            connection = connect(self.database)
            try:
                connection.execute("UPDATE monster_card_translations SET title='即时刷新测试卡' WHERE language='zh' AND monster_card_id=(SELECT id FROM monster_cards WHERE card_id='20250914-00052-e348d55e')")
                connection.commit()
            finally:
                connection.close()
            keyword = urllib.parse.quote("即时刷新测试卡")
            with urllib.request.urlopen(base + f"/api/cards?language=zh&keyword={keyword}") as response:
                refreshed = json.load(response)
                self.assertEqual(refreshed["count"], 1)
                self.assertEqual(refreshed["items"][0]["title"], "即时刷新测试卡")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_single_type_export_preserves_query_order(self):
        connection = connect(self.database)
        try:
            cards = list_cards(connection, language="zh", card_type="monster", sort_by="title", direction="asc", limit=4)
        finally:
            connection.close()
        body, filename, content_type = export_cards(cards, "zh")
        self.assertEqual(filename, "monster_cards.csv")
        self.assertEqual(content_type, "text/csv; charset=utf-8")
        rows = body.decode("utf-8").splitlines()[1:]
        self.assertEqual([row.split("|", 2)[1] for row in rows], [card["title"] for card in cards])


class BatchImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "batch.sqlite3"
        self.connection = connect(self.database)
        migrate(self.connection)
        import_legacy(self.connection, V1_ROOT, REPOSITORY_ROOT / "GemuWorld" / "manual")

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def test_dry_run_then_overwrite_preserves_identity_and_decks(self):
        source = read_records(V1_ROOT / "data" / "current" / "cards" / "monster_cards.csv")[0].copy()
        owner = self.connection.execute("SELECT c.id,c.card_id,c.attack FROM monster_cards c JOIN monster_card_translations t ON t.monster_card_id=c.id WHERE t.language='zh' AND t.title=?", (source["card_title"],)).fetchone()
        deck_count = self.connection.execute("SELECT COUNT(*) FROM deck_cards WHERE monster_card_id=?", (owner["id"],)).fetchone()[0]
        source["card_id"] = "incoming-id-must-not-replace-stable-id"
        source["attack"] = "99"
        source["attributes"] = json.dumps({"normal_attribute": "批量覆盖属性"}, ensure_ascii=False)
        csv_text = render_records(MONSTER_HEADER, [source])
        preview = import_cards(self.connection, "monster", csv_text, dry_run=True)
        self.assertEqual(len(preview.updated), 1)
        self.assertNotEqual(self.connection.execute("SELECT attack FROM monster_cards WHERE id=?", (owner["id"],)).fetchone()[0], 99)
        result = import_cards(self.connection, "monster", csv_text)
        self.assertEqual(len(result.updated), 1)
        updated = self.connection.execute("SELECT card_id,attack FROM monster_cards WHERE id=?", (owner["id"],)).fetchone()
        self.assertEqual(updated["card_id"], owner["card_id"])
        self.assertEqual(updated["attack"], 99)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM deck_cards WHERE monster_card_id=?", (owner["id"],)).fetchone()[0], deck_count)
        effect = self.connection.execute("SELECT t.text FROM effects e JOIN effect_translations t ON t.effect_id=e.id WHERE e.monster_card_id=? AND e.effect_type='monster_attribute' AND t.language='zh'", (owner["id"],)).fetchone()
        self.assertEqual(effect["text"], "批量覆盖属性")

    def test_create_new_prophecy(self):
        row = {key: "" for key in PROPHECY_HEADER}
        row.update({"card_id": "batch-new-prophecy", "card_title": "批量导入新预言", "effect": "抽一张牌。", "image": "pictures/grid.png", "last_update_datetime": "2026-07-12 20:00:00"})
        result = import_cards(self.connection, "prophecy", render_records(PROPHECY_HEADER, [row]))
        self.assertEqual(len(result.created), 1)
        card = self.connection.execute("SELECT c.card_id,t.title FROM prophecy_cards c JOIN prophecy_card_translations t ON t.prophecy_card_id=c.id WHERE t.language='zh' AND t.title='批量导入新预言'").fetchone()
        self.assertEqual(card["card_id"], "batch-new-prophecy")

    def test_invalid_later_row_rolls_back_entire_batch(self):
        rows = read_records(V1_ROOT / "data" / "current" / "cards" / "monster_cards.csv")[:2]
        original = self.connection.execute("SELECT attack FROM monster_cards WHERE card_id=?", (rows[0]["card_id"],)).fetchone()[0]
        rows[0]["attack"] = "123"
        rows[1]["skills"] = "not-json"
        with self.assertRaises(BatchImportError):
            import_cards(self.connection, "monster", render_records(MONSTER_HEADER, rows))
        self.assertEqual(self.connection.execute("SELECT attack FROM monster_cards WHERE card_id=?", (rows[0]["card_id"],)).fetchone()[0], original)

    def test_ambiguous_existing_title_is_rejected(self):
        rows = read_records(V1_ROOT / "data" / "current" / "cards" / "monster_cards.csv")
        row = next(row for row in rows if row["card_title"] == "护法童子").copy()
        row["card_id"] = ""
        with self.assertRaisesRegex(BatchImportError, "ambiguous"):
            import_cards(self.connection, "monster", render_records(MONSTER_HEADER, [row]))

    def test_duplicate_title_is_disambiguated_by_existing_card_id(self):
        rows = [row for row in read_records(V1_ROOT / "data" / "current" / "cards" / "monster_cards.csv") if row["card_title"] == "护法童子"]
        result = import_cards(self.connection, "monster", render_records(MONSTER_HEADER, rows), dry_run=True)
        self.assertEqual(len(result.updated), 2)


class CardCrudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "crud.sqlite3"
        self.connection = connect(self.database)
        migrate(self.connection)
        import_legacy(self.connection, V1_ROOT, REPOSITORY_ROOT / "GemuWorld" / "manual")

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def payload(self, title="CRUD测试怪物"):
        return {"base": {"card_id": "crud-test-monster", "level": 1, "monster_type": "光", "attack": 7, "defence": 8, "magic": 1.5, "image": "pictures/grid.png"}, "translations": {"zh": {"title": title, "monster_type": "光", "description": "【测试种】"}, "en": {"title": "CRUD Test Monster", "monster_type": "Light", "description": "[Test]"}}, "effects": [{"type": "monster_skill", "position": 0, "energy_cost": 1, "translations": {"zh": {"name": "测试技能", "text": "抽一张牌。"}, "en": {"name": "Test Skill", "text": "Draw a card."}}}], "deck_codes": ["Intro"]}

    def test_create_update_effects_decks_and_version_conflict(self):
        created = save_card(self.connection, "monster", self.payload())
        owner_id = created["base"]["id"]
        self.assertEqual(created["base"]["version"], 1)
        self.assertEqual([deck["code"] for deck in created["decks"]], ["Intro"])
        payload = self.payload()
        payload["version"] = 1
        payload["base"]["attack"] = 12
        payload["deck_codes"] = ["Wind"]
        payload["effects"][0]["id"] = created["effects"][0]["id"]
        payload["effects"][0]["version"] = created["effects"][0]["version"]
        payload["effects"][0]["translations"]["zh"]["text"] = "抽两张牌。"
        updated = save_card(self.connection, "monster", payload, owner_id)
        self.assertEqual(updated["base"]["card_id"], "crud-test-monster")
        self.assertEqual(updated["base"]["attack"], 12)
        self.assertEqual(updated["base"]["version"], 2)
        self.assertEqual([deck["code"] for deck in updated["decks"]], ["Wind"])
        self.assertEqual(updated["effects"][0]["translations"]["zh"]["text"], "抽两张牌。")
        with self.assertRaises(VersionConflict):
            save_card(self.connection, "monster", payload, owner_id)

    def test_invalid_deck_rolls_back_aggregate(self):
        created = save_card(self.connection, "monster", self.payload())
        owner_id = created["base"]["id"]
        payload = self.payload("不应保存的新标题")
        payload["version"] = 1
        payload["deck_codes"] = ["不存在的卡组"]
        with self.assertRaises(CardWriteError):
            save_card(self.connection, "monster", payload, owner_id)
        unchanged = get_card(self.connection, "monster", owner_id)
        self.assertEqual(unchanged["translations"]["zh"]["title"], "CRUD测试怪物")
        self.assertEqual(unchanged["base"]["version"], 1)

    def test_archive_then_permanent_delete(self):
        created = save_card(self.connection, "monster", self.payload())
        owner_id = created["base"]["id"]
        delete_card(self.connection, "monster", owner_id, permanent=False, version=1)
        archived = get_card(self.connection, "monster", owner_id)
        self.assertEqual(archived["base"]["status"], "archived")
        delete_card(self.connection, "monster", owner_id, permanent=True, version=2)
        with self.assertRaises(CardWriteError):
            get_card(self.connection, "monster", owner_id)
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM effects WHERE monster_card_id=?", (owner_id,)).fetchone()[0], 0)

    def test_copy_gets_new_identity_and_independent_effects(self):
        created = save_card(self.connection, "monster", self.payload())
        copied = copy_card(self.connection, "monster", created["base"]["id"])
        self.assertNotEqual(copied["base"]["id"], created["base"]["id"])
        self.assertNotEqual(copied["base"]["card_id"], created["base"]["card_id"])
        self.assertEqual(copied["translations"]["zh"]["title"], "CRUD测试怪物副本")
        self.assertNotEqual(copied["effects"][0]["id"], created["effects"][0]["id"])
        self.assertEqual([deck["code"] for deck in copied["decks"]], ["Intro"])

    def test_effect_editor_change_invalidates_open_card_editor(self):
        created = save_card(self.connection, "monster", self.payload())
        stale_payload = self.payload()
        stale_payload["version"] = created["base"]["version"]
        stale_payload["effects"][0]["id"] = created["effects"][0]["id"]
        stale_payload["effects"][0]["version"] = created["effects"][0]["version"]
        effect = get_effect(self.connection, created["effects"][0]["id"])
        effect_payload = {"version": effect["version"], "type": effect["type"], "position": effect["position"], "energy_cost": effect["energy_cost"], "translations": effect["translations"]}
        effect_payload["translations"]["zh"]["text"] = "效果编辑器先修改"
        update_effect(self.connection, effect["id"], effect_payload)
        fresh = get_card(self.connection, "monster", created["base"]["id"])
        self.assertEqual(fresh["base"]["version"], created["base"]["version"] + 1)
        with self.assertRaises(VersionConflict):
            save_card(self.connection, "monster", stale_payload, created["base"]["id"])


class DeckCrudTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "decks.sqlite3"
        self.connection = connect(self.database)
        migrate(self.connection)
        import_legacy(self.connection, V1_ROOT, REPOSITORY_ROOT / "GemuWorld" / "manual")
        self.monster_id = self.connection.execute("SELECT id FROM monster_cards ORDER BY id LIMIT 1").fetchone()[0]
        self.prophecy_id = self.connection.execute("SELECT id FROM prophecy_cards ORDER BY id LIMIT 1").fetchone()[0]

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def payload(self):
        return {"code": "crud-deck", "deck_type": "role", "display_order": 99, "translations": {"zh": {"name": "CRUD卡组", "summary": "摘要", "description": "卡组介绍"}, "en": {"name": "CRUD Deck", "summary": "Summary", "description": "Description"}}, "members": [{"card_type": "monster", "card_id": self.monster_id, "section": "核心", "quantity": 1}, {"card_type": "prophecy", "card_id": self.prophecy_id, "section": "支援", "quantity": 2}]}

    def test_create_update_members_and_card_side_sync(self):
        created = save_deck(self.connection, self.payload())
        self.assertEqual(created["deck_type"], "role")
        self.assertEqual([member["card_type"] for member in created["members"]], ["monster", "prophecy"])
        monster = get_card(self.connection, "monster", self.monster_id)
        self.assertIn("crud-deck", [deck["code"] for deck in monster["decks"]])
        payload = self.payload()
        payload["version"] = 1
        payload["members"] = [payload["members"][1]]
        updated = save_deck(self.connection, payload, created["id"])
        self.assertEqual(updated["version"], 2)
        self.assertEqual(len(updated["members"]), 1)
        monster = get_card(self.connection, "monster", self.monster_id)
        self.assertNotIn("crud-deck", [deck["code"] for deck in monster["decks"]])
        with self.assertRaises(VersionConflict):
            save_deck(self.connection, payload, created["id"])

    def test_invalid_member_rolls_back_metadata(self):
        created = save_deck(self.connection, self.payload())
        payload = self.payload()
        payload["version"] = 1
        payload["translations"]["zh"]["name"] = "不应保存"
        payload["members"] = [{"card_type": "monster", "card_id": 999999}]
        with self.assertRaises(DeckWriteError):
            save_deck(self.connection, payload, created["id"])
        unchanged = get_deck(self.connection, created["id"])
        self.assertEqual(unchanged["translations"]["zh"]["name"], "CRUD卡组")
        self.assertEqual(unchanged["version"], 1)

    def test_archive_and_permanent_delete(self):
        created = save_deck(self.connection, self.payload())
        delete_deck(self.connection, created["id"], permanent=False, version=1)
        self.assertEqual(get_deck(self.connection, created["id"])["status"], "archived")
        delete_deck(self.connection, created["id"], permanent=True, version=2)
        with self.assertRaises(DeckWriteError):
            get_deck(self.connection, created["id"])


class EffectGuideTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.database = Path(self.temp.name) / "effects.sqlite3"
        self.connection = connect(self.database)
        migrate(self.connection)
        import_legacy(self.connection, V1_ROOT, REPOSITORY_ROOT / "GemuWorld" / "manual")

    def tearDown(self):
        self.connection.close()
        self.temp.cleanup()

    def test_effect_update_conflict_and_owner_immutability(self):
        row = self.connection.execute("SELECT id FROM effects WHERE monster_card_id IS NOT NULL AND effect_type='monster_skill' LIMIT 1").fetchone()
        effect = get_effect(self.connection, row["id"])
        payload = {"version": effect["version"], "type": effect["type"], "energy_cost": 2, "professions": ["控制", "辅助"], "valuation": 3.5, "marker": "爆发", "notes": "设计备注", "translations": effect["translations"]}
        payload["translations"]["zh"]["text"] = "V1.6更新效果"
        updated = update_effect(self.connection, effect["id"], payload)
        self.assertEqual(updated["version"], 2)
        self.assertEqual(updated["professions"], ["控制", "辅助"])
        self.assertIn("控制", list_professions(self.connection))
        self.assertEqual(profession_counts(self.connection)["控制"], 1)
        combined = list_effects(self.connection, profession=["控制", "__unset__"])
        self.assertIn(effect["id"], [value["id"] for value in combined])
        self.assertTrue(any(not value["professions"] for value in combined))
        self.assertEqual(updated["valuation"], 3.5)
        self.assertEqual(updated["marker"], "爆发")
        self.assertEqual(updated["notes"], "设计备注")
        invalid_marker = {**payload, "version": updated["version"], "marker": "超过十个字符的标记文本"}
        with self.assertRaises(EffectWriteError):
            update_effect(self.connection, effect["id"], invalid_marker)
        self.assertEqual([value["id"] for value in list_effects(self.connection, profession="控制")], [effect["id"]])
        self.assertEqual([value["id"] for value in list_effects(self.connection, profession="辅助")], [effect["id"]])
        self.assertTrue(all(not value["professions"] for value in list_effects(self.connection, profession="__unset__")))
        self.assertEqual(updated["owner"], effect["owner"])
        with self.assertRaises(VersionConflict):
            update_effect(self.connection, effect["id"], payload)

    def test_copy_effect_creates_independent_duplicate(self):
        source_id = self.connection.execute("SELECT id FROM effects WHERE effect_type='monster_skill' LIMIT 1").fetchone()[0]
        source = get_effect(self.connection, source_id)
        target_id = self.connection.execute("SELECT monster_card_id FROM effects WHERE effect_type='monster_skill' AND monster_card_id<>? GROUP BY monster_card_id LIMIT 1", (source["owner"]["id"],)).fetchone()[0]
        target_version = self.connection.execute("SELECT version FROM monster_cards WHERE id=?", (target_id,)).fetchone()[0]
        copied = copy_effect(self.connection, source_id, "monster", target_id)
        self.assertNotEqual(copied["id"], source_id)
        self.assertEqual(copied["translations"], source["translations"])
        self.assertEqual(copied["owner"]["id"], target_id)
        self.assertEqual(copied["professions"], source["professions"])
        self.assertEqual(copied["marker"], source["marker"])
        self.assertEqual(copied["notes"], source["notes"])
        self.assertEqual(copied["valuation"], source["valuation"])
        self.assertEqual(self.connection.execute("SELECT version FROM monster_cards WHERE id=?", (target_id,)).fetchone()[0], target_version + 1)
        ordered_skills = list(self.connection.execute("SELECT e.position,e.energy_cost,t.text FROM effects e JOIN effect_translations t ON t.effect_id=e.id AND t.language='zh' WHERE e.monster_card_id=? AND e.effect_type='monster_skill' ORDER BY e.position", (target_id,)))
        self.assertEqual([row["position"] for row in ordered_skills], list(range(len(ordered_skills))))
        skill_keys = [(float(row["energy_cost"] or 0), row["text"].casefold()) for row in ordered_skills]
        self.assertEqual(skill_keys, sorted(skill_keys))
        duplicates = {effect["id"]: effect["duplicate_ids"] for effect in list_effects(self.connection)}
        self.assertIn(copied["id"], duplicates[source_id])
        self.assertIn(copied["id"], get_effect(self.connection, source_id)["duplicate_ids"])
        payload = {"version": copied["version"], "type": copied["type"], "energy_cost": copied["energy_cost"], "professions": copied["professions"], "valuation": copied["valuation"], "marker": copied["marker"], "notes": copied["notes"], "translations": copied["translations"]}
        payload["translations"]["zh"]["text"] = "独立副本"
        update_effect(self.connection, copied["id"], payload)
        self.assertNotEqual(get_effect(self.connection, source_id)["translations"]["zh"]["text"], "独立副本")

    def test_effect_search_supports_exact_id(self):
        effect_id = self.connection.execute("SELECT id FROM effects ORDER BY id LIMIT 1").fetchone()[0]
        for keyword in (str(effect_id), f"#{effect_id}"):
            results = list_effects(self.connection, keyword=keyword)
            self.assertEqual([effect["id"] for effect in results], [effect_id])
        self.assertEqual(list_effects(self.connection, keyword="#999999999"), [])
        descending = list_effects(self.connection, sort_by="id", direction="desc")
        self.assertEqual([effect["id"] for effect in descending], sorted((effect["id"] for effect in descending), reverse=True))
        by_text = list_effects(self.connection, sort_by="text", direction="asc")
        text_keys = [(str(effect["translations"].get("zh", {}).get("text", "")).casefold(), effect["id"]) for effect in by_text]
        self.assertEqual(text_keys, sorted(text_keys))
        by_length = list_effects(self.connection, sort_by="text_length", direction="asc")
        length_keys = [(len(str(effect["translations"].get("zh", {}).get("text", "")).strip()), str(effect["translations"].get("zh", {}).get("text", "")).casefold(), effect["id"]) for effect in by_length]
        self.assertEqual(length_keys, sorted(length_keys))
        by_length_desc = list_effects(self.connection, sort_by="text_length", direction="desc")
        descending_length_keys = [(len(str(effect["translations"].get("zh", {}).get("text", "")).strip()), str(effect["translations"].get("zh", {}).get("text", "")).casefold(), effect["id"]) for effect in by_length_desc]
        self.assertEqual(descending_length_keys, sorted(descending_length_keys, reverse=True))
        with self.assertRaises(EffectWriteError):
            list_effects(self.connection, sort_by="unknown")

        source_id = self.connection.execute("SELECT id FROM effects WHERE effect_type='monster_skill' LIMIT 1").fetchone()[0]
        source = get_effect(self.connection, source_id)
        target_id = self.connection.execute("SELECT id FROM monster_cards WHERE id<>? LIMIT 1", (source["owner"]["id"],)).fetchone()[0]
        copied = copy_effect(self.connection, source_id, "monster", target_id)
        filtered = list_effects(self.connection, keyword=str(copied["id"]))
        self.assertIn(source_id, filtered[0]["duplicate_ids"])

    def test_guide_and_benchmark_versioned_updates(self):
        guide = list_guides(self.connection)[0]
        updated = update_guide(self.connection, guide["id"], {"version": guide["version"], "title": guide["title"] + "（更新）", "content": guide["content"] + "\n测试"})
        self.assertEqual(updated["version"], 2)
        with self.assertRaises(VersionConflict):
            update_guide(self.connection, guide["id"], {"version": 1, "title": "冲突", "content": ""})
        benchmark = list_benchmarks(self.connection)[0]
        benchmark["attack_max"] = float(benchmark["attack_max"]) + 1
        saved = update_benchmark(self.connection, benchmark["id"], benchmark)
        self.assertEqual(saved["version"], 2)


if __name__ == "__main__":
    unittest.main()
