from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def compute_statistics(cards: list[dict[str, object]]) -> dict[str, Any]:
    monsters = [card for card in cards if card["type"] == "monster"]
    prophecies = [card for card in cards if card["type"] == "prophecy"]
    levels = Counter(str(card["level"]) for card in monsters)
    attributes = Counter(str(card["monster_type"] or "未知") for card in monsters)
    races = Counter()
    deck_counts = Counter()
    effect_types = Counter()
    level_stats: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0, "attack_total": 0, "defence_total": 0, "magic_total": 0})
    for card in cards:
        for deck in card["decks"]:
            deck_counts[str(deck["code"])] += 1
        for effect in card["effects"]:
            effect_types[str(effect["type"])] += 1
    for card in monsters:
        description = str(card["description"])
        if "【" in description and "种】" in description:
            races[description.split("【", 1)[1].split("种】", 1)[0]] += 1
        else:
            races["未知"] += 1
        bucket = level_stats[str(card["level"])]
        bucket["count"] += 1
        bucket["attack_total"] += float(card["attack"])
        bucket["defence_total"] += float(card["defence"])
        bucket["magic_total"] += float(card["magic"])
    level_averages = {}
    for level, values in level_stats.items():
        count = values["count"]
        level_averages[level] = {"count": int(count), "attack": round(values["attack_total"] / count, 2), "defence": round(values["defence_total"] / count, 2), "magic": round(values["magic_total"] / count, 2)}
    permanent = sum(1 for card in prophecies if "【永续" in str(card.get("introduction", "")) or any("【永续" in str(effect["text"]) for effect in card["effects"]))
    return {"total": len(cards), "monster_count": len(monsters), "prophecy_count": len(prophecies), "cards_without_decks": sum(1 for card in cards if not card["decks"]), "level_distribution": dict(sorted(levels.items(), key=lambda item: float(item[0]))), "attribute_distribution": dict(attributes.most_common()), "race_distribution": dict(races.most_common()), "deck_distribution": dict(deck_counts.most_common()), "effect_type_distribution": dict(effect_types.most_common()), "level_averages": dict(sorted(level_averages.items(), key=lambda item: float(item[0]))), "prophecy": {"permanent": permanent, "other": len(prophecies) - permanent}}
