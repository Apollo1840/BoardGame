from __future__ import annotations

import json
import sqlite3
from typing import Iterable


LANGUAGES = {"zh", "en"}
CARD_TYPES = {"monster", "prophecy"}


def _effect_map(connection: sqlite3.Connection, language: str) -> dict[tuple[str, int], list[dict[str, object]]]:
    result: dict[tuple[str, int], list[dict[str, object]]] = {}
    rows = connection.execute(
        "SELECT e.*,t.name,t.text FROM effects e "
        "JOIN effect_translations t ON t.effect_id=e.id AND t.language=? "
        "ORDER BY e.effect_type,e.position,e.id",
        (language,),
    )
    for row in rows:
        owner_type = "monster" if row["monster_card_id"] is not None else "prophecy"
        owner_id = row["monster_card_id"] or row["prophecy_card_id"]
        result.setdefault((owner_type, owner_id), []).append(
            {
                "id": row["id"],
                "type": row["effect_type"],
                "position": row["position"],
                "energy_cost": row["energy_cost"],
                "name": row["name"],
                "text": row["text"],
            }
        )
    return result


def _deck_map(connection: sqlite3.Connection) -> dict[tuple[str, int], list[dict[str, object]]]:
    result: dict[tuple[str, int], list[dict[str, object]]] = {}
    rows = connection.execute(
        "SELECT d.id,d.code,d.deck_type,dc.monster_card_id,dc.prophecy_card_id,dc.position,dc.section "
        "FROM deck_cards dc JOIN decks d ON d.id=dc.deck_id WHERE d.status='active' "
        "ORDER BY d.display_order,dc.position"
    )
    for row in rows:
        owner_type = "monster" if row["monster_card_id"] is not None else "prophecy"
        owner_id = row["monster_card_id"] or row["prophecy_card_id"]
        result.setdefault((owner_type, owner_id), []).append(
            {"id": row["id"], "code": row["code"], "type": row["deck_type"], "position": row["position"], "section": row["section"]}
        )
    return result


def list_cards(
    connection: sqlite3.Connection,
    *,
    language: str = "zh",
    card_type: str = "all",
    deck_codes: Iterable[str] = (),
    deck_match: str = "any",
    status: str = "active",
    keyword: str = "",
    sort_by: str = "updated_at",
    direction: str = "desc",
    limit: int | None = None,
) -> list[dict[str, object]]:
    if language not in LANGUAGES:
        raise ValueError("language must be zh or en")
    if card_type != "all" and card_type not in CARD_TYPES:
        raise ValueError("card_type must be all, monster, or prophecy")
    if deck_match not in {"any", "all"}:
        raise ValueError("deck_match must be any or all")
    effects = _effect_map(connection, language)
    decks = _deck_map(connection)
    cards: list[dict[str, object]] = []
    if card_type in ("all", "monster"):
        rows = connection.execute(
            "SELECT c.*,t.title,t.monster_type AS translated_monster_type,t.description "
            "FROM monster_cards c JOIN monster_card_translations t ON t.monster_card_id=c.id "
            "WHERE t.language=? AND c.status=?",
            (language, status),
        )
        for row in rows:
            cards.append({"type": "monster", "id": row["id"], "card_id": row["card_id"], "title": row["title"], "level": row["level"], "monster_type": row["translated_monster_type"], "description": row["description"], "attack": row["attack"], "defence": row["defence"], "magic": row["magic"], "image": row["image_path"], "updated_at": row["source_updated_at"], "effects": effects.get(("monster", row["id"]), []), "decks": decks.get(("monster", row["id"]), [])})
    if card_type in ("all", "prophecy"):
        rows = connection.execute(
            "SELECT c.*,t.title,t.introduction FROM prophecy_cards c "
            "JOIN prophecy_card_translations t ON t.prophecy_card_id=c.id "
            "WHERE t.language=? AND c.status=?",
            (language, status),
        )
        for row in rows:
            cards.append({"type": "prophecy", "id": row["id"], "card_id": row["card_id"], "title": row["title"], "introduction": row["introduction"], "image": row["image_path"], "updated_at": row["source_updated_at"], "effects": effects.get(("prophecy", row["id"]), []), "decks": decks.get(("prophecy", row["id"]), [])})
    selected = set(deck_codes)
    if selected:
        def included(card: dict[str, object]) -> bool:
            memberships = {deck["code"] for deck in card["decks"]}
            return bool(memberships & selected) if deck_match == "any" else selected <= memberships
        cards = [card for card in cards if included(card)]
    if keyword:
        needle = keyword.casefold()
        cards = [card for card in cards if needle in json.dumps(card, ensure_ascii=False).casefold()]
    sort_keys = {
        "title": lambda card: str(card["title"]).casefold(),
        "level": lambda card: float(card.get("level", -1)),
        "attack": lambda card: float(card.get("attack", -1)),
        "defence": lambda card: float(card.get("defence", -1)),
        "magic": lambda card: float(card.get("magic", -1)),
        "updated_at": lambda card: str(card["updated_at"]),
        "card_id": lambda card: str(card["card_id"]),
        "database_order": lambda card: int(card["id"]),
    }
    if sort_by not in sort_keys:
        raise ValueError(f"unsupported sort_by: {sort_by}")
    cards.sort(key=sort_keys[sort_by], reverse=direction != "asc")
    return cards[: max(0, limit)] if limit is not None else cards


def list_decks(connection: sqlite3.Connection, language: str = "zh") -> list[dict[str, object]]:
    if language not in LANGUAGES:
        raise ValueError("language must be zh or en")
    rows = connection.execute(
        "SELECT d.*,t.name,t.summary,t.description,"
        "(SELECT COUNT(*) FROM deck_cards dc WHERE dc.deck_id=d.id) AS card_count "
        "FROM decks d LEFT JOIN deck_translations t ON t.deck_id=d.id AND t.language=? "
        "WHERE d.status='active' ORDER BY d.display_order,d.id",
        (language,),
    )
    return [{"id": row["id"], "code": row["code"], "type": row["deck_type"], "name": row["name"] or row["code"], "summary": row["summary"] or "", "description": row["description"] or "", "card_count": row["card_count"], "display_order": row["display_order"]} for row in rows]
