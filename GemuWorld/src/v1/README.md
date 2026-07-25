# GemuWorld source guide

## V1.15.0 monster attributes and effect capacity

The card editor now derives the English monster attribute from the selected Chinese attribute. Chinese values are chosen from every known Chinese/English attribute pair in the current database, exposed by `GET /api/monster-types`; the English field is no longer independently editable. The former `独占效果` section is named `属性与技能`.

A monster card may contain at most one normal attribute, one reactive attribute, and three skills. The card editor chooses an available type when adding an effect, disables addition when every slot is full, and excludes full types from the unassigned-effect picker. Existing effect types remain editable, but an invalid combination is rejected transactionally with its specific reason. The same aggregate rule is enforced by card saves, direct effect edits and copies, CSV imports, and effect-backup restores. A save error remains visible until a later save succeeds.

Profession tags, marker, and notes now form a separated design-metadata block at the bottom of effect detail cards in both editors.

Deleting an effect from the card editor now means **unlink**: the stable effect row and all of its design data remain in SQLite and return to the unassigned effect library. Migration `013_allow_effect_detach.sql` permits attached-to-unassigned transitions while continuing to reject direct moves between cards. Only **永久删除卡效** in the standalone effect editor deletes the effect row itself. Permanent deletion is version-checked and, when the effect was attached, also updates the owning card's version. One-level card undo can reattach an effect under its original stable effect ID.

## V1.14.0 automatic saving and one-level undo

The card and effect editors no longer expose manual save buttons. Editing controls become dirty on input and save when focus leaves the field; selects, checkboxes, profession tags, effect additions/removals, and library attachments save immediately. Opening another card/effect waits for the current save queue to finish, preventing a late response from overwriting the newly opened form. Copy, archive, delete, effect export, and effect import also flush pending edits first.

Each editor keeps exactly one pre-save snapshot. After a successful automatic save, **撤销上次更改** restores that snapshot using the current optimistic-lock versions, then clears itself. The button is disabled and gray before the first reversible save, after one undo, and after switching records. Initial creation of a new card/effect is not itself undoable. Autosaves are serialized and revision-aware so input entered while an earlier request is in flight remains dirty and is saved next.

## V1.13.0 shared effect editing rules and searchable library picker

The card editor and the standalone effect editor now load `web/effect_editor_shared.js` for their common effect labels, headings, profession styles, capability checks, and compact text summaries. The card editor continues to own its aggregate save workflow, but its embedded effect detail cards follow the same field rules and presentation logic as the standalone editor. “从卡效库添加” now provides live search plus a select box whose options contain the effect name/type and a shortened Chinese effect preview.

Effect searches also index the user-facing Chinese type labels. For example, searching `技能` returns every matching unassigned monster skill rather than only effects whose name or body explicitly contains that word; `属性` and `效果` work the same way for their corresponding types.

The current-list JSON import and export actions are displayed as compact gray text links on the first row of the left effect list, keeping the primary filter controls visually focused.

Only monster skills may store or edit Mana cost and Chinese/English effect names. Normal attributes, reactive attributes, prophecy effects, and prophecy reactive effects omit those controls in both editors. Migration `012_effect_field_capabilities.sql`, the write APIs, JSON restore, and validation checks enforce the same rule and remove incompatible legacy values.

## V1.12.0 card-detail effect editors

Every effect card embedded in the card editor now follows the card-effect detail page: detail title, type, compact energy/valuation row, marker, removable profession tags, visible profession presets, bilingual names and effect text, and notes. Fields printed on cards use bold labels under the same rules as the standalone effect editor. The effect card keeps card-level transactional saving and adds only a compact delete button at its upper-right corner.

## V1.11.0 card-ID artwork lock and transactional renamer

Artwork paths are now a database invariant: every card must use `pics/<card_id>.png`. SQLite triggers reject direct writes that violate it, and the card editor no longer exposes an image-path field. Card CRUD, legacy import, and batch CSV import derive the path from the stable card ID and ignore incoming image-path values.

Run `python scripts/rename_card_images.py` for a read-only preflight. Add `--verbose` to include every mapping. Run with `--apply` only after reviewing errors and warnings. The apply operation stages all source files in the artwork directory, creates one PNG per card (copying shared sources), updates SQLite in one transaction, writes a recovery manifest under `data/tmp/`, and restores original files if an operation fails. Cards without source artwork still receive their locked database path and are reported as warnings; unrelated orphan files are reported but never deleted.

## V1.10.0 canonical artwork paths

Card image paths have one portable database form: `pics/<filename>`, corresponding to files under `data/current/pics/`. Card-list API records expose both canonical `image_path` and browser-ready `image` (`/pics/<filename>`). The server serves `/pics/` directly and retains `/pictures/` as a legacy alias. Legacy CSV imports normalize `pictures/...` automatically, while CSV exports deliberately translate back to `pictures/...` for the unchanged legacy Viewer contract. This separation prepares an image-renaming utility to update files and canonical database paths without coupling data to a Windows absolute path.

