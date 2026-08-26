# LCT Project Context

> Initial context for future development conversations. Read this before changing the project, then inspect the current diff because the repository may have moved on.

## Snapshot

- Reviewed: 2026-07-21
- Branch/commit: `main` at local commit `695f1f0` (`additional dev tools for handling battlemaster maps`), one commit ahead of `origin/main` (`e03f480`) at review time.
- History reviewed: all 340 commits reachable from all local/remote refs, from `d81bafc` (2026-04-06) through `695f1f0` (2026-07-21), plus focused diffs and per-file histories for the systems below.
- Project: a Tabletop Simulator (TTS) save for Warhammer 40,000 11th edition, forked from Hutber's FTC table and heavily refactored.
- Current inventory: 255 manifest-listed competitive map cards across 15 source bags, plus 3 Combat Patrol payload cards outside the manifest. All 258 expected terrain payload files exist.
- Validation at review time: 0 errors, 1 warning; all 255 manifest maps use v2 loader machinery; 25 Python behavioral tests pass.
- Known validation warning: card `fd3d94` (`TnH vs Rec 1 - Tipping Point - T5S2`) has home/neutral objective tags but no required center/triangle pattern.

### Latest local commit at this snapshot

Commit `695f1f0` is not yet on `origin/main`. It contains:

- `CHANGELOG.md`: adds a top `v1.10.3` entry.
- `TTSJSON/ftc_base_ui.xml`: expands the debug panel and adds an `All 3` Battlemaster cache button.
- `TTSLUA/global.ttslua`: exposes the `All 3` debug action.
- `TTSLUA/battlemasterDynamicSpawner.ttslua`: archives per-theme caches and sequences multi-theme population.
- `scripts/import_battlemaster_static_maps.py`: adds an `--all-themes` import path using those archives.

Its new workflow is: populate Ruins, Desert, and BTTF sequentially in one debug table; archive each theme before the live one-theme cache is pruned; save once; import all three static map sets in one Python run.

## The shortest useful mental model

This is not a normal application with a single executable entry point. The source tree describes a TTS save:

1. `TTSJSON/ftc_base.json` is the source object graph: objects, decks, bags, GUIDs, transforms, and stripped map-card script heads.
2. `TTSLUA/*.ttslua` contains Global and per-object scripts. The first line of every per-object script declares the GUID or GUIDs that receive it.
3. `TTSJSON/ftc_base_ui.xml` is Global screen-space UI.
4. `data/map_manifest.csv` is the authoritative map inventory and metadata catalog.
5. `data/maps/<card_guid>.lua` stores each map card's large terrain payload outside the JSON.
6. `scripts/compile.py` validates the source, injects XML and Lua by GUID, bakes metadata/URLs/debug state, restores terrain payloads, injects map-load hooks, stamps a version, and writes a playable compiled save under `builds/`.

The source JSON is deliberately incomplete as a playable artifact. The compiled JSON is deliberately generated. Make source changes in `TTSLUA`, `TTSJSON/ftc_base_ui.xml`, the manifest/data files, or tooling—not by editing a compiled build.

## Repository map

