CREATE TABLE monster_cards (
    id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL UNIQUE,
    level INTEGER NOT NULL CHECK(level >= 0),
    monster_type TEXT NOT NULL DEFAULT '',
    attack REAL NOT NULL,
    defence REAL NOT NULL,
    magic REAL NOT NULL,
    image_path TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('draft', 'active', 'archived')),
    source_updated_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0)
);

CREATE TABLE monster_card_translations (
    monster_card_id INTEGER NOT NULL REFERENCES monster_cards(id) ON DELETE CASCADE,
    language TEXT NOT NULL,
    title TEXT NOT NULL,
    monster_type TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    source_updated_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (monster_card_id, language)
);

CREATE TABLE prophecy_cards (
    id INTEGER PRIMARY KEY,
    card_id TEXT NOT NULL UNIQUE,
    image_path TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('draft', 'active', 'archived')),
    source_updated_at TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0)
);

CREATE TABLE prophecy_card_translations (
    prophecy_card_id INTEGER NOT NULL REFERENCES prophecy_cards(id) ON DELETE CASCADE,
    language TEXT NOT NULL,
    title TEXT NOT NULL,
    introduction TEXT NOT NULL DEFAULT '',
    source_updated_at TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (prophecy_card_id, language)
);

CREATE TABLE effects (
    id INTEGER PRIMARY KEY,
    monster_card_id INTEGER REFERENCES monster_cards(id) ON DELETE CASCADE,
    prophecy_card_id INTEGER REFERENCES prophecy_cards(id) ON DELETE CASCADE,
    effect_type TEXT NOT NULL CHECK(effect_type IN (
        'monster_skill', 'monster_attribute', 'monster_reactive_attribute',
        'prophecy_effect', 'prophecy_reactive_effect'
    )),
    position INTEGER NOT NULL DEFAULT 0 CHECK(position >= 0),
    energy_cost REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK ((monster_card_id IS NOT NULL) <> (prophecy_card_id IS NOT NULL)),
    CHECK (
        (monster_card_id IS NOT NULL AND effect_type LIKE 'monster_%') OR
        (prophecy_card_id IS NOT NULL AND effect_type LIKE 'prophecy_%')
    )
);

CREATE TABLE effect_translations (
    effect_id INTEGER NOT NULL REFERENCES effects(id) ON DELETE CASCADE,
    language TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (effect_id, language)
);

CREATE UNIQUE INDEX effects_monster_slot
ON effects(monster_card_id, effect_type, position) WHERE monster_card_id IS NOT NULL;
CREATE UNIQUE INDEX effects_prophecy_slot
ON effects(prophecy_card_id, effect_type, position) WHERE prophecy_card_id IS NOT NULL;

CREATE TRIGGER effects_owner_immutable
BEFORE UPDATE OF monster_card_id, prophecy_card_id ON effects
WHEN OLD.monster_card_id IS NOT NEW.monster_card_id
  OR OLD.prophecy_card_id IS NOT NEW.prophecy_card_id
BEGIN
    SELECT RAISE(ABORT, 'an effect cannot be shared or moved between cards; copy it instead');
END;

CREATE TABLE decks (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    deck_type TEXT NOT NULL DEFAULT 'default'
        CHECK(deck_type IN ('default', 'role', 'tutorial', 'temporary')),
    display_order INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'archived')),
    source_filename TEXT NOT NULL DEFAULT '',
    source_markdown_zh TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE deck_translations (
    deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    language TEXT NOT NULL,
    name TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (deck_id, language)
);

CREATE TABLE deck_cards (
    deck_id INTEGER NOT NULL REFERENCES decks(id) ON DELETE CASCADE,
    monster_card_id INTEGER REFERENCES monster_cards(id) ON DELETE CASCADE,
    prophecy_card_id INTEGER REFERENCES prophecy_cards(id) ON DELETE CASCADE,
    position INTEGER NOT NULL CHECK(position >= 0),
    section TEXT NOT NULL DEFAULT '',
    quantity INTEGER NOT NULL DEFAULT 1 CHECK(quantity > 0),
    CHECK ((monster_card_id IS NOT NULL) <> (prophecy_card_id IS NOT NULL)),
    UNIQUE(deck_id, position),
    UNIQUE(deck_id, monster_card_id),
    UNIQUE(deck_id, prophecy_card_id)
);

CREATE TABLE design_guides (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    guide_type TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    source_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE monster_stat_benchmarks (
    id INTEGER PRIMARY KEY,
    level INTEGER NOT NULL,
    total_stats REAL NOT NULL,
    attack_max REAL NOT NULL,
    defence_max REAL NOT NULL,
    effect_tier REAL NOT NULL,
    one_bonus REAL,
    two_bonus REAL,
    multi_bonus REAL,
    source_row INTEGER NOT NULL,
    UNIQUE(level, total_stats, attack_max, defence_max, effect_tier)
);

CREATE TABLE reference_table_rows (
    id INTEGER PRIMARY KEY,
    table_code TEXT NOT NULL,
    position INTEGER NOT NULL,
    data_json TEXT NOT NULL,
    UNIQUE(table_code, position)
);

CREATE TABLE import_issues (
    id INTEGER PRIMARY KEY,
    severity TEXT NOT NULL CHECK(severity IN ('warning', 'error')),
    source TEXT NOT NULL,
    message TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE change_log (
    id INTEGER PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX deck_cards_monster ON deck_cards(monster_card_id);
CREATE INDEX deck_cards_prophecy ON deck_cards(prophecy_card_id);
CREATE INDEX effects_monster ON effects(monster_card_id);
CREATE INDEX effects_prophecy ON effects(prophecy_card_id);
