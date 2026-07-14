from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def compute_statistics(cards: list[dict[str, object]]) -> dict[str, Any]:
    monsters = [card for card in cards if card["type"] == "monster"]
    prophecies = [card for card in cards if card["type"] == "prophecy"]
    levels = Counter(str(card["level"]) for card in monsters)
    attributes = Counter(str(card["monster_type"] or "未知") for card in monsters)
    races = Counter()
    attribute_levels: dict[str, Counter[str]] = defaultdict(Counter)
    race_levels: dict[str, Counter[str]] = defaultdict(Counter)
    deck_counts = Counter()
    effect_types = Counter()
    prophecy_types = Counter()
    prophecy_effect_coverage = Counter()
    monster_content_coverage = Counter()
    level_stat_distributions: dict[str, dict[str, Counter[str]]] = defaultdict(
        lambda: {"attack": Counter(), "defence": Counter(), "magic": Counter()}
    )
    level_stats: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0, "attack_total": 0, "defence_total": 0, "magic_total": 0})
    for card in cards:
        for deck in card["decks"]:
            deck_counts[str(deck["code"])] += 1
        for effect in card["effects"]:
            effect_types[str(effect["type"])] += 1
    for card in monsters:
        description = str(card["description"])
        level = str(card["level"])
        attribute = str(card["monster_type"] or "未知")
        if "【" in description and "种】" in description:
            race = description.split("【", 1)[1].split("种】", 1)[0]
        else:
            race = "未知"
        races[race] += 1
        attribute_levels[attribute][level] += 1
        race_levels[race][level] += 1
        bucket = level_stats[level]
        bucket["count"] += 1
        bucket["attack_total"] += float(card["attack"])
        bucket["defence_total"] += float(card["defence"])
        bucket["magic_total"] += float(card["magic"])
        for stat in ("attack", "defence", "magic"):
            value = float(card[stat])
            label = str(int(value)) if value.is_integer() else str(value)
            level_stat_distributions[level][stat][label] += 1
        monster_effect_types = {str(effect["type"]) for effect in card["effects"]}
        if "monster_attribute" in monster_effect_types:
            monster_content_coverage["通常属性"] += 1
        if "monster_reactive_attribute" in monster_effect_types:
            monster_content_coverage["响应属性"] += 1
        if "monster_skill" in monster_effect_types:
            monster_content_coverage["怪物技能"] += 1
        if str(card.get("description", "")).strip():
            monster_content_coverage["种族或描述"] += 1
    level_averages = {}
    for level, values in level_stats.items():
        count = values["count"]
        level_averages[level] = {"count": int(count), "attack": round(values["attack_total"] / count, 2), "defence": round(values["defence_total"] / count, 2), "magic": round(values["magic_total"] / count, 2)}
    for card in prophecies:
        introduction = str(card.get("introduction", "")).strip()
        if introduction.startswith("【快速"):
            prophecy_types["快速"] += 1
        elif introduction.startswith("【永续/装备"):
            prophecy_types["永续/装备"] += 1
        elif introduction.startswith("【永续/场景"):
            prophecy_types["永续/场景"] += 1
        elif introduction.startswith("【永续"):
            prophecy_types["永续"] += 1
        else:
            prophecy_types["普通"] += 1
        prophecy_effect_types = {str(effect["type"]) for effect in card["effects"]}
        has_effect = "prophecy_effect" in prophecy_effect_types
        has_reactive = "prophecy_reactive_effect" in prophecy_effect_types
        if has_effect and has_reactive:
            prophecy_effect_coverage["效果 + 响应"] += 1
        elif has_effect:
            prophecy_effect_coverage["仅效果"] += 1
        elif has_reactive:
            prophecy_effect_coverage["仅响应"] += 1
        else:
            prophecy_effect_coverage["无效果记录"] += 1
    permanent = sum(count for name, count in prophecy_types.items() if name.startswith("永续"))
    matrix_sort = lambda item: (-sum(item[1].values()), item[0])
    sorted_stat_distributions = {
        level: {
            stat: dict(sorted(values.items(), key=lambda item: float(item[0])))
            for stat, values in distributions.items()
        }
        for level, distributions in sorted(level_stat_distributions.items(), key=lambda item: float(item[0]))
    }
    return {
        "total": len(cards),
        "monster_count": len(monsters),
        "prophecy_count": len(prophecies),
        "cards_without_decks": sum(1 for card in cards if not card["decks"]),
        "level_distribution": dict(sorted(levels.items(), key=lambda item: float(item[0]))),
        "attribute_distribution": dict(attributes.most_common()),
        "race_distribution": dict(races.most_common()),
        "deck_distribution": dict(deck_counts.most_common()),
        "effect_type_distribution": dict(effect_types.most_common()),
        "prophecy_type_distribution": dict(prophecy_types),
        "prophecy_effect_coverage": dict(prophecy_effect_coverage),
        "monster_content_coverage": dict(monster_content_coverage),
        "level_averages": dict(sorted(level_averages.items(), key=lambda item: float(item[0]))),
        "level_stat_distributions": sorted_stat_distributions,
        "attribute_level_matrix": {name: dict(values) for name, values in sorted(attribute_levels.items(), key=matrix_sort)},
        "race_level_matrix": {name: dict(values) for name, values in sorted(race_levels.items(), key=matrix_sort)},
        "prophecy": {"permanent": permanent, "other": len(prophecies) - permanent},
    }
