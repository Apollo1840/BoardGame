ALTER TABLE effects ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0);
ALTER TABLE design_guides ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0);
ALTER TABLE design_guides ADD COLUMN status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'archived'));
ALTER TABLE monster_stat_benchmarks ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK(version > 0);

