ALTER TABLE effects RENAME COLUMN role TO profession;

CREATE TEMP TABLE skill_position_migration AS
SELECT
    e.id,
    ROW_NUMBER() OVER (
        PARTITION BY e.monster_card_id
        ORDER BY COALESCE(e.energy_cost, 0), COALESCE(t.text, '') COLLATE NOCASE, e.id
    ) - 1 AS new_position
FROM effects e
LEFT JOIN effect_translations t ON t.effect_id=e.id AND t.language='zh'
WHERE e.effect_type='monster_skill';

UPDATE effects
SET position=position+100000
WHERE effect_type='monster_skill';

UPDATE effects
SET position=(SELECT new_position FROM skill_position_migration WHERE id=effects.id)
WHERE effect_type='monster_skill';

DROP TABLE skill_position_migration;