## V1.9.4 species-only description handling

The monster description indicator and the `有描述` filter ignore one leading species marker such as `【龙种】`. A grey block now appears only when non-whitespace description text remains after that marker.

## V1.9.3 compact single-line card summaries

Monster rows now place a nonzero magic value in the leading purple capsule, show level as one star per level immediately after the card title, and render attack/defence as `(attack/defence)`. Level zero has no stars and zero magic has no capsule. Monster and prophecy effect indicators stay on the right side of the same row instead of occupying a second line.

## V1.9.2 card-editor filtering and sorting

The card editor sidebar has explicit `查询` and `添加卡牌` buttons. Monster lists can be filtered by level and by description/attribute/skill presence, then sorted by name, level, combat statistic, skill count, or update time. Prophecy lists can be filtered by the special kind parsed from their introduction and by introduction/effect presence, then sorted by name, special kind, effect count, response count, or update time. Pressing Enter in the card-name search also runs the query.

## V1.9.1 card-editor list summaries

The card editor list no longer exposes stable card IDs. Monster rows show a purple level capsule, title, attack/magic/defence values, and spaced color blocks for description, normal attributes, reactive attributes, and skills. Prophecy rows show the title, any leading special type such as `【永续/装备】`, and dark-blue or dark-red blocks for normal and responsive effects. Repeated blocks represent the number of matching effects.

## V1.9.0 effect JSON backup and restore

The effect editor exports the current filtered and sorted result list to an atomically written, timestamped JSON backup under `data/tmp/`. Each item contains its stable effect ID, exact owner card type and stable `card_id`, storage position, Mana cost, professions, valuation, marker, notes, version, timestamps, and every translation. The same page imports these backups transactionally, restoring missing effects under their original IDs or updating matching records; any validation or owner conflict rolls back the entire package. Imported attached effects also invalidate their parent card versions.

## V1.8.6 live effect-list preview

The selected effect row now previews visible right-hand edits immediately: Chinese skill name, Chinese effect text, valuation, and marker update as the user types. Profession changes synchronize after their existing auto-save path, and every successful save replaces the preview with the canonical API response. Preview changes alone do not write SQLite.

## V1.8.5 effect-type title colors

Effect-list titles use type-specific colors: monster skills black, normal attributes blue, reactive attributes red, prophecy effects dark blue, and prophecy reactive effects dark red. Detail headings and effect body text remain unchanged.

## V1.8.4 compact valuation precision

Effect-list valuation capsules round to one decimal place and omit a trailing `.0`. This display-only formatting leaves the full database valuation unchanged.

## V1.8.3 coin-style valuation capsule

Effect-list valuation capsules now contain only the numeric value. A bright highlighted gold gradient, gold border, and subtle inset shine give the capsule a coin-like appearance without displaying an `估值` label.

## V1.8.2 effect creation draft

Clicking **添加卡效** now opens an unsaved blank detail form immediately. Effect type is selected in that detail form and is required before save; only a successful save creates the standalone SQLite effect, so abandoning an untyped draft leaves no empty database record. Existing effects keep their type read-only.

## V1.8.1 effect-list valuation and ownership indicators

Non-empty effect valuations appear as gold capsules before profession tags; unset valuations render no placeholder. Unassigned effects show a small red ownership-status dot in the upper-right corner of their list row.

## V1.8.0 unassigned effect library

The effect editor can create a standalone card effect from a blank detail draft. Standalone effects keep their stable effect ID and all design fields in SQLite while showing `尚未链接卡牌`. The card editor can search unassigned, type-compatible effects by ID, name, or text and add one to the current card. Saving the card attaches that same database record atomically; an attached effect remains exclusive to one card and cannot later be moved or shared.

## V1.7.5 valuation in effect list

Effect rows no longer show their effect ID beside the title. That gray metadata position now shows `估值：数值`, or `估值：未设置` when empty. IDs remain available in effect details, exact-ID search, duplicate notices, and same-text navigation.

## V1.7.4 card-face field emphasis

Effect-detail field names that render on a card face use bold labels without changing the input text weight. Skills emphasize Mana cost, Chinese/English skill names, and Chinese/English effect text. Attributes and prophecy effects emphasize only their Chinese/English effect text; their non-rendered name fields and all design-only fields remain regular weight.

## V1.7.3 effect markers and notes

Effects add two editor-only design fields: `marker`, trimmed and limited to 10 Unicode characters, and unrestricted `notes`. Both the effect detail editor and card editor preserve them; effect copies carry them independently. Non-empty markers appear as small gray text in the left effect list, while notes remain detail-only and neither field enters the Viewer card model.

