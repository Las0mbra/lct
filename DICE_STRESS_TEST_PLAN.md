# Dice Roller Manual Stress-Test Plan

## How to record each test

Compile the TTS save with `python3 Compiler/compile.py --test` before running
tests that rely on the debug messages below. Release and ordinary builds keep
RNG recovery active but intentionally disable all diagnostic output and checks.

For every test, record:

- fresh game, saved game, or reloaded game;
- Red or Blue side;
- number and type of dice;
- whether the normal tray, ordered roll, row reroll, or quick-roll path was used;
- `[DBG-SEED]`, `[DBG-RNG]`, `[DBG] dice=...`, `[DBG] dist=...`, and any
  `[RNG RECOVERY]` or `[DRIFT]` messages;
- whether every die returned to the correct mat and remained selectable/clearable.

For a healthy normal roll:

- the four seed words should normally contain several non-zero values;
- the five raw probe values should not repeat;
- `dice=N` should match the number sent into that tray batch;
- the sum of all counts in `dist` should equal `dice=N`;
- large rolls should contain several different faces;
- `[DRIFT CHECK]` should report `0 / N dice drifted`.

An occasional unusually good or bad distribution is normal. A repeated raw
probe, an all-identical large batch, or a result pattern that repeats exactly
across subsequent rolls is not.

## Priority 0: original regression

Run this sequence at least 20 times from completely new games.

1. Start a new game.
2. Sit Red before touching Blue's dice tools.
3. Spawn exactly 76 D6.
4. Press **Roll All Dice** once.
5. Roll the same 76 dice another five times.
6. Clear them, spawn another 76, and roll again.

Expected:

- The first roll is not `4:76` or any other all-identical result.
- Every subsequent roll changes.
- Each batch reports `dice=76` and the `dist` counts total 76.
- No `[RNG RECOVERY]` should normally be needed, but if it appears, the roll
  immediately after it must still be varied and valid.

Repeat the same procedure on Blue as a control.

## Priority 1: fresh-game initialization matrix

Each row should be tested from a separate new game:

| Test | First action after loading |
|---|---|
| Red-first | Roll 76 dice on Red |
| Blue-first | Roll 76 dice on Blue |
| Red quick-first | Right-click `+5d6`, then normal-roll 76 |
| Blue quick-first | Right-click `+5d6`, then normal-roll 76 |
| Simultaneous | Prepare 76 on both sides and press both Roll All buttons quickly |
| Delayed-first | Wait 5 minutes after loading, then Red rolls 76 |
| Menu-first | Complete normal game setup, then Red's first roll is 76 |

Expected: side order and time since load do not affect RNG health.

## Priority 2: pool-size boundaries

Normal-roll each size ten times on both Red and Blue:

```text
1, 2, 3, 5, 6, 25, 26, 49, 50, 75, 76, 100, 127, 128
```

Pay special attention to:

- `25 -> 26`: result-row wrapping boundary;
- `75 -> 76`: original failure size;
- `127 -> 128`: maximum supported pool;
- attempting to spawn beyond 128.

Expected:

- `dice=N` and the `dist` total always equal the requested pool.
- More than 25 identical result dice wrap to another band and remain on the mat.
- No dice become permanently unselectable, unclearable, or stranded in the tray.

## Priority 3: long-session and mid-game reproduction

Run one uninterrupted game for at least 60 minutes:

1. Alternate Red and Blue rolls.
2. Cycle pool sizes: `1, 5, 26, 50, 76, 100, 128`.
3. Perform at least 250 normal tray batches per side.
4. Every 25 batches, roll 76 dice five times consecutively.
5. Leave the game idle for 10 minutes, then immediately roll 76 on Red.

Expected:

- No roll becomes permanently stuck on a face.
- If `[RNG RECOVERY]` appears, record the preceding seed and probe. The recovered
  roll and all following rolls must remain healthy without reloading.

## Priority 4: rapid-input and batching races

These tests target overlapping tray drains and interleaved debug output:

1. Spawn 128 dice and rapidly click **Roll All** 10 times.
2. While dice are returning, click **Roll All** repeatedly.
3. Reroll a result row while other dice are still settling.
4. Alternate **Roll All**, ordered roll, groups-of-two, and groups-of-three as
   quickly as possible.
5. Roll 128 on Red and 128 on Blue at almost the same time.
6. Drop extra physical dice into the tray while a button-driven batch enters.

Expected:

- One logical batch produces one coherent `dice=N` / `dist` pair.
- No dice loop repeatedly through the tray or remain inside it.
- Red and Blue results do not affect each other's counts or placement.
- A later normal roll remains healthy.

## Priority 5: every result path

Test each path separately on both sides:

- normal **Roll All**;
- row rerolls for faces 1 through 6;
- reroll row plus lower results;
- reroll row plus higher results;
- ordered roll;
- ordered groups of two;
- ordered groups of three;
- right-click quick-roll `1d6` through `5d6`;
- quick-roll immediately followed by normal Roll All;
- normal Roll All immediately followed by quick-roll.

Expected:

- Quick-roll and normal-roll sequences both remain varied.
- Normal rolls sort/place correctly.
- Ordered rolls preserve their intended grouping layout.
- No path poisons the next path's RNG state.

## Priority 6: dice-type and malformed-object coverage

Test:

- rounded D6 and square D6;
- each available tint;
- custom-image dice;
- copied opponent dice;
- D3;
- a mixed tray batch containing D3 and D6;
- Workshop/custom dice with unusual metadata, if available;
- a non-die object dropped into the tray.

Expected:

- Every valid die returns with a value inside its face range.
- Unknown dice safely fall back to D6 rather than stranding the batch.
- Non-dice objects are ejected.

## Priority 7: save, load, and reconnect boundaries

1. Roll 76 on Red, save, reload, then roll 76 again.
2. Save while dice are resting on the mat, reload, and roll.
3. Save while dice are entering or leaving the tray, reload, recover the table,
   and roll again.
4. Host a multiplayer game, have the Red player disconnect/reconnect, then roll.
5. Transfer host if practical, then roll on both sides.

Expected:

- Reloading produces a fresh healthy seed.
- No sequence is permanently repeated from the save.
- Multiplayer seating/reconnect does not change which mat/roller is used.

## Priority 8: placement and drift

For 76, 100, and 128 dice:

1. Normal roll repeatedly.
2. Inspect every result row and wrapped band.
3. Select all dice and confirm the selected count.
4. Clear the mat and confirm none remain.
5. Repeat after manually moving several dice near mat boundaries.

Expected:

- `[DRIFT CHECK]` remains `0 / N`.
- Every result shown physically matches `dist`.
- Wrapped dice remain within the mat's detection bounds.

## Stop-and-investigate conditions

Capture the full chat/debug log and stop the run if any of these occurs:

- all 26 or more dice show one face;
- two or more raw probe values repeat within one five-value probe;
- `dist` totals do not equal `dice=N`;
- a roll repeats exactly several times;
- `[RNG RECOVERY]` appears repeatedly rather than once;
- any `[DRIFT]` message appears;
- dice remain in the tray, leave the mat, or cannot be selected/cleared;
- Red and Blue batch messages appear to share counts.

## Automated simulations

Run:

```bash
python3 scripts/test_xoshiro128_rng.py
python3 scripts/stress_test_dice_rng.py --quick
python3 scripts/stress_test_dice_rng.py
```

The first script checks exact reference vectors, ranges, state resume behavior,
the captured sparse-state regression, and distributions.

The stress script independently compares the portable Lua-style operations with
Python's native 32-bit reference implementation, fuzzes healthy and corrupt
states, and simulates long sessions containing pools from 1 through 128 dice.

These simulations validate the result-generation algorithm and recovery logic.
They cannot simulate TTS object timing, `Wait` scheduling, container callbacks,
physics drift, or multiplayer synchronization, which is why the manual batching,
placement, and save/reload tests remain necessary.