| Path | Role |
| --- | --- |
| `README.md` | Supported development, map migration, validation, and Battlemaster workflows. |
| `CHANGELOG.md` | Top release version and player-facing patch notes; `compile.py --release` consumes it. |
| `TTSJSON/ftc_base.json` | Canonical TTS source save/object graph. Large but much smaller since terrain extraction. |
| `TTSJSON/ftc_base_ui.xml` | Global HUD, scoring overlays, splash, role menu, and hidden debug panel. |
| `TTSLUA/global.ttslua` | Central GUID registry, global state, HUD/scoring/secondary logic, debug dispatch, player seating, and Global readiness signal. |
| `TTSLUA/startMenu.ttslua` | Main orchestration object (`738804`): game-mode/setup menus, mission generation, map loading, map undo, deployment/objectives, turns/phases, and game start. |
| `TTSLUA/mapFilter.ttslua` | Creator/category filter and mat/theme picker UI; publishes selected creators to Global. |
| `TTSLUA/customDiceTable.ttslua` | Red/Blue dice-tray UI and spatial logic: spawning, filtering, reroll selection, quick roll, lethal/sustained helpers, bubbles, coherency, engagement, and highlight paint. |
| `TTSLUA/customKustom40kDiceRollerMk3.ttslua` | Hidden Red/Blue roller containers: xoshiro PRNG, roll-batch ownership, extraction/layout, result log, and RNG diagnostics. |
| `TTSLUA/SelectionHighlighter.ttslua` | Selection glow plus ownership API used by coherency/engagement/highlight-paint features. |
| `TTSLUA/battlemasterDynamicSpawner.ttslua` | Development scaffolding for Battlemaster API sync, reconstruction, caching, and creation of canonical loader cards. Runtime generation is dormant; shipped Battlemaster maps are static cards. |
| `TTSLUA/11eScoreSheet.ttslua` | Scoreboard and score controls; now defers GUID initialization until Global is ready. |
| `TTSLUA/missionManager.ttslua` | Per-player fixed/tactical secondary selection and lock-in. Global/start menu own shared mission state. |
| `data/map_card_machinery.lua` | Single canonical map-card Load/Clear implementation. Never fork this logic per map. |
| `data/map_manifest.csv` | Map GUID, source bag, logical name, creator, type, display label, and eligibility. |
| `data/maps/` | Extracted `objectJSONs = { ... }` terrain blobs, one per card GUID. |
| `scripts/validate_maps.py` | Structural/cross-file validator used directly and as the compiler gate. |
| `scripts/test_validate_maps.py` | 25 behavioral/regression tests for runtime contracts the structural validator cannot model. |
| `scripts/extract_map_payloads.py` / `map_payloads.py` / `audit_map_payloads.py` | Terrain payload extraction, shared helpers, and inventory/size audit. |
| `scripts/normalize_map_card.py` | Converts foreign map cards to canonical machinery, tags, notes, credits, and GUID rules. |
| `scripts/import_battlemaster_static_maps.py` | Converts a populated Battlemaster spawner cache into normal static LCT map cards and manifest rows. |
| `scripts/bake_battlemaster_cache.py` | Inspects/bakes/clears persisted spawner state. Static shipped maps should not require a warm runtime cache. |
| `builds/` | Generated playable saves. Do not treat these as source. |

Other Lua files are mostly self-contained physical helpers: clocks, CP/round/turn counters, scoring, reserve boards, memory bags, LOS markers, table-surface controls, objective/deployment buttons, army placement, wounds/activation tokens, and trash/vortex objects.

## Build pipeline and non-negotiable contracts

Run from the repository root unless a command says otherwise:

```bash
python3 scripts/validate_maps.py --require-map-tags
python3 -m unittest scripts.test_validate_maps
python3 scripts/audit_map_payloads.py --strict
python3 scripts/compile.py --test
```

`compile.py --test` stamps `DEBUG = true`, produces `builds/lct_base_test_compiled.json`, and attempts to copy it to the local TTS Saves folder. `--release` takes the version and notes from the top of `CHANGELOG.md`, stamps `DEBUG = false`, and also copies the result. A plain compile prompts for a version and does not copy by default. `--no-validate` is an explicit escape hatch, not a normal workflow.

The compiler performs these steps in order:

1. Parse the source JSON and run map validation.
2. Parse the top changelog section.
3. Discover every `.ttslua` file and its first-line GUID declarations.
4. Inject the XML into the top-level `XmlUI` field.
5. Stamp Global version, patch notes, and debug mode; bake the manifest-derived `MAP_INDEX`.
6. Inject each object script into the JSON object matching its GUID.
7. Bake canonical map machinery into the Battlemaster spawner and mat URL/name pools into `startMenu`.
8. Reattach `data/maps/<guid>.lua` terrain blobs to stripped card heads.
9. Inject `startMenu.onMapCardLoaded(...)` immediately after every canonical `loadMap` signature. The Battlemaster spawner's embedded machinery is explicitly skipped so the template string is not accidentally rewritten.
10. Stamp save name/game mode, reparse the finished JSON, write the build, and optionally copy it.

Preserve all compiler markers exactly:

- Global: `@@LCT_VERSION@@`, `@@LCT_PATCH@@`, `@@LCT_CHANGELOG@@`, `@@LCT_DEBUG@@`, `@@MAP_INDEX@@`.
- Start menu: city/Battlemaster/LCT mat URL and name markers plus the randomizer booleans.
- Battlemaster spawner: `@@MAP_CARD_MACHINERY@@`.