## V1.7.2 compact effect metrics

The effect detail form places Mana cost and valuation together in one compact row with 140-pixel controls. Effect type and the multi-profession tag editor each occupy their own full-width row so growing tag collections do not disturb the numeric layout.

## V1.7.1 profession containment and skill titles

Profession filtering explicitly uses tag containment: an effect matches when it contains any selected profession, regardless of its other tags. Monster-skill rows in the left effect list now use the same title convention as details: `技能 - 技能名`, falling back to `技能` when unnamed.

## V1.7.0 multi-profession effect tags

Effect professions are now an ordered many-to-many tag collection stored in `effect_professions`; migration 007 preserves every existing scalar profession as the first tag and removes the obsolete scalar column. The effect detail editor renders selected professions as removable `×` tags, accepts new tags with Enter or Chinese/English comma, and auto-saves preset additions and removals. The card editor reads and writes the same `professions` array. Lists, filters, sorting, counts, copies, and unset detection all use the relational tags as their single source of truth.

## V1.6.24 Chinese effect length sorting

The effect editor adds ascending and descending Chinese effect-text length sorts. Length is the number of Unicode characters after trimming leading and trailing whitespace. Equal lengths use Chinese text lexicographic order and then effect ID for deterministic results.

## V1.6.23 keyboard effect navigation

The effect editor supports `ArrowUp` and `ArrowDown` navigation through the current left-hand result list. Before moving, it saves every field in the current detail form through the normal version-checked update path; navigation stops on save errors or conflicts. The selected row scrolls into view. Arrow keys retain their native behavior while focus is inside inputs, textareas, selects, buttons, or editable content.

## V1.6.22 profession preset auto-save

Clicking a profession preset in an effect detail now fills the profession field and immediately submits the existing effect form. The normal version-conflict checks, card version update, profession counts, and success/error feedback all remain in the same save path.

## V1.6.21 multi-select profession count filters

The profession summary now includes the unset-effect count. Every count pill is a toggle: clicking selects it as a filter, clicking again removes it, and multiple selected professions use OR matching. Clearing every pill restores the unfiltered effect list. The existing profession select remains as a single-selection shortcut.

## V1.6.20 profession effect counts

The effect editor sidebar now shows an all-data profession summary between its filters and result list. Each profession pill includes its total effect-entry count; the five fixed professions remain colored (including zero-count presets), while database-defined professions remain gray. Counts do not change with the active list filters.

## V1.6.19 core profession contrast

The five core professions retain their individual colors in both effect-list pills and detail-form preset tags. All additional database-defined professions now use a neutral gray background, making the fixed core professions immediately distinguishable.

## V1.6.18 fixed core professions

`刺客`, `坦克`, `射手`, `法师`, and `辅助` are permanent profession presets and always appear first, whether or not current effects use them. Distinct database-defined professions follow without duplicating the core five. The five core list pills also use slightly stronger colors.

## V1.6.17 data-driven profession presets

Profession presets are no longer hard-coded. The effect filter and detail-form tags are built from every distinct non-empty profession currently stored in the effects database. Saving a new profession refreshes both controls immediately.

## V1.6.16 searchable effect-copy targets

The **Copy to card** control now includes an instant target search. It filters compatible cards by Chinese card title or `card_id`, displays the matching count, and shows `card_id` beside every title so duplicate names remain distinguishable.

## V1.6.15 professions and canonical skill order

The effect design key `role` is migrated to `profession` without losing existing values. The effect detail form no longer exposes storage positions. Monster skills alone receive canonical positions: ascending Mana cost, then Chinese effect-text lexicographic order, then effect ID as a stable tie-breaker. Existing skills are reordered during migration, and card/effect saves and copies reapply the same rule.

## V1.6.14 Chinese effect text sorting

The effect editor can sort results lexicographically by Chinese effect text, with effect ID as the stable tie-breaker.

## V1.6.13 profession filtering

The effect editor filters by the five preset professions or by unset profession, and combines profession filtering with card type, effect type, keyword, and sorting parameters.

## V1.6.12 optional profession pills

Effects without a profession no longer render a placeholder pill in the list.

## V1.6.11 colored profession pills

Effect list professions appear as colored pills before the title. Pills contain only the profession name; custom and unset professions use neutral styling.

## V1.6.10 effect roles in list

Every effect row shows its profession beside the effect ID; blank professions are shown as `职业：未设置`.

## V1.6.9 visible effect profession tags

Effect profession presets are always-visible tags beneath the free-text field. Clicking `刺客`, `坦克`, `射手`, `法师`, or `辅助` fills the input immediately.

## V1.6.8 effect profession suggestions

The effect detail profession field remains free text and also offers five suggestions: `刺客`, `坦克`, `射手`, `法师`, and `辅助`.

