from __future__ import annotations

import argparse
import json
import mimetypes
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .database import connect, migrate
from .batch_import import BatchImportError, import_cards
from .cards import CardWriteError, VersionConflict, copy_card, delete_card, get_card, save_card
from .decks import DeckWriteError, delete_deck, get_deck, save_deck
from .effects import EffectWriteError, copy_effect, get_effect, list_effects, list_professions, profession_counts, update_effect
from .guides import GuideWriteError, list_benchmarks, list_guides, update_benchmark, update_guide
from .exports import available_versions, current_data_version, export_cards, export_version_snapshot, next_version, order_cards, set_data_version
from .queries import list_cards, list_decks
from .statistics import compute_statistics


V1_ROOT = Path(__file__).resolve().parents[2]


class ViewerServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], database: Path, data_root: Path | None = None):
        self.database = database
        self.data_root = data_root or V1_ROOT / "data"
        connection = connect(database)
        try:
            migrate(connection)
        finally:
            connection.close()
        super().__init__(address, ViewerHandler)


class ViewerHandler(BaseHTTPRequestHandler):
    server: ViewerServer

    def _json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _file(self, path: Path, content_type: str | None = None) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _download(self, body: bytes, filename: str, content_type: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _query_cards(self, query: dict[str, list[str]]) -> tuple[list[dict[str, object]], str]:
        language = query.get("language", ["zh"])[0]
        connection = connect(self.server.database)
        try:
            cards = list_cards(connection, language=language, card_type=query.get("card_type", ["all"])[0], deck_codes=[value for item in query.get("deck", []) for value in item.split(",") if value], deck_match=query.get("deck_match", ["any"])[0], keyword=query.get("keyword", [""])[0], sort_by=query.get("sort_by", ["updated_at"])[0], direction=query.get("direction", ["desc"])[0], limit=int(query["limit"][0]) if "limit" in query else None)
        finally:
            connection.close()
        return cards, language

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query)
        try:
            if path == "/api/health":
                self._json({"status": "ok", "version": "1.7.5"})
                return
            if path == "/api/export-info":
                connection = connect(self.server.database)
                try:
                    version = current_data_version(connection, self.server.data_root)
                finally:
                    connection.close()
                self._json({"versions": available_versions(self.server.data_root), "current_version": version, "default_version": version})
                return
            if path == "/api/cards":
                cards, _ = self._query_cards(query)
                self._json({"items": cards, "count": len(cards)})
                return
            card_route = path.strip("/").split("/")
            if len(card_route) == 4 and card_route[:2] == ["api", "cards"]:
                connection = connect(self.server.database)
                try:
                    card = get_card(connection, card_route[2], int(card_route[3]))
                finally:
                    connection.close()
                self._json(card)
                return
            if path == "/api/statistics":
                cards, language = self._query_cards(query)
                self._json({"language": language, "filters": {key: value for key, value in query.items()}, "statistics": compute_statistics(cards)})
                return
            if path == "/api/effect-professions":
                connection = connect(self.server.database)
                try:
                    professions = list_professions(connection)
                    counts = profession_counts(connection)
                finally:
                    connection.close()
                self._json({"items": professions, "count": len(professions), "counts": counts})
                return
            if path == "/api/effects":
                connection = connect(self.server.database)
                try:
                    effects = list_effects(connection, effect_type=query.get("effect_type", [""])[0], keyword=query.get("keyword", [""])[0], card_type=query.get("card_type", [""])[0], profession=query.get("profession", []), sort_by=query.get("sort_by", ["id"])[0], direction=query.get("direction", ["asc"])[0])
                finally:
                    connection.close()
                self._json({"items": effects, "count": len(effects)})
                return
            effect_route = path.strip("/").split("/")
            if len(effect_route) == 3 and effect_route[:2] == ["api", "effects"]:
                connection = connect(self.server.database)
                try:
                    effect = get_effect(connection, int(effect_route[2]))
                finally:
                    connection.close()
                self._json(effect)
                return
            if path == "/api/design-guides":
                connection = connect(self.server.database)
                try:
                    guides = list_guides(connection)
                finally:
                    connection.close()
                self._json({"items": guides, "count": len(guides)})
                return
            if path == "/api/monster-benchmarks":
                connection = connect(self.server.database)
                try:
                    benchmarks = list_benchmarks(connection)
                finally:
                    connection.close()
                self._json({"items": benchmarks, "count": len(benchmarks)})
                return
            if path == "/api/export":
                cards, language = self._query_cards(query)
                body, filename, content_type = export_cards(cards, language)
                self._download(body, filename, content_type)
                return
            if path == "/api/decks":
                connection = connect(self.server.database)
                try:
                    decks = list_decks(connection, query.get("language", ["zh"])[0])
                finally:
                    connection.close()
                self._json({"items": decks, "count": len(decks)})
                return
            deck_route = path.strip("/").split("/")
            if len(deck_route) == 3 and deck_route[:2] == ["api", "decks"]:
                connection = connect(self.server.database)
                try:
                    deck = get_deck(connection, int(deck_route[2]))
                finally:
                    connection.close()
                self._json(deck)
                return
            if path in ("/", "/viewer", "/viewer.html"):
                self._file(V1_ROOT / "_viewer.html", "text/html; charset=utf-8")
                return
            if path in ("/stats", "/stats.html"):
                self._file(V1_ROOT / "web" / "stats.html", "text/html; charset=utf-8")
                return
            if path in ("/import", "/import.html"):
                self._file(V1_ROOT / "web" / "import.html", "text/html; charset=utf-8")
                return
            if path in ("/editor", "/editor.html"):
                self._file(V1_ROOT / "web" / "editor.html", "text/html; charset=utf-8")
                return
            if path in ("/decks", "/decks.html"):
                self._file(V1_ROOT / "web" / "decks.html", "text/html; charset=utf-8")
                return
            if path in ("/effects", "/effects.html"):
                self._file(V1_ROOT / "web" / "effects.html", "text/html; charset=utf-8")
                return
            if path in ("/design-guides", "/design-guides.html"):
                self._file(V1_ROOT / "web" / "design_guides.html", "text/html; charset=utf-8")
                return
            if path == "/appendix.html":
                self._file(V1_ROOT / "_appendix.html", "text/html; charset=utf-8")
                return
            legacy_cards = {
                "/monster_cards.csv": ("zh", "monster"),
                "/monster_cards_en.csv": ("en", "monster"),
                "/prophecy_cards.csv": ("zh", "prophecy"),
                "/prophecy_cards_en.csv": ("en", "prophecy"),
            }
            if path in legacy_cards:
                language, card_type = legacy_cards[path]
                connection = connect(self.server.database)
                try:
                    cards = list_cards(connection, language=language, card_type=card_type, sort_by="database_order", direction="asc")
                finally:
                    connection.close()
                body, _, content_type = export_cards(cards, language)
                self._download(body, path.lstrip("/"), content_type)
                return
            if path == "/clans/_clans.json":
                connection = connect(self.server.database)
                try:
                    codes = [deck["code"] for deck in list_decks(connection, "zh")]
                finally:
                    connection.close()
                self._json(codes)
                return
            if path.startswith("/clans/") and path.endswith(".md"):
                code = Path(path).stem
                connection = connect(self.server.database)
                try:
                    row = connection.execute("SELECT source_markdown_zh FROM decks WHERE code=? AND status='active'", (code,)).fetchone()
                finally:
                    connection.close()
                if row:
                    body = row["source_markdown_zh"].encode("utf-8")
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/markdown; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_error(HTTPStatus.NOT_FOUND)
                return
            if path.startswith("/pictures/"):
                # Legacy CSV values use pictures/<name>, while the maintained
                # artwork source lives in data/current/pics.
                picture_root = (V1_ROOT / "data" / "current" / "pics").resolve()
                picture = (picture_root / path.removeprefix("/pictures/")).resolve()
                if picture_root in picture.parents and picture.is_file():
                    self._file(picture)
                else:
                    self.send_error(HTTPStatus.NOT_FOUND, "Artwork file is not present in data/current/pics")
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except (CardWriteError, DeckWriteError, EffectWriteError, GuideWriteError, ValueError, KeyError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        card_route = parsed.path.strip("/").split("/")
        is_card_create = len(card_route) == 3 and card_route[:2] == ["api", "cards"]
        is_card_copy = len(card_route) == 5 and card_route[:2] == ["api", "cards"] and card_route[4] == "copy"
        is_deck_create = card_route == ["api", "decks"]
        is_effect_copy = len(card_route) == 4 and card_route[:2] == ["api", "effects"] and card_route[3] == "copy"
        if parsed.path not in {"/api/export", "/api/import", "/api/data-version"} and not is_card_create and not is_card_copy and not is_deck_create and not is_effect_copy:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 10_000_000:
                self._json({"error": "request body is too large"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
                return
            payload = json.loads(self.rfile.read(length) or b"{}")
            if parsed.path == "/api/data-version":
                connection = connect(self.server.database)
                try:
                    version = set_data_version(connection, str(payload.get("version", "")))
                finally:
                    connection.close()
                self._json({"current_version": version})
                return
            if is_card_copy:
                connection = connect(self.server.database)
                try:
                    card = copy_card(connection, card_route[2], int(card_route[3]))
                finally:
                    connection.close()
                self._json(card, HTTPStatus.CREATED)
                return
            if is_deck_create:
                connection = connect(self.server.database)
                try:
                    deck = save_deck(connection, payload)
                finally:
                    connection.close()
                self._json(deck, HTTPStatus.CREATED)
                return
            if is_effect_copy:
                connection = connect(self.server.database)
                try:
                    effect = copy_effect(connection, int(card_route[2]), str(payload.get("target_type", "")), int(payload.get("target_id", 0)))
                finally:
                    connection.close()
                self._json(effect, HTTPStatus.CREATED)
                return
            if is_card_create:
                connection = connect(self.server.database)
                try:
                    card = save_card(connection, card_route[2], payload)
                finally:
                    connection.close()
                self._json(card, HTTPStatus.CREATED)
                return
            if parsed.path == "/api/import":
                connection = connect(self.server.database)
                try:
                    result = import_cards(connection, str(payload.get("card_type", "")), str(payload.get("csv", "")), dry_run=bool(payload.get("dry_run", False)))
                finally:
                    connection.close()
                self._json(result.as_dict())
                return
            if payload.get("snapshot"):
                export_format = str(payload.get("format", ""))
                result = export_version_snapshot(self.server.database, self.server.data_root, str(payload.get("version", "")), export_format)
                if export_format == "database":
                    connection = connect(self.server.database)
                    try:
                        result["next_version"] = set_data_version(connection, next_version(self.server.data_root))
                    finally:
                        connection.close()
                self._json(result, HTTPStatus.CREATED)
                return
            language = payload.get("language", "zh")
            raw_card_ids = payload.get("card_ids", [])
            if not isinstance(raw_card_ids, list):
                raise ValueError("card_ids must be an array")
            card_ids = [str(value) for value in raw_card_ids]
            connection = connect(self.server.database)
            try:
                cards = list_cards(connection, language=language, card_type="all", sort_by="card_id", direction="asc")
            finally:
                connection.close()
            selected = order_cards(cards, card_ids)
            body, filename, content_type = export_cards(selected, language)
            self._download(body, filename, content_type)
        except (BatchImportError, CardWriteError, DeckWriteError, EffectWriteError, GuideWriteError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_PUT(self) -> None:  # noqa: N802
        card_route = urlparse(self.path).path.strip("/").split("/")
        is_card = len(card_route) == 4 and card_route[:2] == ["api", "cards"]
        is_deck = len(card_route) == 3 and card_route[:2] == ["api", "decks"]
        is_effect = len(card_route) == 3 and card_route[:2] == ["api", "effects"]
        is_guide = len(card_route) == 3 and card_route[:2] == ["api", "design-guides"]
        is_benchmark = len(card_route) == 3 and card_route[:2] == ["api", "monster-benchmarks"]
        if not is_card and not is_deck and not is_effect and not is_guide and not is_benchmark:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or b"{}")
            connection = connect(self.server.database)
            try:
                if is_card:
                    card = save_card(connection, card_route[2], payload, int(card_route[3]))
                elif is_deck:
                    card = save_deck(connection, payload, int(card_route[2]))
                elif is_effect:
                    card = update_effect(connection, int(card_route[2]), payload)
                elif is_guide:
                    card = update_guide(connection, int(card_route[2]), payload)
                else:
                    card = update_benchmark(connection, int(card_route[2]), payload)
            finally:
                connection.close()
            self._json(card)
        except VersionConflict as exc:
            self._json({"error": str(exc)}, HTTPStatus.CONFLICT)
        except (CardWriteError, DeckWriteError, EffectWriteError, GuideWriteError, ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_DELETE(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        card_route = parsed.path.strip("/").split("/")
        is_card = len(card_route) == 4 and card_route[:2] == ["api", "cards"]
        is_deck = len(card_route) == 3 and card_route[:2] == ["api", "decks"]
        if not is_card and not is_deck:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        query = parse_qs(parsed.query)
        try:
            version = int(query.get("version", ["0"])[0])
            permanent = query.get("permanent", ["false"])[0].lower() == "true"
            connection = connect(self.server.database)
            try:
                if is_card:
                    delete_card(connection, card_route[2], int(card_route[3]), permanent=permanent, version=version)
                else:
                    delete_deck(connection, int(card_route[2]), permanent=permanent, version=version)
            finally:
                connection.close()
            self._json({"deleted": True, "permanent": permanent})
        except VersionConflict as exc:
            self._json({"error": str(exc)}, HTTPStatus.CONFLICT)
        except (CardWriteError, DeckWriteError, ValueError) as exc:
            self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: object) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the read-only GemuWorld V1.2 API and viewer.")
    parser.add_argument("--database", type=Path, default=V1_ROOT / "data" / "gemuworld.sqlite3")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    server = ViewerServer((args.host, args.port), args.database)
    print(f"GemuWorld V1.2: http://{args.host}:{args.port}/viewer")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
