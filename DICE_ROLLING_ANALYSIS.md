# LCT Dice Rolling Analysis

## Scope and project context

LCT is a ready-to-play Warhammer 40,000 table for Tabletop Simulator (TTS). It is
a fork of Hutber's Competitive FTC Base and retains the same broad architecture:

- TTS objects and their transforms are stored in `TTSJSON/ftc_base.json`.
- Object behavior is authored as Lua in `TTSLUA/*.ttslua`.
- The compiler injects those scripts into a publishable TTS save.

The dice system is split between two objects per player:

1. A locked **dice mat/table** (`customDiceTable.ttslua`) owns the player-facing
   controls, identifies dice within the playable mat area, spawns dice, and sends
   dice to the roller.
2. A locked **roller/tray** (`customKustom40kDiceRollerMk3.ttslua`) is a
   `Custom_Model_Bag`. It receives dice, chooses their results, extracts them,
   and arranges them on the mat.

The active custom mats and rollers are connected by GUIDs in `global.ttslua`:

| Side | Mat GUID | Roller GUID |
|---|---:|---:|
| Red | `acae21` | `17ca2b` |
| Blue | `839fcc` | `927ca1` |

Both LCT and legacy also retain an older pair of roller GUIDs, but the custom
dice mats use the custom roller pair above.

## The most important finding

The tray does **not** physically roll dice to determine their results.

The tray is a scripted container. Once dice enter it, Lua generates a result for
each die. The tray then extracts each die at a calculated mat position, calls
`setValue(result)`, and rotates the die to the corresponding face-up rotation.
Physics only handles the final placement/settling. It is not the source of
randomness.

This is true in both LCT and the legacy project. Their main differences are the
random-number generator, reliability safeguards, batching behavior, and
additional ways to bypass the tray.

## Physical layout and ownership

The physical layout is essentially inherited unchanged from legacy:

| Object | Red position / rotation | Blue position / rotation |
|---|---|---|
| Custom dice mat | `(0, 0.87, 29)`, Y rotation `0` | `(0, 0.87, -29)`, Y rotation `180` |
| Custom roller/tray | `(21.43, 0.96, 25.85)`, Y rotation approximately `0` | `(-21.43, 0.96, -25.85)`, Y rotation approximately `180` |

The mats are locked `Custom_Tile` objects scaled to `3.75`. The trays are locked
`Custom_Model_Bag` objects scaled to `0.55`. Red and Blue are mirrored by 180
degrees, and the placement formulas account for that rotation.

The mat determines which dice it owns by scanning all TTS objects and checking
whether each die's world position is inside a deliberately cropped subsection
of the mat bounds. Dice in the separate lethal-hits area are excluded. In LCT,
held dice are also excluded, and callers can explicitly choose whether moving
dice are eligible.

## Normal LCT roll flow

### 1. Dice are spawned or found on the mat

The `+Nd6` buttons spawn dice in a compact 5-by-5 local grid:

```text
local position = mat.positionToWorld({
    4 - grid * 1.5 - col * 0.25,
    0.5,
    -0.3 + row * 0.25
})
```

Each completed 5-by-5 block moves 1.5 local units along X. The mat caps the pool
at 128 dice. LCT additionally supports spawning a D3 from a dedicated bag.

Left-clicking a spawn button only adds dice to the mat. It does not roll them.

### 2. The mat sends dice to the tray

`Roll All`, ordered rolls, and row rerolls eventually call `moveDiceToRoller`.
For every die, the mat:

- records the rolling player on the roller;
- removes stale lethal-hit tracking in LCT;
- calls `roller.putObject(die)`.

LCT debounces rapid `Roll All` presses for 0.1 seconds and only collects resting
dice when the delayed action fires. This prevents a second click from grabbing
dice that are still returning from the first roll and sending them through the
tray again.

### 3. The tray batches arrivals

When a die enters the tray, LCT immediately detects and records its number of
faces from the live die object. The tray then resets a 0.1-second timer. The
timer fires only after dice stop arriving, so a large pool is drained as one
batch.