GUIDs are APIs in this project. Lua injection, cross-object calls, saved state, container lookup, and map restoration all depend on them. If an object GUID changes in the source save, update every source reference and validate/compile. A filename alone does not attach a script to an object; its `FTC-GUID` header does.

## Runtime lifecycle and the Global readiness barrier

TTS does not guarantee that Global's `onLoad` finishes before object scripts load. A joining player can widen the race. Commit `e03f480` introduced the shared barrier:

- `FTC_Global_Ready` starts false during Global registration.
- Global restores variables/references and sets it true at the end of `onLoad`.
- Scripts that need Global GUIDs/tables use `Wait.condition` in `whenGlobalReady(...)`, with a 10-second fallback so a broken load cannot hang forever.
- Current adopters include `startMenu`, both dice systems, the score sheet, table control, and terrain extraction.

Do not move Global-dependent reads back to top-level script execution. In particular, `MISSION_PACK_PARIAH_NEXUS`, mat/roller GUIDs, counters, and mission pack tables can be nil before the barrier opens.

The normal setup flow is approximately:

```text
choose mode/size
  -> place/hide the correct setup objects
  -> choose Red/Blue dispositions
  -> Generate Mission (primary cards + three compatible map choices + layout art)
  -> optionally lock a map choice / set missions
  -> press a map card's Load Map
       -> capture undo state
       -> park layout art and primaries out of the wipe
       -> canonical card performs deferred wipe, waits for clear, spawns terrain
       -> startMenu auto-selects/draws deployment and later destroys the loader card
  -> choose/lock secondaries
  -> Start Game
       -> return setup cards, lock secondaries, push scoring context,
          hide deployment, show objectives, start turns/HUD
```

Combat Patrol and per-size singles modes deliberately set `matrixPropsDisabled`: mission generation still resolves primaries, but skips normal matchup map/layout cards. Combat Patrol separately deals its own three cards from its map bag.

## Dice roller: architecture and intricate behavior

### Object split

There are two copies of each side's objects:

- Dice mats/trays: `acae21`, `839fcc` running `customDiceTable.ttslua`.
- Hidden roller containers: `17ca2b`, `927ca1` running `customKustom40kDiceRollerMk3.ttslua`.

The tray owns user intent and world-space discovery. The roller owns randomness and the asynchronous container transaction. Keep this separation: pushing all behavior into either object recreates old race/physics failures.

### Normal Roll All path

```text
tray RollAllDice
  -> 0.2 s accepted-press cooldown + 0.1 s coalescing delay
  -> getDice() scans settled, unheld dice inside this tray and outside its lethal zone
  -> roller.beginRollBatch({color, expected count}) acquires the one-roll lock
  -> tray annotates each die with {holder color, rollId}, then putObject(die)
  -> roller onObjectEnterContainer admits only dice belonging to the active batch
  -> collection drain timer waits 0.1 s when complete, 0.2 s otherwise
  -> takeDiceOut precomputes one PRNG face per admitted die
  -> dice leave the bag in result rows or ordered/grouped layout
  -> per-die setValueCallback fixes face/rotation and decrements pending callbacks
  -> last callback releases the roll lock; a 15 s watchdog is the final backstop
```

Important defenses:

- Only one `activeRollBatch` exists per roller. A busy roller rejects a second scripted batch before the tray moves any dice.
- Unexpected/manual/late dice are either attached to the valid collecting batch or ejected, never silently reinterpreted after processing starts.
- `rollId` prevents dice arriving after a drained/timed-out roll from becoming a new manual roll.
- Collection is based on container-entry events, not collision events.
- The roller computes all values before extraction. Invalid face detection falls back to d6 so one exotic die cannot throw and strand the entire batch.
- Lock release waits for all `setValueCallback`s, not merely `takeObject` scheduling.
- Long runs of a value wrap after 25 dice, preventing dice from being laid beyond tray bounds and disappearing from future scans.

### PRNG

The roller uses vendored xoshiro128++ rather than Lua 5.2's host `rand()`. The first adoption was `ca8ad06`; the crucial hardening was `76b129b` after TTS `bit32` was observed returning corrupt XOR/shift/rotate values until reload, producing pathological same-face rolls.

Current implementation details:

