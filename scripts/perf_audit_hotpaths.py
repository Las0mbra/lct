#!/usr/bin/env python3
"""Quantify the algorithmic cost of the always-on / spam-triggered hot paths.

This does NOT run TTS. It ports the *exact* algorithmic shape of three Lua hot
paths so we can put concrete operation counts and wall-times against the
performance-audit claims, and see how each scales with table/selection size:

  1. customDiceTable.refreshCoherencyLines()  -- O(n^2), 10 Hz, up to 15 s
  2. customKustom40kDiceRollerMk3.takeDiceOut() hasGuid() -- O(n^2) placement
  3. customDiceTable.checkDice()  -- O(total objects), 5 Hz, forever, x2 mats

The point is relative scaling and "ops per real-time window", not microsecond
parity with the Lua VM (which is slower per op than CPython).

Usage:
    python3 scripts/perf_audit_hotpaths.py
"""

from __future__ import annotations

import math
import time


# --- 1. Coherency: exact port of baseGap + the two-rule pairwise loops --------

def base_radius_in_dir(d, dx, dz):
    lx = dx * d["rx"] + dz * d["rz"]
    lz = dx * d["fx"] + dz * d["fz"]
    return 1.0 / math.sqrt((lx * lx) / (d["a"] * d["a"]) + (lz * lz) / (d["b"] * d["b"]))


def base_gap(d1, d2):
    dx, dz = d2["x"] - d1["x"], d2["z"] - d1["z"]
    centre = math.sqrt(dx * dx + dz * dz)
    if centre < 1e-6:
        return 0.0
    ux, uz = dx / centre, dz / centre
    r1 = base_radius_in_dir(d1, ux, uz)
    r2 = base_radius_in_dir(d2, -ux, -uz)
    gap = centre - r1 - r2
    return gap if gap > 0 else 0.0


def make_models(n):
    # 32mm bases (~1.26") on a loose grid, mirrors a deployed squad/army.
    out = []
    side = max(1, int(math.ceil(math.sqrt(n))))
    for i in range(n):
        out.append({
            "x": (i % side) * 1.3, "z": (i // side) * 1.3,
            "a": 0.63, "b": 0.63, "rx": 1.0, "rz": 0.0, "fx": 0.0, "fz": 1.0,
        })
    return out


def coherency_refresh(models):
    """One refreshCoherencyLines() tick. Returns (gap_ops, line_count)."""
    n = len(models)
    gap = [[0.0] * n for _ in range(n)]
    ops = 0
    for i in range(n):
        for j in range(i + 1, n):
            g = base_gap(models[i], models[j])
            gap[i][j] = gap[j][i] = g
            ops += 1
    lines = 0
    # Rule 1: nearest-buddy scan (n^2)
    for i in range(n):
        has_buddy = False
        nearest = None
        nearest_d = math.inf
        for j in range(n):
            if i != j:
                d = gap[i][j]
                if d <= 2:
                    has_buddy = True
                if d < nearest_d:
                    nearest_d, nearest = d, j
        if not has_buddy and nearest is not None:
            lines += 1
    # Rule 2: every pair within 9" (n^2)
    for i in range(n):
        for j in range(i + 1, n):
            if gap[i][j] > 9:
                lines += 1
    return ops, lines


# --- 2. Dice placement: exact O(n^2) hasGuid() shape --------------------------

def has_guid(objs, g):
    for v in objs:          # linear scan, mirrors Lua hasGuid()
        if v == g:
            return True
    return False


def dice_placement_ops(num_dice):
    objs = list(range(num_dice))        # dice present on the mat
    sorted_keys = list(range(num_dice))  # iterated in takeDiceOut
    ops = 0
    for key in sorted_keys:
        # hasGuid(objs, key) runs once per die -> O(n) each -> O(n^2) total
        for _ in objs:
            ops += 1
            if _ == key:
                break
    return ops


# --- 3. checkDice full-scene scan --------------------------------------------

def checkdice_scan_ops(total_objects):
    """One checkDice() tick iterates every object in the scene once."""
    return total_objects


def banner(t):
    print("\n" + "=" * 64 + f"\n{t}\n" + "=" * 64)


def main():
    banner("1. Coherency monitor  (O(n^2), 10 Hz, auto-stops at 15 s)")
    print(f"{'models':>7} {'gap ops/tick':>13} {'ops/15s @10Hz':>15} {'ms/tick':>9}")
    for n in (5, 10, 20, 30, 50, 100, 150):
        models = make_models(n)
        t0 = time.perf_counter()
        reps = 200
        ops = lines = 0
        for _ in range(reps):
            ops, lines = coherency_refresh(models)
        ms = (time.perf_counter() - t0) / reps * 1000
        window = ops * 10 * 15  # ticks/s * seconds
        print(f"{n:>7} {ops:>13,} {window:>15,} {ms:>9.3f}")
    print("  Note: CPython is ~10-50x faster per op than the TTS Lua VM, and the")
    print("  Lua version also rebuilds + Global.setVectorLines() every tick.")

    banner("2. Dice roller placement  hasGuid() O(n^2) per roll")
    print(f"{'dice':>7} {'hasGuid ops':>13} {'ms':>9}")
    for n in (6, 10, 30, 60, 120, 240):
        t0 = time.perf_counter()
        ops = dice_placement_ops(n)
        ms = (time.perf_counter() - t0) * 1000
        print(f"{n:>7} {ops:>13,} {ms:>9.3f}")

    banner("3. checkDice full-scene scan  (5 Hz, forever, x2 mats)")
    print(f"{'objects':>8} {'scans/min (2 mats)':>20} {'obj-iters/min':>15}")
    for n in (50, 200, 500, 1000, 2000):
        scans = 5 * 60 * 2          # 5 Hz * 60 s * 2 mats
        print(f"{n:>8} {scans:>20,} {scans * n:>15,}")
    print("  Each tick also calls getAllObjects() which allocates a fresh table")
    print("  of the whole scene before the filter loop even runs.")


if __name__ == "__main__":
    main()
