# LCT 40k TTS — Performance & Regression Audit

Date: 2026-06-11 · Branch: `main` @ `3061750` · No game code was modified.
Reproduce the numbers below with `python3 scripts/perf_audit_hotpaths.py`.

---

## 1. Did the cleanup break anything? — No regressions found

The last 5 commits removed ~2,800 lines: `kustom40kDiceRollerMk3.ttslua`,
`statsHelperv2.ttslua`, `woundsRemaining.ttslua`, `squadActivation.ttslua`, plus
the spawn helpers in `spawnGameTools.ttslua` (`spawnActivation`, `spawnWounds`,
`spawnItem`, `resetTokens`, `lockItem`, `linkMini`, `none`) and
`resetActivationTokens` in `startMenu.ttslua`.

Verification performed:

| Check | Result |
|---|---|
| `python3 compile.py --no-validate` | ✅ Builds clean — 45 object scripts + global, 15 map hooks |
| `python3 validate_maps.py` | ✅ 15/15 cards pass, 0 errors, 0 warnings, all on v2 zones |
| Dangling refs to removed scripts (lua + xml) | ✅ None |
| Dangling callers of removed functions (lua + xml + baked JSON) | ✅ None |
| All 21 XML `onClick` handlers resolve to a live function | ✅ except `closeRedir` (see below) |
| `stress_test_dice_lock.py --quick` | ✅ PASS |
| `stress_test_dice_rng.py --quick` | ✅ PASS (469k rolls, max \|z\|=1.51) |

**Pre-existing latent issue (NOT a regression):** the XML `closeRedirectBtn`
(`TTSJSON/ftc_base_ui.xml:14`) has `onClick="closeRedir"`, but no `closeRedir`
function has ever existed (present since the initial commit). The `redirect`
panel is `active="false"` by default, so this only fails if that panel is shown
and the player clicks CLOSE — TTS logs a harmless "function not found".

**Minor model/code drift:** `stress_test_dice_lock.py` models `COLLECT_DELAY = 0.5`,
but the Lua now uses `collectDiceDelay = 0.2` (`customKustom40kDiceRollerMk3.ttslua:315`).
The test still passes because it checks lock *behaviour*, not exact timing — but
the constant should be synced so the model stays honest.

**Not statically checked:** the compiler validates JSON output but never parses
the Lua. No `lua`/`luac` is installed here, so `test_xoshiro128_rng.py` was
skipped and no Lua syntax/lint gate exists. Worth adding `luacheck` to the build.

---

## 2. Performance audit — where the time goes

TTS runs all object scripts on a single Lua thread; anything in a repeating
`Wait.time(..., -1)` or `onUpdate` competes with the render loop every tick.

### Always-on background loops (run for the entire session)

| Source | Interval | Per-tick cost | Verdict |
|---|---|---|---|
| **`customDiceTable.checkDice`** ×2 mats | 0.2 s (5 Hz) | `getAllObjects()` + scan **every object in the scene** | ⚠️ **Top always-on cost** |
| `SelectionHighlighter.checkSelections` | 0.1 s (10 Hz) | iterate players × selected objects | OK (scales with selection) |
| `chessClock.Tick` | `RESOLUTION` | clock decrement | OK |
| `gameRounds` / `turns` / `cpCounter` `checkValue` | 0.5 s | one `Counter.getValue()`, O(1) | Negligible |
| `InjectionDetector.objectCheck` | 10 s | `getLuaScript()` length compare, O(1) | Negligible (but weak, see §3) |
| `global.checkForMonitoredID` | 30 s | poll | Negligible |

**`checkDice` is the standout.** It fires 5×/s on **each** of the two dice mats
forever, and each call does `getAllObjects()` (allocates a fresh table of the
whole scene) then iterates it filtering for resting dice. The cost grows with
**total table population**, not with dice in play — so it gets *worse the more
army models players load*, even when nobody is rolling:

```
objects   scans/min (2 mats)   obj-iters/min
     50                  600          30,000
    500                  600         300,000
   2000                  600       1,200,000   <- fully loaded table, forever
```

Cheap fixes: gate on `self.resting` (already there) *before* the early work;
cache the bounds; and most importantly raise `Update_Frequency` (the description
default is `0.2`) or only scan when the mat actually has dice on/near it
(e.g. a count check via a scripting zone) instead of the whole scene.

### Heaviest on-demand hot path — the Coherency monitor

`customDiceTable.refreshCoherencyLines` runs **O(n²)** pairwise base-gap math
(`baseGap` → ellipse trig) **plus** an O(n²) rebuild of vector lines, on a
`Wait.time(refreshCoherencyLines, 0.1, -1)` — **10 Hz for up to 15 s**
(`customDiceTable.ttslua:2602`, `COHERENCY_REFRESH = 0.1`, `COHERENCY_TIMEOUT = 15`).

`n` is **whatever the player has selected**. Box-selecting a large unit or a
whole army and clicking *Coherency* is fully supported and triggers this:

```
models  gap ops/tick   ops/15s @10Hz   ms/tick (CPython)
    30           435          65,250     0.507
    50         1,225         183,750     1.411
   100         4,950         742,500     5.725
   150        11,175       1,676,250    12.948
```

