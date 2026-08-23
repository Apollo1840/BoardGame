from __future__ import annotations

import json
import io
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.error
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
from gemuworld_db.cards import CardWriteError, VersionConflict, copy_card, delete_card, get_card, list_monster_types, save_card  # noqa: E402
from gemuworld_db.decks import DeckWriteError, delete_deck, get_deck, save_deck  # noqa: E402
from gemuworld_db.effect_backups import export_effect_backup, export_pure_effects, import_effect_backup, import_pure_effects  # noqa: E402
from gemuworld_db.effects import EffectWriteError, copy_effect, create_effect, delete_effect, get_effect, list_effects, list_professions, profession_counts, update_effect  # noqa: E402
from gemuworld_db.guides import list_benchmarks, list_guides, list_monster_design_rows, update_benchmark, update_guide  # noqa: E402
from gemuworld_db.image_paths import card_image_path, image_url, legacy_image_path, normalize_image_path  # noqa: E402
from gemuworld_db.image_renamer import PNG_SIGNATURE, apply_image_renames, plan_image_renames  # noqa: E402
from gemuworld_db.legacy import MONSTER_HEADER, PROPHECY_HEADER  # noqa: E402
from gemuworld_db.profession_deck_sync import sync_profession_decks  # noqa: E402


class PipeCsvTests(unittest.TestCase):
    def test_escaped_pipe_newline_and_backslash(self):
        self.assertEqual(parse_line(r"a|b\|c|line\nnext|slash\\end"), ["a", "b|c", r"line\nnext", "slash\\end"])


class StatisticsTests(unittest.TestCase):
    def test_deck_coverage_excludes_profession_decks(self):
        cards = [
            {"type": "prophecy", "introduction": "", "effects": [], "decks": [{"name": "刺客", "type": "role"}]},
            {"type": "prophecy", "introduction": "", "effects": [], "decks": [{"name": "梦汐岛", "type": "story"}]},
            {"type": "prophecy", "introduction": "", "effects": [], "decks": [{"name": "坦克", "type": "role"}, {"name": "风", "type": "attribute"}]},
        ]
        statistics = compute_statistics(cards)
        self.assertEqual(statistics["cards_without_decks"], 1)
        self.assertEqual(statistics["deck_distribution"], {"刺客": 1, "梦汐岛": 1, "坦克": 1, "风": 1})