This is a major reliability improvement over legacy. Legacy starts a separate
`takeDiceOut` timer for every entering die and rescans every object in the scene
on each entry to discover face counts.

### 4. LCT generates the results

For every die currently inside the tray, LCT calls `rollFace(faces)`.

LCT uses an explicit 32-bit **xoshiro128++** pseudorandom number generator. It is
seeded from time, clock, roller GUID, and player-side material. Bounded results
use rejection sampling rather than a simple modulo-only mapping, avoiding modulo
bias for bounds that do not evenly divide the 32-bit output range.

Unknown or invalid face counts safely default to D6. A die named `BCB-D3` is
explicitly treated as having three faces.

The RNG is freshly seeded when the roller loads and its state is not persisted
by `onSave`. Therefore, rolls are reproducible within a loaded session only if
the state is externally captured; saving and reloading starts a new stream.

### 5. The tray calculates display positions

By default, results are sorted into one row per face. With the default
`Step = 1.05`, the local result-row placement is:

```text
X = -20.4 + column * Step
Z = -3.17 + faceRow * Step
```

Values above six receive an additional X offset and wrap back through the six
available Z rows.

LCT wraps more than 25 dice of the same result into another six-row band plus a
one-row gap. Legacy does not wrap same-value rows, so a sufficiently long run
continues along X and can leave the detectable mat area.

Ordered rolls turn off value sorting. Dice are instead placed in input order in
rows of up to 25. Ordered groups of two or three insert a blank position between
groups so sequential attack groups are visually separable.

The local X/Z coordinates are transformed into world coordinates using the
target mat's Y rotation. Dice are extracted two units above the mat:

```text
world Y = mat Y + 2
```

This shared transform is why the same placement code works for both the
unrotated Red mat and the 180-degree Blue mat.

### 6. The tray fixes the displayed face

The roller extracts each die with `takeObject`, then its callback:

- calls `die.setValue(scriptedResult)`;
- looks up the rotation corresponding to that value;
- rotates it by that face rotation plus the mat-facing rotation.

LCT's current working-tree version also waits for every die to rest and reports
whether its physically landed value drifted from the scripted value.

### 7. Results and undo state are recorded

Normal tray rolls tally the result counts, update the roller's last-five-roll
history, optionally print results, and ask the mat to snapshot the final dice
positions, rotations, values, tints, and custom images for roll reversion.

## LCT quick-roll path

Right-clicking the `+1d6` through `+5d6` buttons uses a separate instant path:

1. The mat spawns the requested dice in the normal spawn grid.
2. The mat asks its roller for values via `rollFacesForQuick`.
3. The roller draws those values from the same xoshiro RNG stream.
4. The mat directly calls `setValue` and applies one shared, visually distinct
   tint to the batch.

These dice never enter the tray and are not rearranged into result rows. The
path is intentionally limited to one through five D6s; `+10d6`, `+25d6`, and
D3 remain spawn-only.

Quick rolls print their total, but they do not go through the normal roller
result tally, last-five-roll history, or post-roll snapshot pipeline. This is an
important behavioral distinction despite sharing the same RNG stream.

## LCT versus legacy

| Area | Legacy Hutber approach | LCT approach |
|---|---|---|
| Physical props | Mirrored locked mats and bag-like trays | Same inherited geometry and object types |
| Source of result | Lua `math.random(faces)` | Explicit xoshiro128++ `rollFace(faces)` |
| Seed/state | `math.randomseed(os.time() + side offset)` at script initialization | Mixed time/clock/GUID/side seed on load; no persisted state |
| Bias control | Depends on Lua/C `math.random` implementation | Rejection-sampled bounded values |
| Face detection | Rescans all scene objects per entering die; unsafe custom-die lookup | Detects the entering die directly in O(1); guarded lookup; invalid values default to D6 |
| Batch draining | Starts a `takeDiceOut` timer for every arrival | Coalesces arrivals and drains once after the final arrival |
| Rapid Roll All | Immediately sends currently detected resting dice | Debounces clicks and collects resting dice at fire time |
| Same-value row overflow | Continues indefinitely along X | Wraps after 25 dice into a new Z band |
| Die selection | Resting dice inside cropped mat bounds | Shared bounds logic, explicit moving-dice option, excludes held dice, tighter lethal-zone consistency |
| D3 support | Roller recognizes named D3, but mat has no dedicated D3 spawn button | Dedicated D3 spawn path plus roller recognition |
| Instant rolls | Separate 1D6/2D6 buttons; direct `math.random`; independent world-position line | Right-click 1–5 D6 buttons; values come from the roller's xoshiro stream; use normal spawn grid |
| External reporting | Can submit resolved rolls to Hutber's stats API when a tracked game is active | External dice-roll submission removed from the current roller/table path |
| Roll analytics | Includes inferred hit/wound phases, roll stats, and chance displays | Simplified around play controls and last-five-roll display |
| Diagnostics | No post-placement verification | Current working tree prints RNG probes and checks final face drift |