CPython is ~10–50× faster per op than the TTS Lua VM, and Lua *also* rebuilds
the lines/labels and calls `Global.setVectorLines()` each tick. At 100+ models
this realistically means tens-to-hundreds of ms per tick at 10 Hz — i.e. a
visible 15-second framerate stall. Cheap fixes: drop the refresh to ~0.25–0.5 s,
and/or cap the monitored set (warn above e.g. 40 models).

### O(n²) in the dice placement loop

`takeDiceOut` calls `hasGuid(objs, key)` (a linear scan, `:487`) once per die
inside the placement loop → **O(n²)** per roll:

```
dice   hasGuid ops
  30           465
 120         7,260
 240        28,920
```

Tolerable for normal rolls; only bites on huge dice pools. Trivial fix: build a
`guidSet[guid]=true` lookup once and replace `hasGuid` with an O(1) membership
test (the loop already iterates the same set).

### Software-emulated PRNG bit ops

`customKustom40kDiceRollerMk3` deliberately reimplements xoshiro128++ with
nibble lookup tables + per-op loops to dodge TTS's buggy `bit32`
(`:48–120`). This is correct and well-justified, but each 32-bit op is dozens
of Lua ops instead of one. It only runs per-roll (not per-frame), so it's fine —
just be aware a 200-die pool pays this cost 200×.

---

## 3. Player actions that could break or stall the game

1. **Box-select a whole army → Coherency.** The single most likely way to make
   the table chug: O(n²) at 10 Hz for 15 s (see above). Not a crash, but a real
   stall on big selections. *Highest-impact, easy mitigation.*

2. **Loading lots of army models, then leaving the table idle.** `checkDice`
   keeps scanning the entire (now huge) scene 10×/s combined across both mats
   forever. Performance silently degrades with table population. This is exactly
   the "loading objects" worry — but a *perf* effect, not a crash.

3. **Spamming the dice roller / dumping a giant dice pool.** Well-defended:
   `activeRollBatch` lock rejects concurrent rolls, stray dice are ejected with
   a notice, and a 15 s safety timer always releases a stuck lock
   (`:344–417`, `:494–558`). Spamming is safe; only the O(n²) placement above is
   a soft cost on very large pools.

4. **Double/triple-clicking START GAME.** Largely safe: on success
   `writeMenus()` swaps to the in-game menu and removes the button, and
   `gameNotStartedGuard()` protects the HUD actions. **But** `startGame()` has no
   `if inGame then return` guard and does all its heavy work (return cards, move
   primaries, `scoresheet.call("startGame")`, `startCustomTurns()`, spawn
   objectives) *before* setting `inGame=true` and redrawing
   (`startMenu.ttslua:3187–3244`). A fast double-click within that synchronous
   window is the only re-entry risk; adding a one-line guard at the top closes
   it for free.

5. **"Weird scripts" on loaded objects — detector is weak.** `InjectionDetector`
   only compares the length of *its own* `getLuaScript()`
   (`InjectionDetector.ttslua:55`), so it does **not** actually inspect objects a
   player spawns/imports. A malicious or just-expensive imported object (e.g. one
   with its own `onUpdate`) will run unchecked and the detector won't notice.
   This is a security/perf gap to be aware of, though fully sandboxing imported
   objects isn't really possible in TTS.

6. **Leftover `debug = true` raycast.** `statHelper.findCustomDie` issues a
   `Physics.cast{ debug = true }` (`:199–205`), which draws debug overlays. Only
   on the "Set Custom Dice" click, so low-impact, but the debug flag should be
   off in a release build.

---

## 4. Recommendations (ranked by value / effort)

| # | Change | File | Why |
|---|---|---|---|
| 1 | Throttle Coherency refresh to ~0.3 s and/or cap monitored models | `customDiceTable.ttslua:2602` | Removes the worst player-triggered stall |
| 2 | Make `checkDice` skip the full-scene scan when no dice are present / raise `Update_Frequency` | `customDiceTable.ttslua:1393,1670` | Removes the biggest always-on cost; stops degradation as armies load |
| 3 | Replace `hasGuid` linear scan with a set lookup | `customKustom40kDiceRollerMk3.ttslua:487,672` | Kills O(n²) on large dice pools, trivial |
| 4 | Add `if inGame then return end` to `startGame` | `startMenu.ttslua:3187` | Closes the double-click re-entry window |
| 5 | Define `closeRedir` (or change the button's `onClick`) | `ftc_base_ui.xml:14` | Fixes a latent dead handler |
| 6 | Sync `COLLECT_DELAY` in the lock stress model to 0.2 | `scripts/stress_test_dice_lock.py:23` | Keeps the model faithful |
| 7 | Drop `debug = true` from the custom-die raycast | `statHelper.ttslua:200` | Remove stray debug rendering |
| 8 | Add `luacheck` to the build / install `lua` so `test_xoshiro128_rng.py` runs | `scripts/compile.py` | No static Lua checking exists today |

**Bottom line:** the cleanup introduced no regressions — build, map validation,
and both dice stress suites pass, and nothing references the removed code. The
mod is in good shape. The performance ceiling is set by two O(n²)/full-scan loops
in `customDiceTable` (Coherency and `checkDice`); both have cheap, low-risk fixes
and are the only things likely to bite players on a heavily-loaded table.