class MigrationTests(unittest.TestCase):
    def test_migrations_are_repeatable_and_effect_owner_is_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = connect(Path(directory) / "test.sqlite3")
            self.assertEqual(migrate(connection), ["001_initial.sql", "002_deck_versions.sql", "003_effect_guide_versions.sql", "004_effect_role_valuation.sql", "005_app_settings.sql", "006_effect_profession.sql", "007_effect_professions.sql", "008_effect_marker_notes.sql", "009_unassigned_effect_library.sql", "010_canonical_image_paths.sql", "011_lock_card_image_paths.sql", "012_effect_field_capabilities.sql", "013_allow_effect_detach.sql", "014_deck_stable_ids.sql", "015_deck_profession_matrices.sql", "016_expand_deck_types.sql", "017_deck_chinese_names.sql", "018_card_design_notes.sql", "019_effect_tactical_tags.sql", "020_card_serial_numbers.sql"])
            self.assertEqual(migrate(connection), [])
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(decks)")}
            self.assertIn("deck_id", columns)
            self.assertIn("design_notes", {row["name"] for row in connection.execute("PRAGMA table_info(monster_cards)")})
            self.assertIn("design_notes", {row["name"] for row in connection.execute("PRAGMA table_info(prophecy_cards)")})
            self.assertIn("serial_number", {row["name"] for row in connection.execute("PRAGMA table_info(monster_cards)")})
            self.assertIn("serial_updated_at", {row["name"] for row in connection.execute("PRAGMA table_info(prophecy_cards)")})
            self.assertIn("effect_tactical_tags", {row["name"] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")})
            monster = connection.execute("INSERT INTO monster_cards(card_id,level,attack,defence,magic,image_path) VALUES ('m1',0,1,1,1,'pics/m1.png')").lastrowid
            other = connection.execute("INSERT INTO monster_cards(card_id,level,attack,defence,magic,image_path) VALUES ('m2',0,1,1,1,'pics/m2.png')").lastrowid
            effect = connection.execute("INSERT INTO effects(monster_card_id,effect_type) VALUES (?, 'monster_skill')", (monster,)).lastrowid
            with self.assertRaises(sqlite3.IntegrityError):
                connection.execute("UPDATE effects SET monster_card_id=? WHERE id=?", (other, effect))
            connection.execute("UPDATE effects SET monster_card_id=NULL WHERE id=?", (effect,))
            self.assertIsNone(connection.execute("SELECT monster_card_id FROM effects WHERE id=?", (effect,)).fetchone()[0])
            connection.close()

    def test_image_paths_have_one_canonical_database_form(self):
        self.assertEqual(normalize_image_path("pictures/coreblossom.png"), "pics/coreblossom.png")
        self.assertEqual(normalize_image_path(r"D:\anywhere\data\current\pics\coreblossom.png"), "pics/coreblossom.png")
        self.assertEqual(normalize_image_path("coreblossom.png"), "pics/coreblossom.png")
        self.assertEqual(image_url("pics/coreblossom.png"), "/pics/coreblossom.png")
        self.assertEqual(legacy_image_path("pics/coreblossom.png"), "pictures/coreblossom.png")
        self.assertEqual(card_image_path("card-123"), "pics/card-123.png")
        with self.assertRaises(ValueError):
            normalize_image_path("pics/../outside.png")

    def test_image_rename_batch_copies_shared_sources_and_locks_missing_images(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pics = root / "pics"
            pics.mkdir()
            connection = connect(root / "test.sqlite3")
            migrate(connection)
            monster_id = connection.execute("INSERT INTO monster_cards(card_id,level,attack,defence,magic,image_path) VALUES ('monster-a',0,1,1,0,'pics/monster-a.png')").lastrowid
            prophecy_id = connection.execute("INSERT INTO prophecy_cards(card_id,image_path) VALUES ('prophecy-a','pics/prophecy-a.png')").lastrowid
            missing_id = connection.execute("INSERT INTO prophecy_cards(card_id,image_path) VALUES ('prophecy-missing','pics/prophecy-missing.png')").lastrowid
            connection.execute("DROP TRIGGER monster_card_image_path_locked_update")
            connection.execute("DROP TRIGGER prophecy_card_image_path_locked_update")
            connection.execute("UPDATE monster_cards SET image_path='pics/shared.png' WHERE id=?", (monster_id,))
            connection.execute("UPDATE prophecy_cards SET image_path='pics/shared.png' WHERE id=?", (prophecy_id,))
            connection.commit()
            (pics / "shared.png").write_bytes(PNG_SIGNATURE + b"test")
            plan = plan_image_renames(connection, pics)
            self.assertFalse(plan["errors"])
            self.assertEqual(plan["copy_count"], 2)
            self.assertEqual(plan["missing_count"], 1)
            result = apply_image_renames(connection, pics, root / "tmp")
            self.assertEqual(result["copied"], 2)
            self.assertTrue((pics / "monster-a.png").is_file())
            self.assertTrue((pics / "prophecy-a.png").is_file())
            self.assertFalse((pics / "shared.png").exists())
            self.assertFalse((pics / "prophecy-missing.png").exists())
            self.assertEqual(connection.execute("SELECT image_path FROM monster_cards WHERE id=?", (monster_id,)).fetchone()[0], "pics/monster-a.png")
            self.assertEqual(connection.execute("SELECT image_path FROM prophecy_cards WHERE id=?", (missing_id,)).fetchone()[0], "pics/prophecy-missing.png")
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
                serials1 = {
                    (card_type, row["card_id"]): row["serial_number"]
                    for card_type in ("monster", "prophecy")
                    for row in connection.execute(f"SELECT card_id,serial_number FROM {card_type}_cards")
                }
                report2 = import_legacy(connection, V1_ROOT, REPOSITORY_ROOT / "GemuWorld" / "manual")
                counts2 = {table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in counts1}
                serials2 = {
                    (card_type, row["card_id"]): row["serial_number"]
                    for card_type in ("monster", "prophecy")
                    for row in connection.execute(f"SELECT card_id,serial_number FROM {card_type}_cards")
                }
                self.assertEqual(counts1, counts2)
                self.assertEqual(serials1, serials2)
                self.assertEqual(report1.counts, report2.counts)
                self.assertFalse(report1.errors, json.dumps(report1.errors, ensure_ascii=False, indent=2))
                monster_guide = connection.execute("SELECT title,content,source_path FROM design_guides WHERE code='monster_design_table'").fetchone()
                monster_guide_source = REPOSITORY_ROOT / "GemuWorld" / "manual" / "monster_design_table.md"
                self.assertEqual(monster_guide["title"], "怪物设计表")
                self.assertEqual(monster_guide["source_path"], "monster_design_table.md")
                self.assertEqual(monster_guide["content"], monster_guide_source.read_text(encoding="utf-8-sig"))
                design_rows = list_monster_design_rows(connection)
                self.assertGreater(len(design_rows), 0)
                self.assertEqual(design_rows[0]["level"], 0)
                self.assertEqual(design_rows[0]["total_stats"], 10)
                self.assertEqual(design_rows[0]["attack_limit"], "(-1) 9")
                self.assertEqual(design_rows[0]["attack_max"], 9)
                self.assertIsNone(design_rows[0]["one_bonus"])

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
                            elif key == "image":
                                self.assertEqual(f"pictures/{card_id}.png", actual_row[key], f"{filename}:{card_id}:{key}")
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
            self.assertTrue(all("professions" in effect for card in zh for effect in card["effects"]))
            intro = list_cards(connection, language="zh", deck_codes=["Intro"])
            self.assertTrue(intro)
            self.assertTrue(all(any(deck["code"] == "Intro" for deck in card["decks"]) for card in intro))
            self.assertEqual([card["title"] for card in zh], sorted(card["title"] for card in zh))
            decks = list_decks(connection)
            self.assertEqual(len(decks), 27)
            self.assertEqual(len({deck["deck_id"] for deck in decks}), len(decks))
            self.assertTrue(all(deck["deck_id"].startswith("deck-") for deck in decks))
            self.assertEqual(len([deck for deck in decks if deck["type"] == "role"]), 5)
            deck_types = {deck["code"]: deck["type"] for deck in decks}
            self.assertEqual(deck_types["Intro"], "story")
            self.assertEqual(deck_types["Thunder"], "attribute")
            self.assertEqual(deck_types["Frost"], "tribe")
            self.assertEqual(deck_types["Human"], "tribe")
            self.assertEqual(deck_types["Goblin"], "race")
            self.assertEqual(deck_types["Poker"], "culture")
            self.assertEqual(deck_types["Party"], "story")
            deck_names = {deck["code"]: deck["name"] for deck in decks}
            self.assertEqual(deck_names["Intro"], "灵坛村")
            self.assertEqual(deck_names["Sea"], "水")
            self.assertEqual(deck_names["Frost"], "北境霜毒")
            self.assertEqual(deck_names["Human"], "将军城")
            self.assertEqual(deck_names["Goblin"], "哥布林族")
            self.assertEqual(deck_names["WalkingDead"], "不死族")
            self.assertEqual(deck_names["3kings"], "三国")
            self.assertEqual(deck_names["Party"], "梦汐岛")
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
                self.assertEqual(json.load(response)["version"], "1.15.0")
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
                self.assertTrue(all(card["image_path"].startswith("pics/") for card in payload["items"]))
                self.assertTrue(all(card["image"].startswith("/pics/") for card in payload["items"]))
            with urllib.request.urlopen(base + "/api/cards?language=zh&card_type=monster") as response:
                monster_payload = json.load(response)
                listed_effect = next(effect for card in monster_payload["items"] for effect in card["effects"])
                self.assertIn("valuation", listed_effect)
                listed_membership = next(deck for card in monster_payload["items"] for deck in card["decks"])
                self.assertIn("quantity", listed_membership)
            with urllib.request.urlopen(base + "/api/cards?language=zh&card_type=all&deck=virtual-unassigned") as response:
                unassigned_payload = json.load(response)
                self.assertGreater(unassigned_payload["count"], 0)
                self.assertTrue(all(not any(deck["type"] != "role" for deck in card["decks"]) for card in unassigned_payload["items"]))
            with urllib.request.urlopen(base + "/viewer") as response:
                html = response.read().decode("utf-8")
                self.assertIn("--cols: 3", html)
                self.assertIn("@media print", html)
                self.assertIn("#sidebar-panel #btn-print{ background:#7c3aed; }", html)
                self.assertIn("#sidebar-panel #btn-print:hover{ background:#6d28d9; }", html)
                self.assertIn("grid-template-columns: repeat(var(--cols), var(--card-w))", html)
                self.assertIn("height:100vh; height:100dvh", html)
                self.assertIn("height:100vh; height:100dvh; width:280px", html)
                self.assertIn('id="main-content"', html)
                self.assertIn('id="sidebar-collapse" class="sidebar-toggle"', html)
                self.assertIn('id="sidebar-expand" class="sidebar-toggle"', html)
                self.assertIn('id="sidebar-refresh" class="sidebar-toggle"', html)
                self.assertIn("body.sidebar-collapsed #sidebar-panel{ transform:translateX(-100%); }", html)
                self.assertIn("body.sidebar-collapsed #sidebar-expand,body.sidebar-collapsed #sidebar-refresh", html)
                self.assertIn("body.sidebar-collapsed #main-content{ margin-left:0; }", html)
                self.assertIn("function setSidebarCollapsed(collapsed)", html)
                self.assertIn("async function refreshFromCollapsedSidebar()", html)
                self.assertIn("document.getElementById('sidebar-refresh').onclick=refreshFromCollapsedSidebar", html)
                self.assertIn("localStorage.setItem('viewer-sidebar-collapsed'", html)
                self.assertIn("#sidebar-panel,#sidebar-expand,#sidebar-refresh{ display:none!important; }", html)
                self.assertIn("box-sizing:border-box; overflow-y:auto; overflow-x:hidden", html)
                self.assertIn("/api/cards", html)
                self.assertIn("/api/decks", html)
                self.assertIn("${obj.attack??''}", html)
                self.assertIn("${obj.defence??''}", html)
                self.assertNotIn("${obj.attack||''}", html)
                self.assertNotIn("${obj.defence||''}", html)
                self.assertIn('<option value="updated_at">', html)
                self.assertIn("const prophecyHeader=['card_id','card_title','introduction','effect','responsive_effect','image','serial_number','updated_at']", html)
                self.assertIn("const monsterHeader=['card_id','card_title','level','monster_type','description','attack','defence','magic','attributes','skills','image','serial_number','updated_at']", html)
                self.assertIn('class="card-serial"', html)
                self.assertIn("position:absolute; left:4px; right:4px; bottom:1px", html)
                self.assertIn("writing-mode:horizontal-tb", html)
                self.assertIn("font:700 5px/4px monospace", html)
                self.assertIn("function stretchCardSerial(serial)", html)
                self.assertIn("(targetWidth-naturalWidth)/(characters-1)", html)
                self.assertIn("ctr.querySelectorAll('.card-serial').forEach(stretchCardSerial)", html)
                self.assertIn(".card.monster .card-serial{ color:#d9d9d9; }", html)
                self.assertIn(".card.prophecy .card-serial{ color:#fff; }", html)
                self.assertIn("const UNASSIGNED_DECK_ID='virtual-unassigned'", html)
                self.assertIn("name:'无归属'", html)
                self.assertIn("some(deck=>deck.type!=='role')", html)
                self.assertIn("if(field==='updated_at')", html)
                self.assertIn("return bDate-aDate", html)
                self.assertIn("sortField==='updated_at'", html)
                self.assertIn('<input type="radio" name="format" value="database" checked> 数据库', html)
                self.assertIn('<input type="radio" name="format" value="csv"> CSV', html)
                self.assertNotIn('value="update_datetime"', html)
                self.assertNotIn("loadCSVWithHeader", html)
                self.assertNotIn("prophecy_cards_en.csv?t=", html)
                self.assertNotIn("clans/_clans.json", html)
            with urllib.request.urlopen(base + "/monster_cards.csv") as response:
                self.assertEqual(response.readline().decode("utf-8").strip().split("|")[0], "card_id")
            with urllib.request.urlopen(base + "/pictures/20250914-00052-e348d55e.png") as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), "image/png")
                self.assertGreater(int(response.headers["Content-Length"]), 0)
            with urllib.request.urlopen(base + "/pics/20250914-00052-e348d55e.png") as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), "image/png")
            with urllib.request.urlopen(base + "/api/statistics?language=zh&deck=Intro") as response:
                statistics = json.load(response)["statistics"]
                self.assertGreater(statistics["total"], 0)
                self.assertEqual(statistics["deck_distribution"]["灵坛村"], statistics["total"])
            with urllib.request.urlopen(base + "/api/statistics?language=zh&deck=virtual-unassigned") as response:
                unassigned_statistics = json.load(response)["statistics"]
                self.assertEqual(unassigned_statistics["total"], unassigned_payload["count"])
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
                self.assertIn('href="/viewer"', stats_html)
                self.assertIn('<option value="virtual-unassigned">无归属 (${unassigned.count})</option>', stats_html)
                self.assertIn("deck=virtual-unassigned", stats_html)
                self.assertIn("unassigned=Number(s.cards_without_decks)||0", stats_html)
                self.assertIn("['无归属',unassigned,'未加入任何非职业卡组']", stats_html)
            with urllib.request.urlopen(base + "/import") as response:
                import_html = response.read().decode("utf-8")
                self.assertIn("/api/import", import_html)
                self.assertIn("预检", import_html)
            with urllib.request.urlopen(base + "/editor") as response:
                editor_html = response.read().decode("utf-8")
                self.assertIn("卡牌编辑器", editor_html)
                self.assertIn("/api/cards/", editor_html)
                self.assertIn("magicDifference=cardMagicDifference(card)", editor_html)
                self.assertIn("magic=Number(magicDifference)===0?'':", editor_html)
                self.assertIn('class="magic-pill" title="实效魔力 − 魔力">${esc(magicDifference)}', editor_html)
                self.assertIn('class="prophecy-valuation-pill" title="${esc(valuation.formula)}">${esc(formatEstimate(valuation.value))}', editor_html)
                self.assertIn('.prophecy-valuation-pill{', editor_html)
                self.assertIn("function cardEffectiveMagic(card)", editor_html)
                self.assertIn("function cardMagicDifference(card)", editor_html)
                self.assertIn("cardEffectiveMagic(card)-(Number(card.magic)||0)", editor_html)
                self.assertIn(".toFixed(1)", editor_html)
                self.assertNotIn("effectiveMagic!==0", editor_html)
                self.assertIn("['effective_magic:desc','实效魔力从高到低']", editor_html)
                self.assertIn("['effective_magic:asc','实效魔力从低到高']", editor_html)
                self.assertIn("sortKey==='effective_magic'", editor_html)
                self.assertIn("['monster_valuation:desc','怪物卡估值从高到低']", editor_html)
                self.assertIn("['monster_valuation:asc','怪物卡估值从低到高']", editor_html)
                self.assertIn("sortKey==='monster_valuation'", editor_html)
                self.assertIn("left=Number(cardMagicDifference(a));right=Number(cardMagicDifference(b))", editor_html)
                self.assertIn("['prophecy_valuation:desc','预言估值从高到低']", editor_html)
                self.assertIn("['prophecy_valuation:asc','预言估值从低到高']", editor_html)
                self.assertIn("sortKey==='prophecy_valuation'", editor_html)
                self.assertIn("left=cardProphecyValuation(a);right=cardProphecyValuation(b)", editor_html)
                self.assertIn("return left==null?1:-1", editor_html)
                self.assertIn("$('sort').onchange=renderList", editor_html)
                self.assertIn("'★'.repeat(Math.max(0,Math.floor(Number(card.level)||0)))", editor_html)
                self.assertIn('class="level-stars" title="Lv${esc(card.level)}"', editor_html)
                self.assertIn("(${esc(card.attack)}/${esc(card.defence)})", editor_html)
                self.assertIn('class="indicator-row">${indicators}</div></div></div>', editor_html)
                self.assertIn("function hasMonsterDescription(description)", editor_html)
                self.assertIn("replace(/^\\s*【[^】]*种】\\s*/,'')", editor_html)
                self.assertIn("hasMonsterDescription(card.description)?indicator('description'", editor_html)
                self.assertIn("if(content==='description')return card.type==='monster'&&hasMonsterDescription(card.description)", editor_html)
                self.assertIn("if(content==='introduction')return card.type==='prophecy'&&Boolean(card.introduction?.trim())", editor_html)
                self.assertIn("function prophecyKind(introduction)", editor_html)
                self.assertIn("function isPermanentProphecy(introduction)", editor_html)
                self.assertIn("effectIndicators(card,'monster_attribute','attribute','通常属性')", editor_html)
                self.assertIn("effectIndicators(card,'monster_reactive_attribute','reactive','反应属性')", editor_html)
                self.assertIn("effectIndicators(card,'monster_skill','skill','技能')", editor_html)
                self.assertIn("effectIndicators(card,'prophecy_effect','prophecy','预言效果')", editor_html)
                self.assertIn("effectIndicators(card,'prophecy_reactive_effect','prophecy-reactive','预言响应效果')", editor_html)
                self.assertNotIn('<div class="muted">${esc(c.card_id)}</div>', editor_html)
                self.assertIn('id="filter-value"', editor_html)
                self.assertIn('<option value="all">全部</option>', editor_html)
                self.assertIn("card_type=${type}", editor_html)
                self.assertIn("else if(prophecy)", editor_html)
                self.assertIn("setSelectOptions('filter-value',[['','全部卡牌']],true)", editor_html)
                self.assertIn("['type:asc','卡牌类型']", editor_html)
                self.assertIn("if(type==='all'){alert('请先选择怪物或预言，再添加卡牌。');return}", editor_html)
                self.assertIn('id="filter-content"', editor_html)
                self.assertIn("initialCardParams=new URLSearchParams(location.search)", editor_html)
                self.assertIn("await openCard(initialCardType,initialCardId)", editor_html)
                self.assertIn('id="filter-deck"', editor_html)
                self.assertIn('id="filter-primary-profession"', editor_html)
                self.assertIn("function cardPrimaryProfessions(card)", editor_html)
                self.assertIn("effectEditor.cardProfessionGroups(card).primary", editor_html)
                self.assertIn("['__unset__','未设置主职业']", editor_html)
                self.assertIn("primaryProfession=$('filter-primary-profession').value", editor_html)
                self.assertIn("!primaryProfessions.includes(primaryProfession)", editor_html)
                self.assertIn("$('filter-primary-profession').onchange=renderList", editor_html)
                self.assertIn("'<option value=\"\">全部卡组</option>'", editor_html)
                self.assertIn("deckId=$('filter-deck').value", editor_html)
                self.assertIn("deck.deck_id===deckId", editor_html)
                self.assertIn("$('filter-deck').onchange=renderList", editor_html)
                self.assertIn('id="sort"', editor_html)
                self.assertIn('id="query">查询</button>', editor_html)
                self.assertIn('id="new">添加卡牌</button>', editor_html)
                self.assertIn("function filteredCards()", editor_html)
                self.assertIn("图片路径已锁定为 pics/", editor_html)
                self.assertNotIn('name="image"', editor_html)
                self.assertNotIn("form.image", editor_html)
                self.assertIn('class="effect-head"><h3 class="effect-title"', editor_html)
                self.assertIn('class="secondary unlink-effect">解绑</button><button type="button" class="danger delete-effect">删除</button>', editor_html)
                self.assertIn("function unlinkEffectRow(row)", editor_html)
                self.assertIn("async function deleteEffectRow(row)", editor_html)
                self.assertIn("function unlinkEffectRow(row){removeEffectRow(row)}", editor_html)
                self.assertIn("该卡效会从当前卡牌和数据库中永久删除", editor_html)
                self.assertIn('class="effect-detail-grid"', editor_html)
                self.assertIn('class="profession-tags selected-professions"', editor_html)
                self.assertIn('class="profession-tags preset-professions"', editor_html)
                self.assertIn('class="profession-tags selected-tactical-tags"', editor_html)
                self.assertIn('class="profession-tags preset-tactical-tags"', editor_html)
                self.assertIn("TACTICAL_TAG_PRESETS=['输出','输入','转换','追击','反制']", editor_html)
                self.assertIn("function bindEffectRow(row)", editor_html)
                self.assertIn('id="undo-card"', editor_html)
                self.assertIn("function requestCardSave", editor_html)
                self.assertIn("function flushCardSave", editor_html)
                self.assertIn("addEventListener('focusout'", editor_html)
                self.assertNotIn('<button type="submit">保存</button>', editor_html)
                self.assertIn("function addRowProfessions(row,text)", editor_html)
                self.assertIn("professions:rowProfessions(row)", editor_html)
                self.assertIn("tactical_tags:rowTacticalTags(row)", editor_html)
                self.assertIn("loadProfessions()", editor_html)
                self.assertNotIn('class="profession" value=', editor_html)
                self.assertIn("['monster_skill','有技能']", editor_html)
                self.assertIn("['prophecy_reactive_effect','有响应效果']", editor_html)
                self.assertIn("['kind:asc','特殊种类正序']", editor_html)
                self.assertIn('src="/effect-editor-shared.js"', editor_html)
                self.assertIn('id="effect-library-select"', editor_html)
                self.assertIn('effectEditor.compactText(zh.text,36)', editor_html)
                self.assertIn('function effectFromRow(row)', editor_html)
                self.assertIn('中文属性<select name="monster_type">', editor_html)
                self.assertIn("monsterTypeOptions(b.monster_type)", editor_html)
                self.assertNotIn('name="en_monster_type"', editor_html)
                self.assertIn("英文属性将依据中文属性自动翻译", editor_html)
                self.assertIn("<h2>${monster?'属性与技能':'效果编辑'}</h2>", editor_html)
                self.assertIn('class="grid monster-detail-grid"', editor_html)
                self.assertIn('<span class="card-stable-id">${esc(b.card_id||\'保存后自动生成 card_id\')}</span>', editor_html)
                self.assertIn('id="copy-card-id" class="copy-card-id"', editor_html)
                self.assertIn(".copy-card-id{align-self:center;padding:3px;border:0;border-radius:0;background:#fff", editor_html)
                self.assertIn("navigator.clipboard?.writeText", editor_html)
                self.assertIn("async function copyCardId()", editor_html)
                self.assertIn("button.textContent='✓'", editor_html)
                self.assertIn("button.textContent='⧉'", editor_html)
                self.assertNotIn('name="card_id"', editor_html)
                self.assertIn('等级<input name="level"', editor_html)
                self.assertIn('等级<input name="level" type="number" min="0" value="${esc(b.level)}"></label><label>中文卡名', editor_html)
                self.assertIn('中文卡名<input name="zh_title" required value="${esc(zh.title)}"></label><label>英文卡名', editor_html)
                self.assertIn('英文卡名<input name="en_title" value="${esc(en.title)}"></label><label>中文属性', editor_html)
                self.assertIn('魔力 <span id="effective-magic-estimate" class="magic-effective-value" title="实效魔力 = 通常属性估值 + 反应属性估值 + 技力估值">(—)</span>', editor_html)
                self.assertIn("effectiveMagic.textContent=`(${formatEstimate(values.effectiveMagic)})`", editor_html)
                self.assertIn("card_id:current.base.card_id", editor_html)
                self.assertIn('技力估值<input id="skill-valuation-estimate" class="computed-field" title="技力估值 = max(每个技能的估值 - 该技能的灵力消耗, 0)" readonly>', editor_html)
                self.assertIn('怪物卡估值<input id="monster-card-valuation" class="computed-field" title="怪物卡估值 = 实效魔力 - 魔力" readonly>', editor_html)
                self.assertIn("monsterValuation=$('monster-card-valuation')", editor_html)
                self.assertIn("monsterValuation.value=(values.effectiveMagic-(Number(form.magic?.value)||0)).toFixed(1)", editor_html)
                self.assertIn('预言估值<input id="prophecy-valuation-estimate" class="computed-field"', editor_html)
                self.assertIn('主职业<input id="primary-professions" class="computed-field" title="${esc(primaryDefinition)}" readonly>', editor_html)
                self.assertIn('副职业<input id="secondary-professions" class="computed-field" title="${esc(secondaryDefinition)}" readonly>', editor_html)
                self.assertIn("primaryDefinition=monster?'主职业 = 通常属性职业 + 灵力消耗 ≤ 0 的技能职业；攻击 > (等级 + 1) × 5 时加入刺客；防御 > (等级 + 1) × 5 时加入坦克':'主职业 = 预言效果的职业集合'", editor_html)
                self.assertIn("secondaryDefinition=monster?'副职业 = 反应属性职业 + 灵力消耗 > 0 的技能职业':'副职业 = 预言响应效果的职业集合'", editor_html)
                self.assertIn('.computed-field{background:#e5e7eb;color:#59636c', editor_html)
                self.assertIn('cursor:not-allowed', editor_html)
                self.assertIn("function effectEstimateValues(effects)", editor_html)
                self.assertIn("function prophecyValuationDetails(effects,permanent=false)", editor_html)
                self.assertIn("deduction=permanent?1:2", editor_html)
                self.assertIn("highest=Math.max(...all)", editor_html)
                self.assertIn("combined=permanent?sum:highest", editor_html)
                self.assertIn("value:(combined-deduction)*1.2", editor_html)
                self.assertIn("permanent?'全部效果估值之和':'最高卡效估值'", editor_html)
                self.assertIn("value:highest-deduction", editor_html)
                self.assertIn("isPermanentProphecy(card.introduction)", editor_html)
                self.assertIn("isPermanentProphecy(form.zh_introduction?.value)", editor_html)
                self.assertIn("effect.type==='monster_attribute'||effect.type==='monster_reactive_attribute'", editor_html)
                self.assertIn("Math.max(...skillValues,0)", editor_html)
                self.assertIn("attributeValuation+skillValuation", editor_html)
                self.assertIn("effectProfessionGroups=effectEditor.effectProfessionGroups", editor_html)
                self.assertIn("monsterStatProfessions=effectEditor.monsterStatProfessions", editor_html)
                self.assertIn("primaryProfessions=new Set(groups.primary)", editor_html)
                self.assertIn("updateCardEffectSummary()", editor_html)
                self.assertIn("monsterEffectLimits={monster_attribute:1,monster_reactive_attribute:1,monster_skill:3}", editor_html)
                self.assertIn("添加效果（已达上限）", editor_html)
                self.assertIn("cardHasSaveError", editor_html)
                self.assertIn("button.onmousedown=event=>event.preventDefault()", editor_html)
                self.assertIn("卡牌、翻译、卡组关系及其已链接卡效都会从数据库删除", editor_html)
                self.assertIn('设计笔记<textarea name="design_notes"', editor_html)
                self.assertIn('仅供设计与编辑使用，不会渲染到卡面', editor_html)
                self.assertIn("design_notes:form.design_notes.value", editor_html)
                self.assertIn("professionText=(effect.professions||[]).join('、')||'未设置职业'", editor_html)
                self.assertIn("compactText(zh.text,36)||'无简述'", editor_html)
                self.assertIn("${esc(title)} - ${esc(professionText)} - ${esc(summary)}", editor_html)
                self.assertIn('/api/monster-design-table', editor_html)
                self.assertIn('id="attack-budget" class="stat-budget"', editor_html)
                self.assertIn('id="defence-budget" class="stat-budget"', editor_html)
                self.assertIn("function setBudgetHeadingState(element,value=null)", editor_html)
                self.assertIn("value!==null&&value>0", editor_html)
                self.assertIn("value!==null&&value<0", editor_html)
                self.assertIn("setBudgetHeadingState(attack,remaining)", editor_html)
                self.assertIn("setBudgetHeadingState(defence,remaining)", editor_html)
                self.assertIn(".field-heading.budget-positive", editor_html)
                self.assertIn(".field-heading.budget-negative", editor_html)
                self.assertIn("color:#17803d;font-weight:700", editor_html)
                self.assertIn("color:#c62828;font-weight:700", editor_html)
                self.assertIn('function monsterDesignMatch(level,effectCount,magic,effectiveMagic)', editor_html)
                self.assertIn("effectCount===0){const zeroBonus=rows.find(row=>row.one_bonus===null||row.one_bonus==='')", editor_html)
                self.assertIn('0增匹配“1增配置”为 - 的最上行', editor_html)
                self.assertIn('Math.round((Number(effectiveMagic)||0)*2)/2', editor_html)
                self.assertIn('多行命中时取最上行', editor_html)
                self.assertIn("attackLimit=match.row.attack_max==null?'-':formatEstimate(match.row.attack_max)", editor_html)
                self.assertIn("defenceLimit=match.row.defence_max==null?'-':formatEstimate(match.row.defence_max)", editor_html)
                self.assertNotIn('${match.row.attack_limit}', editor_html)
                self.assertNotIn('${match.row.defence_limit}', editor_html)
                self.assertIn('updateMonsterStatBudget(effects,values.effectiveMagic)', editor_html)
            with urllib.request.urlopen(base + "/decks") as response:
                decks_html = response.read().decode("utf-8")
                self.assertIn("卡组管理", decks_html)
                self.assertIn("/api/decks/", decks_html)
                self.assertIn("function monsterLevelCounts()", decks_html)
                self.assertIn("renderMonsterLevelStats()", decks_html)
                self.assertIn('class="member-level-stars"', decks_html)
                self.assertIn("'★'.repeat(Math.max(0,Math.floor(Number(level)||0)))", decks_html)
                self.assertIn('id="monster-level-chart"', decks_html)
                self.assertIn("total=counts.reduce((sum,[,count])=>sum+count,0)", decks_html)
                self.assertIn('class="monster-level-total">/${total}张', decks_html)
                self.assertIn('.monster-level-total{', decks_html)
                self.assertIn("卡组职业分析", decks_html)
                self.assertIn("卡组战术分析", decks_html)
                self.assertIn('id="deck-type-filter"', decks_html)
                self.assertIn('id="deck-sort"', decks_html)
                self.assertIn('<option value="valuation:desc">', decks_html)
                self.assertIn('<option value="valuation:asc">', decks_html)
                self.assertIn('<option value="updated_at:desc">', decks_html)
                self.assertIn('id="deck-search"', decks_html)
                self.assertIn('id="deck-query"', decks_html)
                self.assertIn("function renderDeckTypeFilter()", decks_html)
                self.assertIn("function filteredDecks()", decks_html)
                self.assertIn('class="deck-valuation-pill"', decks_html)
                self.assertIn("function cardValuation(card)", decks_html)
                self.assertIn('class="member-valuation ${valuationClass}"', decks_html)
                self.assertIn("valuation>0?'positive':valuation<0?'negative':''", decks_html)
                self.assertIn(".member-valuation.positive{color:#17803d}", decks_html)
                self.assertIn(".member-valuation.negative{color:#c62828}", decks_html)
                self.assertIn("valuation.toFixed(1)", decks_html)
                self.assertIn("?'--':valuation.toFixed(1)", decks_html)
                self.assertIn("grid-template-columns:44px 58px minmax(180px,1fr)", decks_html)
                self.assertIn("function deckValuationDetails(deck)", decks_html)
                self.assertIn("valuation.value.toFixed(2)", decks_html)
                self.assertIn("total+=valuation*quantity", decks_html)
                self.assertIn("const totalCount=valuedCount+missingCount", decks_html)
                self.assertIn("value:totalCount?total/totalCount:null", decks_html)
                self.assertIn("缺少估值按 0 计算", decks_html)
                self.assertIn("deck.deck_id||''", decks_html)
                self.assertIn("$('deck-type-filter').onchange=renderDeckList", decks_html)
                self.assertIn("$('deck-sort').onchange=renderDeckList", decks_html)
                self.assertIn("$('deck-search').oninput=renderDeckList", decks_html)
                self.assertIn("英文名称（同时作为 code）", decks_html)
                self.assertNotIn('name="code"', decks_html)
                self.assertIn('src="/effect-editor-shared.js"', decks_html)
                self.assertIn("STANDARD_PROFESSIONS=effectEditor.fixedProfessions", decks_html)
                self.assertIn("UNASSIGNED_DECK_ID='virtual-unassigned'", decks_html)
                self.assertIn("DECK_TYPE_LABELS={virtual:'自动计算卡组',role:", decks_html)
                self.assertIn("function isUnassignedCard(card)", decks_html)
                self.assertIn("some(deck=>deck.type!=='role')", decks_html)
                self.assertIn("function unassignedDeck()", decks_html)
                self.assertIn("function allDecks()", decks_html)
                self.assertIn("这是实时计算的只读卡组，不能主动添加、移除或调整成员", decks_html)
                self.assertIn("if(!current.isVirtual)container.querySelectorAll('.member')", decks_html)
                self.assertIn("attribute:'属性卡组'", decks_html)
                self.assertIn("race:'种族卡组'", decks_html)
                self.assertIn("tribe:'部落卡组'", decks_html)
                self.assertIn("culture:'文化卡组'", decks_html)
                self.assertIn("story:'剧情卡组'", decks_html)
                self.assertIn("function renderDeckTypeOptions()", decks_html)
                self.assertIn("PROFESSION_MATRIX=[...STANDARD_PROFESSIONS,'其他']", decks_html)
                self.assertIn("function matrixProfessions(values)", decks_html)
                self.assertIn("function matrixProfessionCells(groups)", decks_html)
                self.assertIn("if(!groups.primary.length)return secondary.map(profession=>[profession,profession])", decks_html)
                self.assertIn("if(!groups.secondary.length)return primary.map(profession=>[profession,profession])", decks_html)
                self.assertIn("function professionMatrix(cardType)", decks_html)
                self.assertIn("function professionCounts(cardType='')", decks_html)
                self.assertIn("function professionMatrixHtml(cardType)", decks_html)
                self.assertIn("function professionTotalChartHtml(counts)", decks_html)
                self.assertIn('class="profession-total-chart" role="img"', decks_html)
                self.assertIn('class="profession-bar profession-bar-total" style="height:${totalHeight}px"', decks_html)
                self.assertIn('class="profession-bar profession-bar-primary" style="height:${primaryHeight}px"', decks_html)
                self.assertNotIn('<span class="profession-bar-value">总计／主职业</span>', decks_html)
                self.assertIn("function professionCounts(cardType='')", decks_html)
                self.assertIn("members=cardType?current.members.filter(member=>member.card_type===cardType):current.members", decks_html)
                self.assertIn("all.id='profession-chart-all'", decks_html)
                self.assertIn("heading.textContent='全卡组'", decks_html)
                self.assertIn("all.innerHTML=professionTotalChartHtml(professionCounts())", decks_html)
                self.assertIn('class="profession-bar-number">${total}</span>', decks_html)
                self.assertIn('class="profession-bar-number">${primary}</span>', decks_html)
                self.assertIn("background:repeating-linear-gradient(to top", decks_html)
                self.assertIn("function tacticalTagCounts(cardType='')", decks_html)
                self.assertIn("function tacticalTagChartHtml(cardType='')", decks_html)
                self.assertIn("function renderTacticalTagChart()", decks_html)
                self.assertIn('id="tactical-tag-chart"', decks_html)
                self.assertIn('id="tactical-tag-chart-monster"', decks_html)
                self.assertIn('id="tactical-tag-chart-prophecy"', decks_html)
                self.assertIn("tacticalTagChartHtml('monster')", decks_html)
                self.assertIn("tacticalTagChartHtml('prophecy')", decks_html)
                self.assertIn('class="tactical-tag-chart" role="img"', decks_html)
                self.assertIn("cardTags=new Set((card.effects||[]).flatMap(effect=>effect.tactical_tags||[]))", decks_html)
                self.assertIn("entry.cards.push({type:card.type,title:card.title,card_id:card.card_id,quantity})", decks_html)
                self.assertIn('class="tactical-card-list"', decks_html)
                self.assertIn("showCards=Boolean(cardType)", decks_html)
                self.assertIn("${showCards?`<span class=\"tactical-card-list\">", decks_html)
                self.assertNotIn('<span class="tactical-card-type">${card.type', decks_html)
                self.assertNotIn('.tactical-card-type{', decks_html)
                self.assertIn("card.quantity>1?` ×${card.quantity}`:''", decks_html)
                self.assertIn("Object.prototype.hasOwnProperty.call(effect,'tactical_tags')", decks_html)
                self.assertIn("同一张卡的多个卡效带有相同标签时只计一次", decks_html)
                self.assertIn("Math.max(1,Math.floor(Number(member.quantity)||1))", decks_html)
                self.assertIn("TACTICAL_TAG_ORDER=['输出','输入','转换','追击','反制']", decks_html)
                self.assertIn("leftIndex=TACTICAL_TAG_ORDER.indexOf(left[0])", decks_html)
                self.assertIn("if(leftPreset&&rightPreset)return leftIndex-rightIndex", decks_html)
                self.assertIn("if(leftPreset)return-1", decks_html)
                self.assertIn("return left[0].localeCompare(right[0],'zh-CN')", decks_html)
                self.assertIn("Math.max(...entries.map(([,entry])=>entry.count))", decks_html)
                self.assertNotIn("right[1]-left[1]", decks_html)
                self.assertNotIn('class="profession-total"><strong>${profession}</strong> 总计', decks_html)
                self.assertNotIn('class="matrix-count">副 ${counts.secondary[profession]}', decks_html)
                self.assertIn('class="matrix-count">主 ${counts.primary[primary]}', decks_html)
                self.assertIn("new Set(primaryRoles).forEach(profession=>primary[profession]+=quantity)", decks_html)
                self.assertIn("new Set([...primaryRoles,...secondaryRoles]).forEach(profession=>total[profession]+=quantity)", decks_html)
                self.assertNotIn("浅：总计<br>深：主职业", decks_html)
                self.assertIn('class="profession-legend-swatch profession-legend-total"', decks_html)
                self.assertIn('class="profession-legend-swatch profession-legend-primary"', decks_html)
                self.assertIn("“总计”统计主职业或副职业包含该职业的卡牌数量", decks_html)
                self.assertIn("syncMemberInputs();renderMonsterLevelStats();renderProfessionMatrix();renderTacticalTagChart()", decks_html)
                self.assertIn("if(!rawPrimary.length)primaryRoles=rawSecondary", decks_html)
                self.assertIn("else if(!rawSecondary.length)secondaryRoles=rawPrimary", decks_html)
                self.assertIn("new Set([...primaryRoles,...secondaryRoles])", decks_html)
                self.assertIn('id="profession-matrix-monster"', decks_html)
                self.assertIn('id="profession-matrix-prophecy"', decks_html)
                self.assertIn("参考职业矩阵(怪物)", decks_html)
                self.assertIn("参考职业矩阵(预言)", decks_html)
                self.assertIn('id="generate-reference-monster">生成</button>', decks_html)
                self.assertIn('id="generate-reference-prophecy">生成</button>', decks_html)
                self.assertIn("head=STANDARD_PROFESSIONS.map", decks_html)
                self.assertIn("rows=STANDARD_PROFESSIONS.map", decks_html)
                self.assertIn("function isRegularTournament(matrix)", decks_html)
                self.assertIn("function randomRegularTournament5Bruteforce()", decks_html)
                self.assertIn("function generateReferenceMatrix(cardType)", decks_html)
                self.assertIn("if(isRegularTournament(matrix))return matrix", decks_html)
                self.assertIn("生成会直接覆盖对应矩阵", decks_html)
                self.assertIn("function renderReferenceMatrices()", decks_html)
                self.assertIn("class=\"${reference?'reference-target':''}\"", decks_html)
                self.assertIn("function ensureCardProfessionDetails(member)", decks_html)
                self.assertIn("effectEditor.cardProfessionGroups(card)", decks_html)
                self.assertIn("function renderProfessionMatrix()", decks_html)
                self.assertIn('id="member-search" type="search"', decks_html)
                self.assertIn("member.card_type==='prophecy'?'member-title-prophecy':''", decks_html)
                self.assertIn('.member-title-prophecy{color:#1e5a96}', decks_html)
                self.assertIn('href="/editor?type=${encodeURIComponent(member.card_type)}&id=${encodeURIComponent(member.card_id)}"', decks_html)
                self.assertIn('target="_blank" rel="noopener"', decks_html)
                self.assertIn('搜索卡名、card_id 或卡牌类型', decks_html)
                self.assertIn('function memberCardMatches(card,keyword)', decks_html)
                self.assertIn('function renderMemberCardOptions()', decks_html)
                self.assertIn("$('member-search').oninput=renderMemberCardOptions", decks_html)
                self.assertIn("if(event.key==='Enter')event.preventDefault()", decks_html)
                self.assertIn('没有匹配卡牌', decks_html)
                self.assertIn("function requestDeckSave", decks_html)
                self.assertIn("function flushDeckSave", decks_html)
                self.assertIn("function persistDeck", decks_html)
                self.assertIn("Promise.all([loadDeckList(),loadCards(true)])", decks_html)
                self.assertIn("async function refreshExternalData()", decks_html)
                self.assertIn("if(document.hidden||deckDirty||current?.isNew", decks_html)
                self.assertIn("document.addEventListener('visibilitychange'", decks_html)
                self.assertIn("window.addEventListener('focus',refreshExternalData)", decks_html)
                self.assertIn("addEventListener('focusout'", decks_html)
                self.assertIn("所有修改都会自动保存", decks_html)
                self.assertNotIn('<button type="submit">保存卡组</button>', decks_html)
                self.assertIn("只会解除卡组成员关系，卡牌本身不会被删除", decks_html)
                self.assertIn("卡组翻译、成员关系和职业矩阵都会从数据库删除", decks_html)
            with urllib.request.urlopen(base + "/effects") as response:
                effects_html = response.read().decode("utf-8")
                self.assertIn('id="sort"', effects_html)
                self.assertIn("valuationFilter.id='valuation-filter'", effects_html)
                self.assertIn('<option value="valued">', effects_html)
                self.assertIn("q.set('valuation_status',$('valuation-filter').value)", effects_html)
                self.assertIn("valuationFilter.onchange=load", effects_html)
                self.assertIn('<option value="text:asc">中文效果字典序</option>', effects_html)
                self.assertIn('<option value="text_length:asc" selected>中文效果字数从少到多</option>', effects_html)
                self.assertIn('<option value="text_length:desc">中文效果字数从多到少</option>', effects_html)
                self.assertIn("effectLabels", effects_html)
                self.assertIn("detailTitle", effects_html)
                self.assertIn("e.type==='prophecy_effect'&&e.owner?.is_permanent?'（永续）预言效果'", effects_html)
                self.assertIn('<option value="normal_prophecy_effect">预言效果</option>', effects_html)
                self.assertIn('<option value="permanent_prophecy_effect">（永续）预言效果</option>', effects_html)
                self.assertIn("['normal_prophecy_effect','permanent_prophecy_effect'].includes(selectedType)?'prophecy_effect':selectedType", effects_html)
                self.assertIn("effectTitleColors", effects_html)
                self.assertIn("<strong style=\"color:${effectTitleColors[e.type]||'#111827'}\">${esc(detailTitle(e))}</strong>", effects_html)
                self.assertIn("function previewCurrentListItem(event)", effects_html)
                self.assertIn("addEventListener('input',previewCurrentListItem)", effects_html)
                self.assertIn("导出当前列表 JSON", effects_html)
                self.assertIn("<strong>卡效列表</strong>", effects_html)
                self.assertIn("$('list-actions').append(exportEffectsButton,importEffectsButton,exportPureEffectsButton,importPureEffectsButton,importEffectsInput,importPureEffectsInput)", effects_html)
                self.assertIn("font-size:12px", effects_html)
                self.assertIn("color:#7b838c", effects_html)
                self.assertIn("导入卡效 JSON", effects_html)
                self.assertIn("/api/effects/export", effects_html)
                self.assertIn("/api/effects/import", effects_html)
                self.assertIn("/api/effects/pure-export", effects_html)
                self.assertIn("/api/effects/pure-import", effects_html)
                self.assertIn("exportPureEffectsButton.textContent='纯效导出'", effects_html)
                self.assertIn("importPureEffectsButton.textContent='纯效导入'", effects_html)
                self.assertIn("只会按卡效 ID 更新中文效果描述和估值", effects_html)
                self.assertIn("e.valuation!=null", effects_html)
                self.assertIn("function formatValuation(value)", effects_html)
                self.assertIn(">${esc(formatValuation(e.valuation))}</span>", effects_html)
                self.assertIn("linear-gradient(135deg,#fff8b8 0%,#ffd84d 42%,#f4b400 100%)", effects_html)
                self.assertNotIn("估值 ${esc(e.valuation)}", effects_html)
                self.assertNotIn('title="估值"', effects_html)
                self.assertIn('title="未绑定卡牌"', effects_html)
                self.assertNotIn("估值：${e.valuation??'未设置'}", effects_html)
                self.assertIn('请选择效果类型', effects_html)
                self.assertIn("type:$('effect-type').value", effects_html)
                self.assertIn("method:isNew?'POST':'PUT'", effects_html)
                self.assertNotIn('<span class="muted">#${e.id}</span>', effects_html)
                self.assertIn("所属卡牌：", effects_html)
                self.assertIn('class="profession-tags"', effects_html)
                self.assertIn('id="editing-professions"', effects_html)
                self.assertIn('style="display:flex;gap:12px"', effects_html)
                self.assertIn('<label style="width:140px">${fieldLabel(\'灵力消耗\',true)}', effects_html)
                self.assertIn('<label style="width:140px">估值', effects_html)
                self.assertIn('<label class="wide">职业标签', effects_html)
                self.assertIn('<label class="wide">战术标签', effects_html)
                self.assertIn('id="editing-tactical-tags"', effects_html)
                self.assertIn("TACTICAL_TAG_PRESETS=['输出','输入','转换','追击','反制']", effects_html)
                self.assertIn('name="marker" maxlength="10"', effects_html)
                self.assertIn('name="notes"', effects_html)
                self.assertIn("function fieldLabel(label,onCard)", effects_html)
                self.assertIn("effectEditor.supportsEnergy(current.type)", effects_html)
                self.assertIn("supportsName=effectEditor.supportsName(type)", effects_html)
                self.assertIn("fieldLabel('中文效果',true)", effects_html)
                self.assertIn("e.marker?` <span class=\"muted\">", effects_html)
                self.assertIn("data-profession=\"${esc(profession)}\"", effects_html)
                self.assertIn("professions:[...editingProfessions]", effects_html)
                self.assertIn("tactical_tags:[...editingTacticalTags]", effects_html)
                self.assertIn("addEditingProfessions", effects_html)
                self.assertIn("async function navigateEffect", effects_html)
                self.assertIn("await openEffect(effects[targetIndex].id)", effects_html)
                self.assertIn('id="undo-effect"', effects_html)
                self.assertIn("function requestEffectSave", effects_html)
                self.assertIn("function flushEffectSave", effects_html)
                self.assertNotIn('<button type="submit">保存效果</button>', effects_html)
                self.assertIn("['ArrowUp','ArrowDown'].includes(event.key)", effects_html)
                self.assertIn("scrollIntoView({block:'nearest'})", effects_html)
                self.assertIn("/api/effect-professions", effects_html)
                self.assertIn('id="profession-summary"', effects_html)
                self.assertNotIn('id="profession"', effects_html)
                self.assertNotIn("function renderProfessionFilter", effects_html)
                self.assertIn("职业词条：", effects_html)
                self.assertIn("selectedProfessions=new Set()", effects_html)
                self.assertIn("function toggleProfession", effects_html)
                self.assertIn("q.append('profession',profession)", effects_html)
                self.assertNotIn("['刺客','坦克','射手','法师','辅助'].map", effects_html)
                self.assertIn("FIXED_PROFESSIONS=effectEditor.fixedProfessions", effects_html)
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
                self.assertIn('src="/effect-editor-shared.js"', effects_html)
                self.assertIn("border-top:1px solid #d9dee3", effects_html)
                self.assertIn("effectHasSaveError", effects_html)
                self.assertIn("永久删除卡效", effects_html)
                self.assertIn("method:'DELETE'", effects_html)
                self.assertIn("function deleteCurrentEffect()", effects_html)
                self.assertIn("button.onmousedown=event=>event.preventDefault()", effects_html)
                self.assertIn("该卡效会从所属卡牌和数据库中永久删除", effects_html)
            with urllib.request.urlopen(base + "/effect-editor-shared.js") as response:
                shared_effect_editor = response.read().decode("utf-8")
                self.assertIn("supportsEnergy", shared_effect_editor)
                self.assertIn("supportsName", shared_effect_editor)
                self.assertIn("compactText", shared_effect_editor)
                self.assertIn("const effectProfessionGroups", shared_effect_editor)
                self.assertIn("const monsterStatProfessions", shared_effect_editor)
                self.assertIn("const cardProfessionGroups", shared_effect_editor)
                self.assertIn("effect.type === 'monster_attribute'", shared_effect_editor)
                self.assertIn("effect.type === 'monster_reactive_attribute'", shared_effect_editor)
                self.assertIn("effect.type === 'monster_skill'", shared_effect_editor)
                self.assertIn("effect.type === 'prophecy_effect'", shared_effect_editor)
                self.assertIn("effect.type === 'prophecy_reactive_effect'", shared_effect_editor)
                self.assertIn("(Math.max(0, Number(level) || 0) + 1) * 5", shared_effect_editor)
                self.assertIn("professions.push('刺客')", shared_effect_editor)
                self.assertIn("professions.push('坦克')", shared_effect_editor)
            with urllib.request.urlopen(base + "/design-guides") as response:
                guides_html = response.read().decode("utf-8")
                self.assertIn("设计指南", guides_html)
                self.assertIn("/api/monster-benchmarks", guides_html)
                self.assertIn('id="show-monster-design"', guides_html)
                self.assertIn('id="monster-design-table"', guides_html)
                self.assertIn("g.code!=='monster_design_table'", guides_html)
                self.assertIn("function markdownTable(content)", guides_html)
                self.assertIn("function renderMonsterDesign()", guides_html)
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
            with urllib.request.urlopen(base + "/api/monster-types") as response:
                monster_types = json.load(response)
                self.assertEqual(monster_types["count"], 13)
                self.assertIn({"zh": "光", "en": "Light"}, monster_types["items"])
            with urllib.request.urlopen(base + "/api/design-guides") as response:
                self.assertGreater(json.load(response)["count"], 0)
            with urllib.request.urlopen(base + "/api/monster-benchmarks") as response:
                self.assertGreater(json.load(response)["count"], 0)
            with urllib.request.urlopen(base + "/api/monster-design-table") as response:
                monster_design = json.load(response)
                self.assertGreater(monster_design["count"], 0)
                self.assertEqual(monster_design["items"][0]["attack_limit"], "(-1) 9")
            http_deck_payload = {"deck_type": "tribe", "display_order": 100, "translations": {"zh": {"name": "HTTP卡组", "summary": "", "description": "HTTP介绍"}, "en": {"name": "HTTP Deck", "summary": "", "description": "HTTP description"}}, "members": []}
            deck_create_request = urllib.request.Request(base + "/api/decks", data=json.dumps(http_deck_payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(deck_create_request) as response:
                self.assertEqual(response.status, 201)
                http_deck = json.load(response)
            self.assertTrue(http_deck["deck_id"].startswith("deck-"))
            self.assertEqual(http_deck["code"], "HTTP Deck")
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


class ProfessionDeckSyncTests(unittest.TestCase):
    def test_sync_appends_missing_cards_preserves_order_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            connection = connect(Path(directory) / "profession-decks.sqlite3")
            try:
                migrate(connection)
                deck_ids = {}
                for index, code in enumerate(("⚔️assassin", "🛡️tank", "🏹shooter", "🪄magician", "🧠strategy")):
                    deck_id = connection.execute("INSERT INTO decks(deck_id,code,deck_type,display_order) VALUES (?,?, 'role',?)", (f"deck-role-{index}", code, index)).lastrowid
                    connection.execute("INSERT INTO deck_translations(deck_id,language,name) VALUES (?,'zh',?)", (deck_id, code))
                    deck_ids[code] = deck_id

                def monster(card_id, title, attack=1, defence=1):
                    owner_id = connection.execute("INSERT INTO monster_cards(card_id,level,attack,defence,magic,image_path) VALUES (?,0,?,?,0,?)", (card_id, attack, defence, f"pics/{card_id}.png")).lastrowid
                    connection.execute("INSERT INTO monster_card_translations(monster_card_id,language,title) VALUES (?,'zh',?)", (owner_id, title))
                    return owner_id

                existing = monster("existing-assassin", "原刺客")
                multi = monster("multi-role", "刺坦双职")
                stat_assassin = monster("stat-assassin", "高攻刺客", attack=6)
                prophecy = connection.execute("INSERT INTO prophecy_cards(card_id,image_path) VALUES ('multi-prophecy','pics/multi-prophecy.png')").lastrowid
                connection.execute("INSERT INTO prophecy_card_translations(prophecy_card_id,language,title) VALUES (?,'zh','多职业预言')", (prophecy,))

                effect = connection.execute("INSERT INTO effects(monster_card_id,effect_type) VALUES (?,'monster_attribute')", (existing,)).lastrowid
                connection.execute("INSERT INTO effect_professions(effect_id,profession,position) VALUES (?,'刺客',0)", (effect,))
                effect = connection.execute("INSERT INTO effects(monster_card_id,effect_type) VALUES (?,'monster_attribute')", (multi,)).lastrowid
                connection.execute("INSERT INTO effect_professions(effect_id,profession,position) VALUES (?,'刺客',0)", (effect,))
                connection.execute("INSERT INTO effect_professions(effect_id,profession,position) VALUES (?,'坦克',1)", (effect,))
                effect = connection.execute("INSERT INTO effects(prophecy_card_id,effect_type) VALUES (?,'prophecy_effect')", (prophecy,)).lastrowid
                for position, profession in enumerate(("射手", "法师", "辅助")):
                    connection.execute("INSERT INTO effect_professions(effect_id,profession,position) VALUES (?,?,?)", (effect, profession, position))

                assassin = deck_ids["⚔️assassin"]
                connection.execute("INSERT INTO deck_cards(deck_id,monster_card_id,position,section) VALUES (?,?,0,'原顺序')", (assassin, existing))
                connection.execute("INSERT INTO deck_cards(deck_id,prophecy_card_id,position,section) VALUES (?,?,1,'保留项')", (assassin, prophecy))
                connection.commit()

                preview = sync_profession_decks(connection, dry_run=True)
                self.assertEqual(preview["total_added"], 6)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM deck_cards").fetchone()[0], 2)

                applied = sync_profession_decks(connection)
                self.assertEqual(applied["total_added"], 6)
                assassin_rows = list(connection.execute("SELECT monster_card_id,prophecy_card_id,position,section FROM deck_cards WHERE deck_id=? ORDER BY position", (assassin,)))
                self.assertEqual([(row["monster_card_id"], row["prophecy_card_id"]) for row in assassin_rows], [(existing, None), (None, prophecy), (multi, None), (stat_assassin, None)])
                self.assertEqual([(row["position"], row["section"]) for row in assassin_rows[:2]], [(0, "原顺序"), (1, "保留项")])
                self.assertEqual(sync_profession_decks(connection)["total_added"], 0)
            finally:
                connection.close()


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
        return {"base": {"card_id": "crud-test-monster", "level": 1, "monster_type": "光", "attack": 7, "defence": 8, "magic": 1.5, "image": "pictures/grid.png", "design_notes": "内部设计笔记"}, "translations": {"zh": {"title": title, "monster_type": "光", "description": "【测试种】"}, "en": {"title": "CRUD Test Monster", "monster_type": "Light", "description": "[Test]"}}, "effects": [{"type": "monster_skill", "position": 0, "energy_cost": 1, "translations": {"zh": {"name": "测试技能", "text": "抽一张牌。"}, "en": {"name": "Test Skill", "text": "Draw a card."}}}], "deck_codes": ["Intro"]}

    def test_new_prophecy_without_card_id_gets_generated_stable_id(self):
        created = save_card(self.connection, "prophecy", {
            "base": {"design_notes": ""},
            "translations": {
                "zh": {"title": "自动编号预言", "introduction": "测试"},
                "en": {"title": "Generated Prophecy ID", "introduction": "Test"},
            },
            "effects": [],
            "deck_codes": [],
        })
        self.assertRegex(created["base"]["card_id"], r"^\d{8}-web-p[0-9a-f]{8}$")

    def test_create_update_effects_decks_and_version_conflict(self):
        created = save_card(self.connection, "monster", self.payload())
        owner_id = created["base"]["id"]
        self.assertEqual(created["base"]["version"], 1)
        self.assertEqual(created["base"]["design_notes"], "内部设计笔记")
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

    def test_card_serial_tracks_rendered_content_but_not_valuation_or_design_notes(self):
        created = save_card(self.connection, "monster", self.payload("Serial Test Monster"))
        owner_id = created["base"]["id"]
        original_serial = created["base"]["serial_number"]
        self.assertRegex(original_serial, r"^V1-CCRUDTESTMONSTER-U\d{8}T\d{9}Z$")
        self.assertRegex(created["base"]["serial_updated_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")

        effect = get_effect(self.connection, created["effects"][0]["id"])
        valuation_only = {**effect, "valuation": 9.5}
        update_effect(self.connection, effect["id"], valuation_only)
        after_valuation = get_card(self.connection, "monster", owner_id)
        self.assertEqual(after_valuation["base"]["serial_number"], original_serial)

        changed_effect = get_effect(self.connection, effect["id"])
        changed_effect["translations"]["zh"]["text"] += " Visible change."
        update_effect(self.connection, effect["id"], changed_effect)
        after_visible_change = get_card(self.connection, "monster", owner_id)
        changed_serial = after_visible_change["base"]["serial_number"]
        self.assertNotEqual(changed_serial, original_serial)

        notes_only = {
            "version": after_visible_change["base"]["version"],
            "base": {**after_visible_change["base"], "design_notes": "new internal notes"},
            "translations": after_visible_change["translations"],
            "effects": after_visible_change["effects"],
            "deck_codes": [deck["code"] for deck in after_visible_change["decks"]],
        }
        after_notes = save_card(self.connection, "monster", notes_only, owner_id)
        self.assertEqual(after_notes["base"]["serial_number"], changed_serial)

        self.assertEqual(set_data_version(self.connection, "v3.1"), "v3.1")
        after_version = get_card(self.connection, "monster", owner_id)
        self.assertRegex(after_version["base"]["serial_number"], r"^V3P1-CCRUDTESTMONSTER-U\d{8}T\d{9}Z$")
        self.assertNotEqual(after_version["base"]["serial_number"], changed_serial)
        version_serial = after_version["base"]["serial_number"]
        set_data_version(self.connection, "v3.1")
        self.assertEqual(get_card(self.connection, "monster", owner_id)["base"]["serial_number"], version_serial)

    def test_monster_type_translation_and_effect_limits(self):
        payload = self.payload("属性翻译与容量测试")
        payload["base"]["card_id"] = "monster-limits-test"
        payload["translations"]["en"]["monster_type"] = "Wrong value must be ignored"
        skill = payload["effects"][0]
        payload["effects"] = [
            {**json.loads(json.dumps(skill)), "position": position, "translations": {"zh": {"name": f"技能{position}", "text": f"技能文本{position}"}}}
            for position in range(3)
        ] + [{"type": "monster_attribute", "position": 0, "translations": {"zh": {"name": "", "text": "通常属性文本"}}}]
        created = save_card(self.connection, "monster", payload)
        self.assertEqual(created["translations"]["en"]["monster_type"], "Light")
        self.assertIn({"zh": "光", "en": "Light"}, list_monster_types(self.connection))

        too_many = self.payload("技能超限测试")
        too_many["base"]["card_id"] = "monster-too-many-skills"
        too_many["effects"] = [
            {**json.loads(json.dumps(skill)), "position": position, "translations": {"zh": {"name": f"超限{position}", "text": "测试"}}}
            for position in range(4)
        ]
        with self.assertRaisesRegex(CardWriteError, "最多只能有3个技能"):
            save_card(self.connection, "monster", too_many)

        duplicate_attributes = self.payload("属性超限测试")
        duplicate_attributes["base"]["card_id"] = "monster-too-many-attributes"
        duplicate_attributes["effects"] = [
            {"type": "monster_attribute", "position": position, "translations": {"zh": {"name": "", "text": f"属性{position}"}}}
            for position in range(2)
        ]
        with self.assertRaisesRegex(CardWriteError, "最多只能有1个通常属性"):
            save_card(self.connection, "monster", duplicate_attributes)

        attribute = next(effect for effect in created["effects"] if effect["type"] == "monster_attribute")
        with self.assertRaisesRegex(EffectWriteError, "最多只能有3个技能"):
            update_effect(self.connection, attribute["id"], {
                "version": attribute["version"],
                "type": "monster_skill",
                "energy_cost": 1,
                "translations": {"zh": {"name": "第四技能", "text": "不应保存"}},
            })

    def test_card_save_detaches_effect_without_deleting_it(self):
        created = save_card(self.connection, "monster", self.payload("解除链接测试"))
        effect = created["effects"][0]
        payload = self.payload("解除链接测试")
        payload["version"] = created["base"]["version"]
        payload["effects"] = []
        detached_card = save_card(self.connection, "monster", payload, created["base"]["id"])
        self.assertEqual(detached_card["effects"], [])
        self.assertEqual(detached_card["detached_effects"], [{"id": effect["id"], "version": effect["version"] + 1}])
        detached = get_effect(self.connection, effect["id"])
        self.assertIsNone(detached["owner"])
        self.assertEqual(detached["translations"], effect["translations"])

        payload["version"] = detached_card["base"]["version"]
        payload["effects"] = [{**detached, "position": 0}]
        restored = save_card(self.connection, "monster", payload, created["base"]["id"])
        self.assertEqual(restored["effects"][0]["id"], effect["id"])
        self.assertEqual(get_effect(self.connection, effect["id"])["owner"]["id"], created["base"]["id"])

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
        self.assertEqual(copied["base"]["design_notes"], "内部设计笔记")
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
        return {"deck_type": "role", "display_order": 99, "translations": {"zh": {"name": "CRUD卡组", "summary": "摘要", "description": "卡组介绍"}, "en": {"name": "CRUD Deck", "summary": "Summary", "description": "Description"}}, "members": [{"card_type": "monster", "card_id": self.monster_id, "section": "核心", "quantity": 1}, {"card_type": "prophecy", "card_id": self.prophecy_id, "section": "支援", "quantity": 2}], "profession_matrices": [{"card_type": "monster", "primary_profession": "刺客", "secondary_profession": "坦克", "value": 1}, {"card_type": "prophecy", "primary_profession": "法师", "secondary_profession": "辅助", "value": 1}]}

    def test_create_update_members_and_card_side_sync(self):
        created = save_deck(self.connection, self.payload())
        self.assertEqual(created["deck_type"], "role")
        self.assertTrue(created["deck_id"].startswith("deck-"))
        self.assertEqual(created["code"], "CRUD Deck")
        self.assertEqual(len(created["profession_matrices"]), 2)
        self.assertEqual({(cell["card_type"], cell["primary_profession"], cell["secondary_profession"]) for cell in created["profession_matrices"]}, {("monster", "刺客", "坦克"), ("prophecy", "法师", "辅助")})
        self.assertEqual([member["card_type"] for member in created["members"]], ["monster", "prophecy"])
        monster = get_card(self.connection, "monster", self.monster_id)
        self.assertIn(created["deck_id"], [deck["deck_id"] for deck in monster["decks"]])
        payload = self.payload()
        payload["version"] = 1
        payload["translations"]["en"]["name"] = "Renamed Deck"
        payload["members"] = [payload["members"][1]]
        updated = save_deck(self.connection, payload, created["id"])
        self.assertEqual(updated["version"], 2)
        self.assertEqual(updated["deck_id"], created["deck_id"])
        self.assertEqual(updated["code"], "Renamed Deck")
        self.assertEqual(len(updated["members"]), 1)
        monster = get_card(self.connection, "monster", self.monster_id)
        self.assertNotIn(created["deck_id"], [deck["deck_id"] for deck in monster["decks"]])
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

    def test_blank_chinese_name_defaults_to_english_name(self):
        payload = self.payload()
        payload["translations"]["zh"]["name"] = ""
        created = save_deck(self.connection, payload)
        self.assertEqual(created["translations"]["zh"]["name"], "CRUD Deck")
        self.assertEqual(created["translations"]["en"]["name"], created["code"])

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

    def test_non_skill_effects_reject_names_and_energy_costs(self):
        created = create_effect(self.connection, {
            "type": "prophecy_effect",
            "energy_cost": 9,
            "translations": {
                "zh": {"name": "不应保存", "text": "预言效果文本"},
                "en": {"name": "Must disappear", "text": "Prophecy text"},
            },
        })
        self.assertIsNone(created["energy_cost"])
        self.assertEqual(created["translations"]["zh"]["name"], "")
        self.assertEqual(created["translations"]["en"]["name"], "")

        updated = update_effect(self.connection, created["id"], {
            **created,
            "energy_cost": 3,
            "translations": {"zh": {"name": "仍不应保存", "text": "已更新"}},
        })
        self.assertIsNone(updated["energy_cost"])
        self.assertEqual(updated["translations"]["zh"]["name"], "")

        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("INSERT INTO effects(effect_type,energy_cost) VALUES ('monster_attribute',1)")
        with self.assertRaises(sqlite3.IntegrityError):
            self.connection.execute("UPDATE effect_translations SET name='非法名称' WHERE effect_id=? AND language='zh'", (created["id"],))

    def test_permanent_prophecy_effect_is_derived_from_owner_card(self):
        prophecy_id = self.connection.execute("INSERT INTO prophecy_cards(card_id,image_path) VALUES ('permanent-prophecy','pics/permanent-prophecy.png')").lastrowid
        self.connection.execute("INSERT INTO prophecy_card_translations(prophecy_card_id,language,title,introduction) VALUES (?,'zh','永续测试','【永续】测试')", (prophecy_id,))
        effect_id = self.connection.execute("INSERT INTO effects(prophecy_card_id,effect_type) VALUES (?,'prophecy_effect')", (prophecy_id,)).lastrowid
        self.connection.execute("INSERT INTO effect_translations(effect_id,language,text) VALUES (?,'zh','持续生效。')", (effect_id,))
        self.connection.commit()

        self.assertTrue(get_effect(self.connection, effect_id)["owner"]["is_permanent"])
        listed = next(effect for effect in list_effects(self.connection) if effect["id"] == effect_id)
        self.assertTrue(listed["owner"]["is_permanent"])
        self.assertEqual([effect["id"] for effect in list_effects(self.connection, effect_type="permanent_prophecy_effect") if effect["id"] == effect_id], [effect_id])
        self.assertNotIn(effect_id, [effect["id"] for effect in list_effects(self.connection, effect_type="normal_prophecy_effect")])

        self.connection.execute("UPDATE prophecy_card_translations SET introduction='【通常】测试' WHERE prophecy_card_id=? AND language='zh'", (prophecy_id,))
        self.connection.commit()
        self.assertFalse(get_effect(self.connection, effect_id)["owner"]["is_permanent"])
        self.assertNotIn(effect_id, [effect["id"] for effect in list_effects(self.connection, effect_type="permanent_prophecy_effect")])
        self.assertEqual([effect["id"] for effect in list_effects(self.connection, effect_type="normal_prophecy_effect") if effect["id"] == effect_id], [effect_id])

    def test_effect_editor_delete_permanently_removes_record(self):
        row = self.connection.execute("SELECT id,monster_card_id FROM effects WHERE monster_card_id IS NOT NULL ORDER BY id LIMIT 1").fetchone()
        effect = get_effect(self.connection, row["id"])
        card_version = self.connection.execute("SELECT version FROM monster_cards WHERE id=?", (row["monster_card_id"],)).fetchone()[0]
        delete_effect(self.connection, effect["id"], version=effect["version"])
        with self.assertRaisesRegex(EffectWriteError, "effect not found"):
            get_effect(self.connection, effect["id"])
        self.assertEqual(
            self.connection.execute("SELECT version FROM monster_cards WHERE id=?", (row["monster_card_id"],)).fetchone()[0],
            card_version + 1,
        )

    def test_create_unassigned_effect_and_attach_from_card_editor(self):
        created = create_effect(self.connection, {
            "type": "monster_skill",
            "energy_cost": 2,
            "professions": ["法师"],
            "valuation": 4.5,
            "marker": "待采用",
            "notes": "独立卡效库",
            "translations": {"zh": {"name": "候选技能", "text": "抽一张牌。"}},
        })
        self.assertIsNone(created["owner"])
        available = list_effects(self.connection, unassigned=True, available_for="monster", keyword="候选技能")
        self.assertEqual([effect["id"] for effect in available], [created["id"]])
        self.assertEqual(list_effects(self.connection, unassigned=True, available_for="prophecy", keyword="候选技能"), [])

        second_skill = create_effect(self.connection, {
            "type": "monster_skill",
            "energy_cost": 1,
            "translations": {"zh": {"name": "候选招式", "text": "获得一点魔力。"}},
        })
        skill_type_matches = list_effects(self.connection, unassigned=True, available_for="monster", keyword="技能")
        self.assertTrue({created["id"], second_skill["id"]}.issubset({effect["id"] for effect in skill_type_matches}))
        self.assertTrue(all(effect["type"] == "monster_skill" for effect in skill_type_matches))

        card_id = self.connection.execute("SELECT id FROM monster_cards WHERE status='active' ORDER BY id LIMIT 1").fetchone()[0]
        card = get_card(self.connection, "monster", card_id)
        payload = {
            "version": card["base"]["version"],
            "base": {**card["base"], "image": card["base"]["image_path"]},
            "translations": card["translations"],
            "effects": [{**effect, "position": index} for index, effect in enumerate(card["effects"] + [created])],
            "deck_codes": [deck["code"] for deck in card["decks"]],
        }
        attached = save_card(self.connection, "monster", payload, card_id)
        same_effect = next(effect for effect in attached["effects"] if effect["id"] == created["id"])
        self.assertEqual(same_effect["translations"]["zh"]["name"], "候选技能")
        self.assertEqual(get_effect(self.connection, created["id"])["owner"]["id"], card_id)
        self.assertEqual(list_effects(self.connection, unassigned=True, keyword=str(created["id"])), [])

        other_card_id = self.connection.execute("SELECT id FROM monster_cards WHERE id<>? AND status='active' ORDER BY id LIMIT 1", (card_id,)).fetchone()[0]
        other = get_card(self.connection, "monster", other_card_id)
        other_payload = {
            "version": other["base"]["version"],
            "base": {**other["base"], "image": other["base"]["image_path"]},
            "translations": other["translations"],
            "effects": [{**effect, "position": index} for index, effect in enumerate(other["effects"] + [same_effect])],
            "deck_codes": [deck["code"] for deck in other["decks"]],
        }
        with self.assertRaises(CardWriteError):
            save_card(self.connection, "monster", other_payload, other_card_id)

    def test_effect_json_backup_restores_deleted_effects_with_stable_ids(self):
        effect_ids = [row["id"] for row in self.connection.execute("SELECT id FROM effects ORDER BY id LIMIT 5")]
        originals = {effect_id: get_effect(self.connection, effect_id) for effect_id in effect_ids}
        output_dir = Path(self.temp.name) / "tmp"
        result = export_effect_backup(self.connection, effect_ids, output_dir, {"effect_type": "", "sort_by": "id"})
        backup_path = Path(result["path"])
        self.assertEqual(backup_path.parent, output_dir.resolve())
        backup = json.loads(backup_path.read_text(encoding="utf-8"))
        self.assertEqual(backup["format"], "gemuworld.effect-backup")
        self.assertEqual(backup["schema_version"], 1)
        self.assertEqual(backup["count"], len(effect_ids))
        self.assertEqual([item["id"] for item in backup["items"]], effect_ids)
        self.assertIn("card_id", backup["items"][0]["owner"])
        self.assertIn("translations", backup["items"][0])
        self.assertIn("professions", backup["items"][0])
        self.assertIn("tactical_tags", backup["items"][0])

        placeholders = ",".join("?" for _ in effect_ids)
        self.connection.execute(f"DELETE FROM effects WHERE id IN ({placeholders})", effect_ids)
        self.connection.commit()
        self.assertEqual(self.connection.execute(f"SELECT COUNT(*) FROM effects WHERE id IN ({placeholders})", effect_ids).fetchone()[0], 0)

        restored = import_effect_backup(self.connection, backup)
        self.assertEqual(restored["created"], len(effect_ids))
        self.assertEqual(restored["updated"], 0)
        for effect_id in effect_ids:
            effect = get_effect(self.connection, effect_id)
            original = originals[effect_id]
            for key in ("id", "type", "position", "energy_cost", "professions", "tactical_tags", "valuation", "marker", "notes", "version", "translations", "created_at", "updated_at"):
                self.assertEqual(effect[key], original[key], (effect_id, key))
            self.assertEqual(effect["owner"]["card_id"] if effect["owner"] else None, original["owner"]["card_id"] if original["owner"] else None)

    def test_pure_effect_export_and_import_only_update_chinese_text_and_valuation(self):
        row = self.connection.execute(
            "SELECT id,monster_card_id FROM effects WHERE monster_card_id IS NOT NULL ORDER BY id LIMIT 1"
        ).fetchone()
        effect_id = row["id"]
        owner_id = row["monster_card_id"]
        original = get_effect(self.connection, effect_id)
        self.connection.execute("UPDATE monster_cards SET updated_at='2000-01-01 00:00:00' WHERE id=?", (owner_id,))
        self.connection.commit()

        result = export_pure_effects(self.connection, [effect_id], Path(self.temp.name) / "pure", {"keyword": ""})
        backup = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(backup["format"], "gemuworld.pure-effects")
        self.assertEqual(backup["schema_version"], 1)
        self.assertEqual(set(backup["items"][0]), {"id", "zh_text", "valuation"})
        backup["items"][0]["zh_text"] = "纯效导入后的中文描述"
        backup["items"][0]["valuation"] = 7.5

        imported = import_pure_effects(self.connection, backup)
        updated = get_effect(self.connection, effect_id)
        self.assertEqual(imported, {"updated": 1, "count": 1, "effect_ids": [effect_id]})
        self.assertEqual(updated["translations"]["zh"]["text"], "纯效导入后的中文描述")
        self.assertEqual(updated["valuation"], 7.5)
        self.assertEqual(updated["version"], original["version"] + 1)
        for key in ("type", "position", "energy_cost", "professions", "tactical_tags", "marker", "notes"):
            self.assertEqual(updated[key], original[key], key)
        self.assertEqual(updated["translations"].get("en"), original["translations"].get("en"))
        self.assertNotEqual(
            self.connection.execute("SELECT updated_at FROM monster_cards WHERE id=?", (owner_id,)).fetchone()[0],
            "2000-01-01 00:00:00",
        )

        invalid = json.loads(json.dumps(backup))
        invalid["items"].append({"id": 999999999, "zh_text": "不存在", "valuation": 1})
        before_text = updated["translations"]["zh"]["text"]
        invalid["items"][0]["zh_text"] = "不应部分写入"
        with self.assertRaisesRegex(EffectWriteError, "pure effect id not found"):
            import_pure_effects(self.connection, invalid)
        self.assertEqual(get_effect(self.connection, effect_id)["translations"]["zh"]["text"], before_text)

    def test_effect_backup_import_supports_position_swaps_and_increments_versions(self):
        group = self.connection.execute(
            "SELECT monster_card_id,effect_type FROM effects WHERE monster_card_id IS NOT NULL "
            "GROUP BY monster_card_id,effect_type HAVING COUNT(*)>=2 ORDER BY monster_card_id LIMIT 1"
        ).fetchone()
        rows = list(self.connection.execute(
            "SELECT id,position,version FROM effects WHERE monster_card_id=? AND effect_type=? ORDER BY position,id LIMIT 2",
            tuple(group),
        ))
        effect_ids = [row["id"] for row in rows]
        result = export_effect_backup(self.connection, effect_ids, Path(self.temp.name) / "swap", {})
        backup = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        backup["items"][0]["position"], backup["items"][1]["position"] = backup["items"][1]["position"], backup["items"][0]["position"]

        imported = import_effect_backup(self.connection, backup)

        self.assertEqual(imported["updated"], 2)
        updated = {row["id"]: row for row in self.connection.execute("SELECT id,position,version FROM effects WHERE id IN (?,?)", effect_ids)}
        self.assertEqual(updated[effect_ids[0]]["position"], rows[1]["position"])
        self.assertEqual(updated[effect_ids[1]]["position"], rows[0]["position"])
        self.assertEqual(updated[effect_ids[0]]["version"], rows[0]["version"] + 1)
        self.assertEqual(updated[effect_ids[1]]["version"], rows[1]["version"] + 1)

    def test_effect_backup_import_rejects_invalid_valuation_and_never_regresses_version(self):
        effect_id = self.connection.execute("SELECT id FROM effects ORDER BY id LIMIT 1").fetchone()[0]
        result = export_effect_backup(self.connection, [effect_id], Path(self.temp.name) / "validation", {})
        backup = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        invalid = json.loads(json.dumps(backup))
        invalid["items"][0]["valuation"] = "not-a-number"
        with self.assertRaisesRegex(EffectWriteError, "valuation must be a finite number"):
            import_effect_backup(self.connection, invalid)

        self.connection.execute("UPDATE effects SET version=version+5 WHERE id=?", (effect_id,))
        self.connection.commit()
        current_version = self.connection.execute("SELECT version FROM effects WHERE id=?", (effect_id,)).fetchone()[0]
        import_effect_backup(self.connection, backup)
        self.assertEqual(
            self.connection.execute("SELECT version FROM effects WHERE id=?", (effect_id,)).fetchone()[0],
            current_version + 1,
        )

    def test_effect_backup_http_returns_json_for_slot_constraint_errors(self):
        group = self.connection.execute(
            "SELECT monster_card_id,effect_type FROM effects WHERE monster_card_id IS NOT NULL "
            "GROUP BY monster_card_id,effect_type HAVING COUNT(*)>=2 ORDER BY monster_card_id LIMIT 1"
        ).fetchone()
        rows = list(self.connection.execute(
            "SELECT id,position FROM effects WHERE monster_card_id=? AND effect_type=? ORDER BY position,id LIMIT 2",
            tuple(group),
        ))
        result = export_effect_backup(self.connection, [rows[0]["id"]], Path(self.temp.name) / "http", {})
        backup = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        backup["items"][0]["position"] = rows[1]["position"]
        server = ViewerServer(("127.0.0.1", 0), self.database, Path(self.temp.name) / "http-data")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.server_port}/api/effects/import",
                data=json.dumps({"backup": backup}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(request)
            self.assertEqual(caught.exception.code, 400)
            self.assertIn("database constraint error", json.load(caught.exception)["error"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_effect_update_conflict_and_owner_immutability(self):
        row = self.connection.execute("SELECT id FROM effects WHERE monster_card_id IS NOT NULL AND effect_type='monster_skill' LIMIT 1").fetchone()
        effect = get_effect(self.connection, row["id"])
        owner_id = effect["owner"]["id"]
        self.connection.execute("UPDATE monster_cards SET updated_at='2000-01-01 00:00:00',source_updated_at='1999-01-01 00:00:00' WHERE id=?", (owner_id,))
        self.connection.commit()
        payload = {"version": effect["version"], "type": effect["type"], "energy_cost": 2, "professions": ["控制", "辅助"], "tactical_tags": ["输入", "反制"], "valuation": 3.5, "marker": "爆发", "notes": "设计备注", "translations": effect["translations"]}
        payload["translations"]["zh"]["text"] = "V1.6更新效果"
        updated = update_effect(self.connection, effect["id"], payload)
        self.assertEqual(updated["version"], 2)
        self.assertEqual(updated["professions"], ["控制", "辅助"])
        self.assertEqual(updated["tactical_tags"], ["输入", "反制"])
        self.assertIn("控制", list_professions(self.connection))
        self.assertEqual(profession_counts(self.connection)["控制"], 1)
        combined = list_effects(self.connection, profession=["控制", "__unset__"])
        self.assertIn(effect["id"], [value["id"] for value in combined])
        self.assertTrue(any(not value["professions"] for value in combined))
        self.assertEqual(updated["valuation"], 3.5)
        self.assertEqual(updated["marker"], "爆发")
        self.assertEqual(updated["notes"], "设计备注")
        card_updated_at = self.connection.execute("SELECT updated_at FROM monster_cards WHERE id=?", (owner_id,)).fetchone()[0]
        self.assertNotEqual(card_updated_at, "2000-01-01 00:00:00")
        listed_card = next(card for card in list_cards(self.connection, card_type="monster") if card["id"] == owner_id)
        self.assertEqual(listed_card["updated_at"], card_updated_at)
        self.assertNotEqual(listed_card["updated_at"], "1999-01-01 00:00:00")
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
        self.assertEqual(copied["tactical_tags"], source["tactical_tags"])
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
        self.assertEqual([key[0] for key in descending_length_keys], sorted((key[0] for key in descending_length_keys), reverse=True))
        for length in dict.fromkeys(key[0] for key in descending_length_keys):
            same_length = [key[1:] for key in descending_length_keys if key[0] == length]
            self.assertEqual(same_length, sorted(same_length))
        with self.assertRaises(EffectWriteError):
            list_effects(self.connection, sort_by="unknown")

        source_id = self.connection.execute("SELECT id FROM effects WHERE effect_type='monster_skill' LIMIT 1").fetchone()[0]
        source = get_effect(self.connection, source_id)
        target_id = self.connection.execute("SELECT id FROM monster_cards WHERE id<>? LIMIT 1", (source["owner"]["id"],)).fetchone()[0]
        copied = copy_effect(self.connection, source_id, "monster", target_id)
        filtered = list_effects(self.connection, keyword=str(copied["id"]))
        self.assertIn(source_id, filtered[0]["duplicate_ids"])

    def test_effect_valuation_status_filter_includes_zero(self):
        effect_ids = [row[0] for row in self.connection.execute("SELECT id FROM effects ORDER BY id LIMIT 2")]
        self.assertEqual(len(effect_ids), 2)
        self.connection.execute("UPDATE effects SET valuation=0 WHERE id=?", (effect_ids[0],))
        self.connection.execute("UPDATE effects SET valuation=NULL WHERE id=?", (effect_ids[1],))
        self.connection.commit()

        valued = list_effects(self.connection, valuation_status="valued")
        missing = list_effects(self.connection, valuation_status="missing")
        self.assertIn(effect_ids[0], [effect["id"] for effect in valued])
        self.assertNotIn(effect_ids[1], [effect["id"] for effect in valued])
        self.assertIn(effect_ids[1], [effect["id"] for effect in missing])
        self.assertNotIn(effect_ids[0], [effect["id"] for effect in missing])
        self.assertTrue(all(effect["valuation"] is not None for effect in valued))
        self.assertTrue(all(effect["valuation"] is None for effect in missing))
        with self.assertRaises(EffectWriteError):
            list_effects(self.connection, valuation_status="unknown")

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