## Architectural interpretation

Legacy treats the dice system as a feature-rich extension of the original
Kustom 40k Dice Roller. It layers analytics, phase inference, external stats
reporting, undo/redo, instant buttons, and additional controls onto the inherited
container-driven mechanism. The result is capable, but several paths use
different randomness and reporting behavior, and the container path performs
expensive global scans with fragile assumptions about custom dice.

LCT keeps the inherited physical interaction model but moves toward a more
self-contained, deterministic-in-implementation, failure-resistant dice
service. Its strongest changes are not visual: they reduce global scanning,
coalesce asynchronous events, guard malformed dice, unify normal and quick-roll
randomness, keep large result pools on the mat, and prevent rapid input from
causing repeated tray cycles.

In short:

> Legacy is a scripted tray with many attached features. LCT increasingly treats
> the tray as a robust result-generation and layout engine, while allowing small
> rolls to bypass its physical-container workflow safely.

## Observations and risks

1. **Current debug instrumentation is user-visible.** The working-tree version
   of `customKustom40kDiceRollerMk3.ttslua` prints the complete RNG state, five
   probe outputs, result distribution, face samples, GUID samples, and drift
   checks for every normal tray roll. This is useful for investigation but noisy
   and exposes enough state to reproduce subsequent rolls during the session.

2. **Quick rolls are not equivalent to normal rolls beyond randomness.** They
   share xoshiro-generated values, but skip sorted placement, normal result
   history, the one-second undo snapshot, and normal optional result messages.

3. **Normal roll order is not a stable insertion order.** The tray enumerates
   `self.getObjects()` and uses Lua tables keyed by GUID. Ordered mode suppresses
   value sorting, but its exact sequence ultimately depends on TTS/container and
   Lua table enumeration behavior rather than an explicit arrival-order list.

4. **RNG state comments are slightly inconsistent with behavior.** The file
   header mentions saved/restored RNG state, while `onSave` deliberately returns
   an empty string and `onLoad` reseeds. The implementation is clear; the header
   should be read as outdated wording.

5. **Legacy instant rolls and LCT quick rolls are separate result pipelines.**
   Any future auditing, statistics, or replay feature must explicitly ingest
   both tray rolls and bypass rolls if it intends to represent every result.

## Primary source locations

- `README.md` and `TUTORIAL_GUIDE.md`: project purpose and user-facing dice features.
- `TTSLUA/global.ttslua`: active mat and roller GUID wiring.
- `TTSJSON/ftc_base.json`: physical object types, transforms, scales, and assets.
- `TTSLUA/customDiceTable.ttslua`: active LCT mat controls, bounds, spawning,
  quick rolls, rerolls, and roll snapshots.
- `TTSLUA/customKustom40kDiceRollerMk3.ttslua`: active LCT tray, RNG, batching,
  result layout, extraction, face setting, and diagnostics.
- `LEGACY/hutber-tts-main/TTSLUA/customDiceTable.ttslua`: legacy mat behavior.
- `LEGACY/hutber-tts-main/TTSLUA/customKustom40kDiceRollerMk3.ttslua`: legacy
  custom tray behavior.
- `LEGACY/hutber-tts-main/TTSJSON/ftc_base.json`: legacy physical object layout.