## V1.6.7 effect-focused list and headings

The effect list omits owning card names and focuses on effect labels, IDs, and text. Detail headings are effect-centric (`通常属性`, `反应属性`, `技能 - <name>`, etc.); owning card information remains available in the muted metadata line.

## V1.6.6 effect editor navigation and sorting

The effect overview is now named **卡效编辑**. Internal effect types use Chinese labels in the list and detail form. Results can be sorted by ID, owning card, effect type, profession, or valuation. Effect details expose global same-text matches and provide direct navigation buttons for each matching effect.

## V1.6.5 temporary CSV export

CSV snapshots no longer require a data version. They atomically replace the four card CSV files under `data/tmp/` and never change the active data version. Only a database snapshot uses `data/<version>/` and advances the active version after success.

## V1.6.4 active data version

The Viewer control-panel header shows the active data version. Clicking it changes the persisted export/import version, and the export dialog uses that value by default. A successful database snapshot advances the active value to the next major version (`v2.3` still advances to `v3`, not `v2.4`). The card editor remains full-width; deck and effect editors share the row below it.

## V1.6.3 versioned data export

The Viewer batch-export button now opens a format/version dialog. It scans `data/v*` folders and suggests the next major version (`v2.2` produces `v3`). CSV export writes all four Chinese/English monster/prophecy files; database export writes a consistent `gemuworld.sqlite3` backup. Output is staged and then published to `data/<version>/`, and an existing version directory is never overwritten.

## V1.6.2 effect design fields

Effects now have two editor-only design fields: `profession` (free text) and `valuation` (optional number). Both fields can be edited from the card editor and effect editor, survive effect/card copying, and remain absent from the Viewer card display model.

## V1.6.1 cross-editor concurrency

V1.6.1 closes the lost-update gap between the card editor and effect editor while retaining one physical source of truth.

- Card detail responses include each owned effect's `version`.
- Aggregate card saves validate both the card version and every retained effect version.
- A successful card save increments the card version and the versions of effects it updates.
- A direct effect edit increments both the effect version and its owning card version.
- Copying an effect increments the target card version.
- Stale card or effect forms receive HTTP 409 and must reload; no old form can silently overwrite a change made through the other editor.

This makes bidirectional editing strict: both pages operate on the same `effects` / `effect_translations` rows, and all application write paths participate in the same optimistic-concurrency boundary.

## V1.6 effects and design guides

V1.6 completes the first industrialized roadmap with two management surfaces:

- [Effect overview](http://127.0.0.1:8000/effects)
- [Design guides](http://127.0.0.1:8000/design-guides)

The effect overview searches by card type, one of the five effect types, card name, effect name, or effect text. Every result shows its single owning card. Editing can change localized name/text, energy cost, and position, but never the owner. Version conflicts return HTTP 409.

Exact normalized Chinese effect-text duplicates are marked with their other effect IDs. **Copy to card** creates a new effect row and translation rows on a compatible target card; it never shares or moves the source effect. Subsequent edits remain independent.

The design-guide page edits imported Markdown guides and the structured monster-stat benchmark table. Both use optimistic versions and write audit records. The benchmark table exposes level, total-stat budget, attack/defence limits, effect tier, and one/two/multi-bonus configurations.

V1.6 API routes:

```text
GET  /api/effects
GET  /api/effects/{id}
PUT  /api/effects/{id}
POST /api/effects/{id}/copy

GET /api/design-guides
PUT /api/design-guides/{id}

GET /api/monster-benchmarks
PUT /api/monster-benchmarks/{id}
```

Migration `003_effect_guide_versions.sql` adds version control to effects, guides, and monster benchmarks, plus active/archive status for design guides.

## V1.5 deck management

V1.5 replaces manual clan-file maintenance with transactional deck management at [http://127.0.0.1:8000/decks](http://127.0.0.1:8000/decks).

The page supports:

- creating and editing Chinese/English deck names, display order, and type; the English name is mirrored to the legacy `code` field while an immutable hidden `deck_id` carries identity;
- `default`, `role`, `tutorial`, and `temporary` deck types;
- Chinese and English names, summaries, and Markdown descriptions;
- adding monster and prophecy cards by stable database identity;
- removing and reordering members;
- per-member section and quantity metadata;
- archiving and permanent deletion;
- optimistic version conflict protection.

Deck metadata, translations, and the complete ordered member list save in one transaction. Any invalid or archived member, duplicate member, unknown card, duplicate English name, or version conflict rolls back the whole edit. Chinese names default to the English name when left blank. Saving from the deck page updates the same `deck_cards` relationships used by the card editor, Viewer, statistics, and exports, so no synchronization job is required.

Five role decks use the normal deck/member tables with `deck_type=role`. They retain their ordering and section metadata without a separate special-case database.

API routes:

```text
GET    /api/decks/{id}
POST   /api/decks
PUT    /api/decks/{id}
DELETE /api/decks/{id}?version=N&permanent=false
```

Saving also regenerates the compatibility Markdown representation from the Chinese description and ordered members. The normalized database remains authoritative; legacy clan URLs are export/compatibility views only.

## V1.4 card CRUD

V1.4 makes SQLite the card-development entry point. Open [http://127.0.0.1:8000/editor](http://127.0.0.1:8000/editor) or use the **Card editor** link in the Viewer.

The editor supports:

- searching and switching between monster and prophecy cards;
- creating cards with generated or supplied stable IDs;
- editing canonical stats, image paths, Chinese content, and optional English translations;
- adding, reordering, editing, and removing card-owned effects;
- assigning zero or more decks;
- copying a card with independent effect IDs;
- archiving a card without destroying history;
- permanently deleting a card and its dependent translations, effects, and memberships.

Card save is an aggregate transaction: base data, both translations, all effects, and all deck memberships either commit together or roll back together. Existing card updates require the version returned by the detail API. A stale editor receives HTTP 409 instead of silently overwriting a newer change.

Effects remain strictly card-owned. The API rejects an effect ID belonging to another card. Copying creates new effect rows, so later edits cannot affect the source card.

API routes:

```text
GET    /api/cards/{monster|prophecy}/{id}
POST   /api/cards/{monster|prophecy}
PUT    /api/cards/{monster|prophecy}/{id}
POST   /api/cards/{monster|prophecy}/{id}/copy
DELETE /api/cards/{monster|prophecy}/{id}?version=N&permanent=false
```

`permanent=false` archives the card and removes it from normal Viewer, statistics, and export queries. `permanent=true` physically deletes it. Both require the current version. Every create, update, archive, delete, batch import, and copy-backed create is written to `change_log`.

## V1.3.2 transactional batch card import

V1.3.2 supports importing the existing pipe-delimited `monster_cards.csv` and `prophecy_cards.csv` schemas through [http://127.0.0.1:8000/import](http://127.0.0.1:8000/import), `POST /api/import`, or the CLI.

Matching uses the exact Chinese card title:

- one existing match updates the card's canonical fields and owned effects;
- no match creates a new card;
- multiple existing matches reject the entire batch as ambiguous;
- duplicate titles inside the uploaded file reject the entire batch.

An overwrite preserves the database's internal row ID, stable `card_id`, deck memberships, and English effect translations for effect slots that still exist. The incoming `card_id` is used only for a newly created card; a different incoming ID on an existing title is reported and ignored. Effects removed from the incoming card are deleted. English card translations are not overwritten by a Chinese CSV.

Every import runs in one `BEGIN IMMEDIATE` transaction. A malformed number, invalid effect JSON, duplicate ID, ambiguous title, or any other failure rolls back every card in the upload. The web page provides a dry-run preview before confirmation, and successful writes are recorded in `change_log`.

CLI examples:

```powershell
# Default: import both data/transport files
python scripts/import_cards.py --dry-run
python scripts/import_cards.py

# Import one default transport file
python scripts/import_cards.py monster
python scripts/import_cards.py prophecy

# Import an explicitly selected file
python scripts/import_cards.py monster path/to/monster_cards.csv --dry-run
python scripts/import_cards.py monster path/to/monster_cards.csv
python scripts/import_cards.py prophecy path/to/prophecy_cards.csv
```

The default transport inbox is `data/transport/`. Before a two-file write, both files receive a full dry-run validation, so a malformed prophecy file cannot be discovered only after the monster file has already been applied. Use `--transport-dir <path>` to select another inbox while retaining the standard filenames.

API payload:

```json
{
  "card_type": "monster",
  "csv": "card_id|card_title|...",
  "dry_run": true
}
```

Batch import changes SQLite only. It does not rewrite `data/current/cards`; use the export API or `scripts/export_legacy_data.py` when a new legacy snapshot is required.

## V1.3.1 direct-API Viewer

V1.3.1 removes the Viewer's runtime dependency on CSV and clan Markdown. `_viewer.html` now requests:

```text
GET /api/cards
GET /api/decks
POST /api/export
GET /pictures/<asset>
```

The API response is adapted in memory to the established card-rendering objects, preserving the existing DOM, CSS, special client-side sort modes, 63 × 88 mm cards, and 3×3 print behavior. Deck membership and default deck order use stable card IDs and hidden deck IDs instead of matching editable names.

Database commits are visible after refreshing the Viewer; the service does not need to restart and no CSV cache is rebuilt. Automated HTTP coverage commits a title change while the server is running and verifies that the next API query returns it.

Legacy card CSV and clan URLs remain available for historical compatibility, but they are generated from SQLite only when explicitly requested. They are not generated at server startup and are not fetched by the Viewer.

## V1.3 export and statistics

V1.3 adds read-only release tooling on top of the V1.2 query layer:

- **Export current cards** in the Viewer exports the exact cards currently rendered, in their visible order. A monster-only or prophecy-only result downloads one pipe-delimited CSV; a mixed result downloads a ZIP containing both schemas.
- **Card statistics** at [http://127.0.0.1:8000/stats](http://127.0.0.1:8000/stats) supports language, card type, deck, and keyword filters, and reports totals, level/stat averages, attributes, races, effect types, deck distribution, unassigned cards, and persistent prophecies.
- `GET /api/export` provides programmatic filtered/sorted export using the same parameters as `/api/cards`.
- `POST /api/export` accepts `{"language":"zh","card_ids":[...]}` and preserves the supplied order; the Viewer uses this route so client-only legacy sort modes remain exact.
- `GET /api/statistics` accepts the same language, type, deck, deck matching, and keyword filters as `/api/cards`.

Examples:

```text
GET /api/export?language=zh&card_type=monster&deck=Intro&sort_by=level&direction=asc
GET /api/statistics?language=zh&deck=Wind
GET /api/statistics?language=en&card_type=prophecy&keyword=damage
```

All exports retain the legacy `|`, `\|`, and `\n` conventions. Shared numeric data and energy costs remain canonical Chinese values; localized text comes from the requested language. Cards without that translation are excluded. Export and statistics do not mutate the database.

The V1.3 automated suite verifies that filtered statistics use the same card set as queries, mixed exports contain the two correct CSV files, single-type exports preserve order, Viewer-selected IDs survive the HTTP export round trip, and the statistics page consumes `/api/statistics`.

## V1.2 read-only API and Viewer

V1.2 serves the existing card-rendering and 3×3 print specification from the V1.1 SQLite database. Start it from this directory:

```powershell
python scripts/serve.py
```

Then open [http://127.0.0.1:8000/viewer](http://127.0.0.1:8000/viewer). `launch.bat`, `make launch`, and `make serve` start the same application.

The Viewer HTML and CSS were deliberately reused as the print baseline. V1.2 initially used generated legacy resources as a compatibility bridge; V1.3.1 replaced that bridge with direct JSON API calls while retaining the existing behavior, card dimensions, text fitting, sorting controls, clan filtering, language switch, and print workflow. The print contract remains:

- card size: 63 × 88 mm;
- three fixed columns (`--cols: 3`);
- 0.53 mm print gap and border;
- cards use `page-break-inside: avoid`;
- browser controls and sidebar are hidden under `@media print`;
- the existing print script applies fixed card and grid classes before printing.

English legacy resources and API results omit cards that have no English translation, as required. Shared stats and energy costs always come from the canonical Chinese card.

### Read-only API

```text
GET /api/health
GET /api/decks?language=zh
GET /api/cards?language=zh&card_type=all
```

`/api/cards` accepts:

| Parameter | Values |
| --- | --- |
| `language` | `zh`, `en` |
| `card_type` | `all`, `monster`, `prophecy` |
| `deck` | one code, comma-separated codes, or repeated parameters |
| `deck_match` | `any`, `all` |
| `keyword` | free-text search over the localized card payload |
| `sort_by` | `updated_at`, `card_id`, `title`, `level`, `attack`, `defence`, `magic` |
| `direction` | `asc`, `desc` |
| `limit` | non-negative integer |

Each card includes localized content, owned effects, and all deck memberships. Each deck includes its type, order, normalized member count, and preserved Markdown description. The API is read-only in V1.2.

For historical compatibility, these paths are generated from SQLite on demand; the Viewer does not request them:

```text
/monster_cards.csv
/monster_cards_en.csv
/prophecy_cards.csv
/prophecy_cards_en.csv
/clans/_clans.json
/clans/<deck>.md
```

### V1.2 verification

The automated suite exercises localized queries, missing-English exclusion, deck filtering, five role decks, deterministic sorting, HTTP routes, generated legacy resources, and the fixed print CSS contract:

```powershell
python -m unittest discover -s tests -v
```

Legacy CSV rows reference artwork as `pictures/<filename>`. The V1.2 server maps that public URL safely to the maintained asset directory at `data/current/pics/`, including `grid.png`; no duplicate `pictures/` directory is required. Missing files return HTTP 404 without reading outside the asset directory.

## V1.1 data foundation

V1.1 introduces the first industrialized data layer while leaving the legacy HTML and `data/current` sources untouched. The generated SQLite database at `data/gemuworld.sqlite3` is now the normalized development data store for subsequent versions.

The implementation intentionally uses Python's standard-library `sqlite3`; no package installation is required. Versioned SQL files in `migrations/` create and upgrade the schema. The first migration provides:

- separate canonical monster and prophecy tables;
- language-specific translations attached to the same card ID;
- card-owned effects for monster skills, normal/reactive attributes, and prophecy normal/reactive effects;
- a database trigger that prevents moving or sharing an effect between cards;
- decks, preserved clan Markdown, ordered deck membership, and special `role` deck types;
- Markdown design guides, structured monster-stat benchmarks, and generic reference-table rows;
- import issue and future change-log tables.

### V1.1 commands

Run commands from `GemuWorld/src/v1` with Python 3.11 or newer:

```powershell
# Exercise the full migration without changing the target database
python scripts/import_legacy_data.py --dry-run

# Rebuild normalized data transactionally and write a machine-readable report
python scripts/import_legacy_data.py --report data/v1.1-import-report.json

# Check foreign keys, ownership rules, and required Chinese card translations
python scripts/validate_data.py --include-import-errors

# Export cards and clans in the legacy layout
python scripts/export_legacy_data.py --output data/export

# Run schema, ownership, idempotency, and semantic round-trip tests
python -m unittest discover -s tests -v
```

Import is deterministic and idempotent: it replaces imported domain rows inside one transaction, while preserving the schema and migration history. `--dry-run` uses a temporary database. `--strict` additionally treats migration warnings as failure.

Chinese card rows are canonical for shared game data such as level, stats, image, and skill energy cost. English rows contribute translations only. Historical duplicate English IDs are resolved by selecting the newest timestamp; missing translations and conflicting shared values are retained in `import_issues` and the JSON report.

Clan Markdown is preserved verbatim in `decks.source_markdown_zh`. Recognized card lines are additionally normalized into `deck_cards`; `//` and Markdown headings are retained as section metadata. Ambiguous or duplicate legacy membership is reported rather than silently assigned.

### V1.1 acceptance snapshot

The checked-in V1.1 migration produced:

| Entity | Count |
| --- | ---: |
| Monster cards | 258 |
| Prophecy cards | 252 |
| Owned effects | 857 |
| Decks | 27 |
| Normalized deck memberships | 986 |
| Markdown design guides | 7 |
| Monster stat benchmarks | 49 |
| Other reference rows | 190 |

Structural validation passes with no errors. The import report currently contains warnings for legacy translation gaps/conflicts, duplicate English IDs, duplicate clan entries, and the ambiguous duplicate Chinese title `护法童子`. These warnings are source-data cleanup work, not structural database failures; the raw clan Markdown remains preserved losslessly.

This directory contains the card-authoring data and browser tools for **GemuWorld**, a two-player tabletop card game. It is not a game engine: the implementation is a collection of self-contained HTML pages that read and write pipe-delimited card files, plus Markdown files that define named decks/clans.

## Repository map

```text
src/
├── README.md                 # this guide
├── 开发日志.md               # development log
└── v1/
    ├── _viewer.html          # card renderer, deck filter, and print/PDF view
    ├── _editor.html          # local CSV editor
    ├── _stats.html           # card statistics and charts
    ├── _appendix.html        # printable player-board appendix
    ├── Makefile              # starts a static HTTP server on port 8000
    ├── launch.bat            # Windows equivalent
    ├── How_to_edit.md        # older launch note; filenames in it are stale
    ├── backend/gemuworld_db/ # V1.1 SQLite data and legacy-codec library
    ├── migrations/           # ordered, atomic database schema upgrades
    ├── scripts/              # import, export, and validation commands
    ├── tests/                # standard-library automated tests
    ├── data/
    │   ├── gemuworld.sqlite3 # generated normalized V1.1 database
    │   ├── current/
    │   │   ├── cards/        # active Chinese and English card databases
    │   │   └── clans/        # active deck lists and their index
    │   ├── v0 ... v2.2/      # historical snapshots
    │   └── test/             # test/raw CSV fixtures
    ├── agent/
    │   ├── agents.md         # game rules and card-design agent role
    │   ├── skills/           # reusable card/deck design procedures
    │   └── workflow/         # end-to-end design workflows
    └── utils/
        └── cards_csv_modifier.ipynb
```

The project-level `GemuWorld/manual/` directory contains the human-facing card-design process, theory, balancing tables, and scripts. `GemuWorld/Tutorial/` contains game tutorials and abbreviated rules. These support the source tree but are not loaded by the browser pages.

## Architecture and data flow

The legacy browser tools have no framework or shared JavaScript module. Each HTML file contains its own CSS, state, parsing, and rendering logic. V1.1 adds a framework-free Python/SQLite data layer alongside them; the HTML pages will move to that data source in later subversions.

```text
monster_cards*.csv ─┐
                    ├──> viewer ──> rendered cards / browser print-to-PDF
prophecy_cards*.csv ┤
                    ├──> stats  ──> KPIs, tables, and Chart.js charts
clans/_clans.json ──┤
clans/*.md ─────────┘

local CSV file <──> editor ──> File System Access save or CSV download
```

### `_viewer.html`

The main card presentation page:

- fetches `monster_cards.csv` and `prophecy_cards.csv`, or their `_en.csv` counterparts when English is selected;
- parses the custom pipe-delimited format and the JSON stored in monster `attributes` and `skills` fields;
- renders monster and prophecy cards with artwork referenced by each row's `image` field;
- loads `clans/_clans.json`, then loads each listed `clans/<name>.md` file;
- filters cards by one or more clans, reports deck entries that do not match a card title, and supports several sort modes;
- lays cards out for browser printing/PDF export.

Clan files are deliberately simple: after blank lines and Markdown headings/list markers are removed, each remaining line is treated as an exact card title. Consequently, changing a card title can break clan membership until every affected clan file is updated.

### `_editor.html`

A client-side CRUD editor for the two card types. It opens CSVs chosen by the user, converts rows into in-memory card objects, edits them in forms, and serializes them back to the canonical column order. It supports direct writes through the browser File System Access API and a download fallback. New cards receive generated IDs and timestamps.

The editor does **not** automatically open `data/current/cards`; select the desired file explicitly. Direct save requires a compatible browser and a secure context such as `localhost`.

### `_stats.html`

Loads `monster_cards.csv` and `prophecy_cards.csv` over HTTP and computes counts and distributions for card type, level, monster attribute, race, attack, defence, magic, and prophecy effect categories. It uses Bootstrap, Papa Parse, and Chart.js from public CDNs, so its styling and charts require network access unless those dependencies are vendored.

### `_appendix.html`

A standalone printable A4 landscape player board with three monster slots, three prophecy slots, a deck, and a discard pile. It has no card-data dependency.

## Card data format

Despite the `.csv` extension, files use `|` as the delimiter. Literal pipes and newlines inside text are represented as `\|` and `\n`. Files are UTF-8 and begin with a header row.

Monster columns:

```text
card_id|card_title|level|monster_type|description|attack|defence|magic|attributes|skills|image|last_update_datetime
```

- `attributes` is a JSON object, normally with `normal_attribute` and/or `responsive_attribute`.
- `skills` is a JSON array of objects containing `name`, `energy_cost`, and `effect`.
- `image` is expected to resemble `pictures/<asset-name>.png` in the deployed site.

Prophecy columns:

```text
card_id|card_title|introduction|effect|responsive_effect|image|last_update_datetime
```

The files in `data/current/cards/` are the active source of truth. The version-numbered directories are snapshots and should not be silently updated alongside current data.

## Running the tools

The browser pages use `fetch`, so opening them directly with a `file://` URL is unreliable. Start a local server:

```powershell
cd GemuWorld/src/v1
py -m http.server 8000
```

or run `launch.bat`; on systems with GNU Make and `python3`, run `make launch`.

There is currently no build/deployment script. The underscore-prefixed HTML sources assume a served directory containing non-prefixed page names and the active assets beside them:

```text
viewer.html
editor.html
stats.html
appendix.html
monster_cards.csv
monster_cards_en.csv
prophecy_cards.csv
prophecy_cards_en.csv
clans/
pictures/
```

The repository does not currently assemble that layout automatically, and the checked-in `GemuWorld/viewer.html` is empty. To test a page without changing source data, create a temporary served directory, copy/rename the HTML templates, copy `data/current/cards/*` and `data/current/clans/`, and provide the referenced `pictures/` assets. Do not treat the versioned snapshot directories as deployment targets.

## Making changes safely

1. Edit the active Chinese and, where applicable, English CSV together; both viewer modes rely on matching schemas.
2. Preserve the exact header names, pipe escaping, JSON validity, UTF-8 encoding, and timestamps.
3. If a title changes, search `data/current/clans/*.md` and update exact-name references.
4. If `_viewer.html` or `_stats.html` changes its schema interpretation, keep `_editor.html` serialization compatible.
5. Serve the staged layout and verify the viewer, editor round-trip, statistics page, and print preview.
6. Add a new clan Markdown filename (without `.md`) to `data/current/clans/_clans.json`; file-name casing must match.

## Known maintenance issues

- Parsing logic and schema knowledge are duplicated across the viewer, editor, and statistics pages, so a format change must be implemented in all three.
- `_stats.html` links to `editor.html`, while the source file is `_editor.html`; this only works after the intended rename/staging step.
- `How_to_edit.md` refers to older `cards.html` and `edit_cards.html` names.
- Artwork is referenced as `pictures/...`, but no `pictures` directory is present in this repository snapshot.
- `GemuWorld/viewer.html` is currently a zero-byte file rather than a generated/deployed viewer.