- All 32-bit XOR, shifts, rotates, and multiplication are implemented arithmetically using exact ranges within Lua's double-number runtime; `bit32` is not trusted.
- Four seed words mix time, clock, roller GUID, side-specific material, and a reseed counter.
- RNG state is intentionally **not saved**. Each TTS load reseeds so a published save cannot replay a frozen sequence.
- Health checks reject low-complexity/all-zero state and probe eight outputs for repeats; recovery retries seeds and has a deterministic last-resort state.
- Bounded output uses rejection sampling, avoiding modulo bias.
- Debug builds can print seed/probe/distribution/timing data, verify the known `{1,2,3,4}` xoshiro vector, and check for physical face drift after dice settle.

The comments near the file header still mention saved/restored state; the current `onSave()` returns an empty string, and the later lifecycle comments are authoritative.

### Quick roll and spawning

- Left-click `+Nd6` spawns dice without rolling.
- Right-click on the small `1d6` through `5d6` buttons quick-rolls. `+10`/`+25` remain spawn-only.
- `+1d3` comes from a dedicated bag and supports right-click quick roll.
- Quick roll calls `roller.rollFacesForQuick`, sharing the same xoshiro stream but never entering the roller container. It assigns one non-red/non-blue palette tint per batch.
- Applying a custom die image triggers an asynchronous object reload. Face/rotation assignment is deferred two frames; commit `00c3822` fixed the prior race where custom dice reset to their default face.
- If the roller cannot be resolved, quick roll currently falls back to `math.random` for values. Normal bag rolls do not.
- Spawning is capped at 128 on-tray dice and throttled per configured player speed.

### Tray result tools and coupling

The tray also owns:

- Per-face reroll/delete controls, with alternate-click lower/upper ranges.
- Ordered rolls and grouping in twos/threes.
- Five-roll chat history held by the roller.
- An in-memory roll snapshot stack for `revertRoll`; it recreates current d6/custom dice but is separate from the roller's chat history.
- Lethal and sustained-hit helpers. Lethal dice are parked in a separate zone and excluded from normal scans; clearing uses the same bounds function so dice cannot become excluded-but-unclearable.
- Custom dice/color selection and Dice+ palette.
- Periodic `checkDice()` result counts. This still performs `getAllObjects()` every 0.2 s per mat; debug includes a benchmark against an area `Physics.cast` because this is a known performance hot path.
- Coherency, engagement range, measurement bubbles, model spacing, and persistent highlight paint.

Coherency performs one O(n²) full calculation on a capped selection, then becomes event-driven: pickup/drop starts a short 0.1 s motion loop that recomputes only moved rows and stops when everything rests. Engagement intentionally rescans during its 15-second live window. Both borrow highlight ownership through `SelectionHighlighter.holdHighlight/releaseHighlight` so the generic selection glow does not capture or restore the wrong color. Highlight paint updates the highlighter's restoration snapshot so paint survives deselection.

## Map inventory, generation, and loading

### Manifest/index contracts

`data/map_manifest.csv` is authoritative for normal map cards. At this snapshot it contains:

- 45 each: T5S2, Cra5hNatural, Battlemaster BTTF Ruins, Battlemaster Desert, and BTTF.
- 15 each: Zim and LCT Pack 1.
- 255 eligible maps total, all currently tagged `map_type_comp`.
- 15 source bags, corresponding to the 15 unordered/symmetric disposition matchups.

At compile time the manifest becomes Global `MAP_INDEX`, keyed by card GUID with creator ID, creator display name, map type, and eligibility. This lets generation/filter code identify cards while they are still inside bags.

Creator filters live in `mapFilter.ttslua`, persist their own state, and mirror it into Global `activeMapCreators`. Generation filters out `eligible=false` cards and prefers active creators. If no active creator can fill a logical layout slot, it falls back to any eligible creator rather than leave the slot empty. The default active creators at this snapshot are Battlemaster - BTTF Ruins and Battlemaster - Grimdark (`battlemaster_bttf`).

Creator tag/display mappings must agree between Python validation and Lua display logic. Logical map matching strips the trailing creator credit from nicknames; changing the name format can break deployment-zone and layout-art resolution.

### Mission generation resiliency

The core is `startMenu.runMissionGeneration(deploymentMode)`:

- It rejects calls outside setup and holds both a short generate cooldown and a `missionDealInProgress` guard.
- The 5×5 `missionMatchups` table in Global resolves Red/Blue primary mission names.
- Existing primary cards already in slots are included in resolution; unwanted cards return to their decks, while wanted cards remain and are repositioned. This avoids the historic press-twice toggle/race.
- A disposition matchup selects a source map bag. Cards are grouped by logical slot, then one creator variant is chosen for each slot. This weights layouts equally rather than overweighting creators with more cards.
- Paired layout-art cards are resolved from deck `fb4b5d`.
- Old deployment/layout cards are returned to their actual source containers. Source is remembered by both GUID and normalized name because TTS may recombine a returned deck under a new deck GUID.
- `findDeploymentCard` scans loose objects and all Deck/Bag contents by card GUID, surviving TTS deck recombination.
- Cards are dealt one per frame so repeated `takeObject` calls on one container do not collide. Every step and completion path is guarded so the cooldown cannot remain stuck after an error.
- `random` mode uses a sparse `{[2] = choice}` to put one choice in the middle slot; code that reads it must use `pairs`, not `ipairs`.

The former dynamic Battlemaster branch remains as dormant scaffolding (`runBattlemasterMissionGeneration` and callback), but normal generation currently uses the static map matrix only.

### Canonical card loading

Every normal card is `canonical machinery head + extracted terrain payload + compiler-injected hook`.

The canonical v2 card loader in `data/map_card_machinery.lua`:

1. Spawns a board-sized scripting trigger.
2. Waits two frames for zone population.
3. Repeatedly destroys everything in the zone except the explicit keep GUIDs and objects with `GMNotes == "MapExclude"`.
4. Requires two consecutive clear frames before spawning terrain, with a 180-frame safety deadline.
5. Spawns each serialized terrain object JSON and locks it after a short delay.

The clear path uses the same deferred wipe without terrain spawning. This is designed around TTS's asynchronous zone population/destruction; replacing it with a synchronous `zone.getObjects()`/spawn sequence will reintroduce partially cleared boards.

The compiler injects a hook at the start of `loadMap` that calls `startMenu.onMapCardLoaded` **before** the card begins wiping. That handler:

- Captures the Back-to-Selection restore point.
- Remembers the loaded map GUID/name for debug tag export.
- Moves paired static layout art to the mission board, or destroys sibling transient Battlemaster choices.
- Applies creator-specific mat randomization where enabled.
- Moves primary missions out of the wipe area.
- Rewrites menus so map-selection controls disappear but Clear/Back remain.
- Schedules the loader card's destruction after 1.0 seconds. Earlier destruction would cancel its pending 0.5-second terrain spawn.
- Parses the deployment-zone suffix from the logical map name and draws it after 0.7 seconds, safely beyond both wipe and terrain spawn.

The auto-destroy timer ID is retained because a very fast Back-to-Selection must cancel it before respawning the original card GUID.

### Extracted terrain payloads

Terrain blobs total about 29 MB and are excluded from the roughly 4 MB source JSON. `scripts/extract_map_payloads.py` preserves raw line endings and strips payloads without reserializing the whole save; the compiler reconstructs `head + payload` byte-for-byte before hook injection. A stripped required card without a matching payload file is a hard build error.

Normal map cards are in the manifest. Combat Patrol bag `fdf6e7` is explicitly treated as an extra map pool, accounting for the three additional payloads.

## Back to Selection: transaction-style undo

This feature began as a simple “go back” UI in `c6d9f9d`, was expanded in `434cc4d` to restore generated mission objects too, and has since become a full snapshot/wipe/restore transaction.

The restore point is captured at the instant `onMapCardLoaded` runs, before any card movement or wipe:

- Menu/game-mode state: mode, in-game flag, singles/Combat Patrol/matrix flags, size/deployment selection, mission pack, dispositions, and mat texture.
- JSON for persistent selection-screen objects: startup cards, mode objects, force-disposition token, and Combat Patrol bag when applicable.
- Every loose map/layout/Combat Patrol card wherever the user moved it.
- Primary cards currently in their mission slots.
- A separate GUID set marking loose mission cards that must be purged and recreated rather than merely respawned if absent.

Undo proceeds as follows:

```text
disable buttons and cancel the pending loaded-card destruction timer
  -> remove objectives and deployment overlays
  -> purge every snapshotted mission card, loose or inside any Deck/Bag
  -> spawn a board-sized wipe trigger
  -> two frames later destroy map terrain except keep GUIDs / MapExclude
  -> wait 0.4 s for destruction to settle
  -> spawn missing objects from captured JSON (reusing their now-free GUIDs)
  -> wait 0.5 s for registration
  -> restore menu variables and normalize object placement
  -> restore mission pack/mode objects/mat texture
  -> clear the in-memory restore point and redraw menus
```

Why the complexity matters:

- After map load, related cards are scattered across the mat, off-board target slots, and source containers. Testing only for a live GUID would preserve stale position/scale and can duplicate deck-held cards.
- TTS can turn the last card of a deck into a loose Card and can assign a new GUID to a recombined Deck. Lookups therefore search loose objects and container contents by child GUID.
- Spawned JSON reuses original GUIDs only after the previous objects are destroyed and TTS has registered that destruction.
- Freshly spawned setup objects must not overlap the still-active wipe trigger.
- The restore point is intentionally in-memory only and omitted from `onSave`; saving/reloading after a map load loses the undo.
- Pressing Back during the loader card's 1-second auto-destroy window must stop that timer or it will destroy the newly restored card with the same GUID.

The debug-only `Back to Selection (SAVE TAGS)` first records every live `obj_*` terrain object's tags/name/position into persisted `debugMapTagData`, keyed by loaded card GUID, then calls the same normal undo. That allows editing many maps in one TTS session and transferring tag changes back with tooling from the exported save.

## Debug system

Debug behavior is a compile-time build flavor, not a separate source branch:

- Source Global retains `DEBUG = true -- @@LCT_DEBUG@@` so raw/dev use remains convenient.
- `compile.py --test` stamps true; release/plain builds stamp false.
- `ftc_base_ui.xml` always carries `DebugTools` but marks it inactive.
- Global reveals the panel only when `DEBUG == true` and every sensitive handler rechecks the flag.
- The Battlemaster dev object keeps buttons in debug builds and hides itself below the table in release builds.

The shared draggable debug panel currently provides:

- Red/Blue dice scan benchmarks (`getAllObjects` versus box `Physics.cast`).
- Red roller known-vector RNG test.
- Selected-GUID dump to a spawned tile, first removing stale dump tiles.
- Battlemaster cache populate/check, per-theme population, and the `695f1f0` sequential `All 3` population workflow.
- Custom table-mat URL input forwarded to the start menu's mat logic.

Other debug paths:

- Dice rolls print seed/probe/distribution/timing and physical drift diagnostics only in debug builds.
- Objective placement can print tag/raycast diagnostics based on the Global debug flag.
- `BM_MAT_DEBUG` is independently true in `startMenu` at this snapshot; check its use before assuming all mat logging is compile-gated.
- The SAVE TAGS undo path persists `debugMapTagData` in the start menu's Lua state specifically so an exported TTS save can carry edits back to Python.

Do not expose debug HTTP sync buttons or bulky diagnostics in release UI. Do not make `DEBUG` a saved runtime preference; reproducible test/release compilation is the intended boundary.

## Battlemaster: current truth versus historical scaffolding

The historical sequence matters because the code contains both approaches:

1. `3f24f87` introduced a bare dev spawner.
2. `f494de3`/`3aff5bb` developed API sync and cache-driven generation.
3. `3039dba` deliberately pivoted from runtime cache dependence to static map migration.
4. Merge `7651fb8` brought in the static-card system and larger supporting UI/tool work.

Shipped Battlemaster maps are now ordinary canonical cards in three creator sets, 45 maps each:

- `map_crt_battlemaster_bttf_ruins` / Battlemaster - BTTF Ruins
- `map_crt_battlemaster_armageddon_desert` / Battlemaster - Desert
- `map_crt_battlemaster_bttf` / BTTF (UI override: Battlemaster - Grimdark)

There must not be a fourth generic `map_crt_battlemaster` shipped set.

The spawner remains valuable development infrastructure. It smart-syncs API manifests/themes/layout catalogs, prunes stale cache entries, reconstructs board-space mats/terrain/objective tags from templates and theme mappings, builds canonical loader scripts, and can return complete transient card JSON through an exactly-once callback. Network buttons are debug-only; cached static cards are the release path.

