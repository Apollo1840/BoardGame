CREATE TABLE effect_professions (
    effect_id INTEGER NOT NULL REFERENCES effects(id) ON DELETE CASCADE,
    profession TEXT NOT NULL CHECK(TRIM(profession) <> ''),
    position INTEGER NOT NULL CHECK(position >= 0),
    PRIMARY KEY (effect_id, profession),
    UNIQUE (effect_id, position)
);

INSERT INTO effect_professions(effect_id, profession, position)
SELECT id, TRIM(profession), 0 FROM effects WHERE TRIM(profession) <> '';

ALTER TABLE effects DROP COLUMN profession;