The live spawner cache holds only one theme because each sync prunes payloads outside the incoming catalog. Commit `695f1f0` adds archives that deep-copy completed per-theme catalog/script data through a JSON round-trip, preventing later in-place pruning from mutating earlier snapshots.

Static import is intentionally idempotent per creator: it removes the previous imported creator set, generates stable card/deck identifiers, preserves logical matchup/slot naming and layout-art compatibility, appends creator credit/tags, strips the transient provider hook, and leaves the compiler to inject the normal static map hook. After import, clear the shipped dynamic cache, validate strictly, test, and compile.

## History: why the architecture looks this way

The complete history is unusually dense (340 commits in roughly three months), but these are the durable arcs:

- **Apr 6-20 — FTC fork and table cleanup:** compiler rewrite, clock/VP/CP widgets, removal of legacy boards/tokens, deployment picker, early instant-spawn/roll behavior, and base UI cleanup.
- **Apr 21-30 — overlay, xoshiro, and mission prototypes:** scoring overlay/phase integration, xoshiro128++ replaces host `rand`, automatic roller experiments, secondary managers/scoreboard, and first mission/disposition generator.
- **May — 11th-edition gameplay system:** split per-player overlays, mission matrix, secondaries, deployment zones, map art, CP tracking, and elimination of 10th-edition/2v2 paths.
- **Jun 1-7 — resiliency/dev tooling:** mission generation hardened, objective markers become dynamic, auto deployment on map load, quick-roll iterations, legacy roll behavior partially restored after instability, v2 map loaders, compiler and injection tooling.
- **Jun 9-10 — dice incident and hardening:** `76b129b` diagnoses corrupt TTS `bit32`; arithmetic xoshiro, RNG analysis/stress tests, batch locking, timing thresholds, and final debug adjustments follow. The old analysis/stress files were later removed in cleanup, but their conclusions live in current code.
- **Jun 11-16 — performance, validation, map undo/filter:** polling/hot-path pass, coherency improvements, structural map validator, the first Back-to-Selection transaction, layout-art support, canonical migration rules, creator-aware map filtering, and fixes to keep primaries alive through map loads.
- **Jun 18-25 — Battlemaster and static maps:** dynamic spawner prototype, debugging, deliberate pivot to static imported cards, Combat Patrol/narrative support, advanced UI, and merge of the static-card branch.
- **Jun 27-30 — cleanup and map-load rework:** game modes/UI consolidated; branch commits separate terrain payloads, clean tags/UI, expand dice, add Set Mission, and merge as `146f32d`. This establishes the current extracted-payload build architecture.
- **Jul 3-21 — LCT maps, dice/tool polish, load races, Battlemaster refresh tooling:** first 15 LCT maps, clock/overlay fixes, removal of Select All dice, highlight paint, the Global readiness barrier and joining-player secondary refresh fix in `e03f480`, then the local multi-theme cache/archive/import workflow in `695f1f0`.

History pitfalls:

- Commit messages sometimes describe experiments later reverted. Current code and changelog win.
- Removed files such as old dice stress scripts, migration scripts, and performance audit documents still appear in history; do not assume their absence means the issue was never addressed.
- Large merge commits include enormous JSON churn. Inspect focused parent/branch diffs and source scripts rather than inferring behavior from line counts.
- Version headings/messages have occasional typos (`v16.2c`, `dispotition`, etc.). Preserve runtime identifiers where code depends on them, but new documentation/UI can use corrected spelling.

## Validation and safe change recipes

### Before any meaningful change

```bash
git status --short --branch
python3 scripts/validate_maps.py --require-map-tags
python3 -m unittest scripts.test_validate_maps
```

Read the active diff first. `ftc_base.json` and Lua files are often edited together through a TTS export/import workflow; unrelated modifications belong to the current developer.

### After Lua/XML-only changes

```bash
python3 -m py_compile scripts/*.py
python3 scripts/validate_maps.py --require-map-tags
python3 -m unittest scripts.test_validate_maps
python3 scripts/compile.py --test
```

Load the test build in TTS for behaviors Python cannot emulate: object load ordering, physics, scripting-trigger population, `Wait` timing, deck collapse/recombination, object reload after `setCustomObject`, and join-in-progress UI.

### After map/card changes

Follow `README.md` exactly. In particular:

1. Normalize foreign cards with `normalize_map_card.py`; do not hand-copy their loader.
2. Update source JSON and `data/map_manifest.csv` together.
3. Ensure every source bag appears in `deploymentMatrixDecks`, `randomDeploymentDecks`, and `GAME_MODE_OBJECTS`.
4. Ensure all 25 matchups remain dedicated and every logical map name resolves layout art.
5. Extract payloads after a TTS re-export/import.
6. Run strict validation, payload audit, behavioral tests, and a test compile.

Useful audits:

```bash
python3 scripts/audit_map_payloads.py --sizes
python3 scripts/audit_map_payloads.py --strict
python3 scripts/extract_map_payloads.py --dry-run
```

### After dice changes

Test Red and Blue independently and together:

- normal Roll All, repeated/double presses, overlapping side rolls, and manual dice entering the bag;
- per-face reroll, lower/upper alternate click, ordered/grouped layouts, and 25+ same-face placement wrapping;
- quick roll for standard/custom d6 and d3;
- invalid/custom face metadata fallback;
- lethal/sustained workflows, moving lethal dice back, and Clear Mat;
- the debug known-vector RNG test, seed/probe output, lock timing, safety timeout, and drift check;
- load/join before Global references are ready.

Do not “simplify” away batch IDs, pending callback accounting, rejection sampling, arithmetic bit operations, the custom-die defer, or the busy-die ejection path without reproducing the old failure cases.

### After map load / Back-to-Selection changes

Test at least:

- immediate Back press during the loader-card destruction window;
- Back after terrain/deployment/objectives have fully settled;
- generated primaries, three map cards, three layout cards, locked-in card, and manually moved cards;
- a Deck collapsing to its last Card and cards returning into Bags;
- repeated Generate → Load → Back cycles;
- Combat Patrol bag plus all three loose Combat Patrol cards;
- static Battlemaster cards and, in a debug build, transient provider cards;
- save/reload expectations (undo is intentionally not persistent).

## High-risk coupling checklist

- `startMenu.ttslua` is nearly 5,800 lines and owns several subsystems. Search all references before renaming state/functions.
- Keep canonical wipe survivor GUIDs aligned among map machinery, standalone Clear Table, validator constants, and actual JSON objects.
- Keep source bag lists aligned across the manifest, generation tables, random fallback tables, and game-mode placement tables.
- Keep creator tags/displays aligned across manifest, validator, start menu suffix map, and filter overrides.
- Keep layout naming conventions and creator-credit stripping stable.
- Keep map-load timing ordered: pre-wipe hook → deferred wipe → 0.5 s terrain → 0.7 s deployment → 1.0 s loader destruction.
- Keep Back restore timing ordered: purge → wipe → settle → respawn → register → re-place.
- Keep the Global readiness barrier for any load-time GUID/table lookup.
- Keep debug UI hidden by XML default and revealed only by compiled DEBUG state.
- Keep SelectionHighlighter ownership calls balanced; leaked holds leave highlights under another subsystem's control.
- Avoid relying on a Deck's GUID after `putObject`; scan child GUIDs when identity matters.
- `onload` versus `onLoad` is accepted by TTS in existing inherited scripts; do not mass-normalize event names without in-game verification.
- Lua source uses some MoonSharp/TTS extensions such as `!=`; a generic Lua parser may report false errors.

## Starting point for the next conversation

Before acting, a future assistant/developer should:

1. Read `git status` and the current diff; do not assume the repository snapshot above is still current.
2. Read the relevant source file plus its recent `git log --follow` history.
3. Treat `README.md`, current source, validator, and tests as more authoritative than old commit messages.
4. State whether a proposed change affects source-only behavior, compilation, TTS asynchronous runtime behavior, map inventory, or saved-state compatibility.
5. Preserve GUIDs, compiler markers, canonical map machinery, and user changes.
6. Run proportionate validation and clearly call out anything requiring an in-TTS test.

The central design lesson is that most “extra” complexity here is compensating for TTS realities: nondeterministic script load order, asynchronous container/zone/object operations, physics settling, deck identity changes, and generated object GUID lifecycles. Refactors should reduce duplication while keeping those explicit safety boundaries intact.
