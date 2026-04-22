#!/usr/bin/env python3
"""Run a Lua-side xoshiro128++ harness and validate its output.

This script mirrors the dice roller's xoshiro128++ implementation, runs the
same logic through a local Lua interpreter, and checks:

1. Exact deterministic output for `nextRngU32()` against a Python reference.
2. Exact deterministic output for bounded d6 rolls against the same reference.
3. Range validity for d3/d6/d20 sample rolls.
4. Basic distribution sanity for d3/d6/d20 using z-score thresholds.

Usage:
    python3 scripts/test_xoshiro128_rng.py

Optional:
    LUA_BIN=/path/to/lua python3 scripts/test_xoshiro128_rng.py
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass
from typing import Iterable


UINT32 = 2**32


def u32(value: int) -> int:
    return value % UINT32


def rol32(value: int, shift: int) -> int:
    shift %= 32
    return u32(((value << shift) & 0xFFFFFFFF) | (value >> (32 - shift)))


@dataclass
class Xoshiro128PlusPlus:
    s0: int
    s1: int
    s2: int
    s3: int

    def next_u32(self) -> int:
        result = u32(rol32(u32(self.s0 + self.s3), 7) + self.s0)
        t = u32(self.s1 << 9)

        s0, s1, s2, s3 = self.s0, self.s1, self.s2, self.s3
        s2 ^= s0
        s3 ^= s1
        s1 ^= s2
        s0 ^= s3
        s2 ^= t
        s3 = rol32(s3, 11)

        self.s0, self.s1, self.s2, self.s3 = map(u32, (s0, s1, s2, s3))
        return result

    def bounded(self, bound: int) -> int:
        if bound <= 0:
            return 0
        threshold = (UINT32 - bound) % bound
        while True:
            value = self.next_u32()
            if value >= threshold:
                return value % bound

    def roll_face(self, faces: int) -> int:
        return self.bounded(faces) + 1


LUA_HARNESS = textwrap.dedent(
    r"""
    local bit = bit32 or bit
    assert(bit, "Requires bit32 or bit library")

    local function lrotate(x, n)
        if bit.lrotate then
            return bit.lrotate(x, n)
        end
        if bit.rol then
            return bit.rol(x, n)
        end
        error("No rotate-left implementation available")
    end

    local UINT32 = 4294967296

    local rngState = {1, 2, 3, 4}

    local function setRngState(state)
        rngState = {
            state[1] % UINT32,
            state[2] % UINT32,
            state[3] % UINT32,
            state[4] % UINT32,
        }
    end

    local function nextRngU32()
        local s0 = rngState[1]
        local s1 = rngState[2]
        local s2 = rngState[3]
        local s3 = rngState[4]

        local result = (lrotate((s0 + s3) % UINT32, 7) + s0) % UINT32
        local t = bit.lshift(s1, 9)

        s2 = bit.bxor(s2, s0)
        s3 = bit.bxor(s3, s1)
        s1 = bit.bxor(s1, s2)
        s0 = bit.bxor(s0, s3)
        s2 = bit.bxor(s2, t)
        s3 = lrotate(s3, 11)

        rngState[1] = s0
        rngState[2] = s1
        rngState[3] = s2
        rngState[4] = s3

        return result
    end

    local function nextRngBounded(bound)
        if bound <= 0 then
            return 0
        end

        local threshold = (UINT32 - bound) % bound
        while true do
            local value = nextRngU32()
            if value >= threshold then
                return value % bound
            end
        end
    end

    local function rollFace(faces)
        return nextRngBounded(faces) + 1
    end

    local function csv(values)
        local parts = {}
        for i, value in ipairs(values) do
            parts[i] = tostring(value)
        end
        return table.concat(parts, ",")
    end

    local function sampleCounts(faces, rolls)
        local counts = {}
        for i = 1, faces do
            counts[i] = 0
        end
        for _ = 1, rolls do
            counts[rollFace(faces)] = counts[rollFace(faces)] + 1
        end
        return counts
    end

    local function sampleRolls(faces, rolls)
        local values = {}
        for i = 1, rolls do
            values[i] = rollFace(faces)
        end
        return values
    end

    setRngState({1, 2, 3, 4})
    local seq = {}
    for i = 1, 20 do
        seq[i] = nextRngU32()
    end
    print("U32 " .. csv(seq))

    setRngState({1, 2, 3, 4})
    local d6seq = sampleRolls(6, 50)
    print("D6SEQ " .. csv(d6seq))

    setRngState({1, 2, 3, 4})
    local d3rolls = sampleRolls(3, 1000)
    print("D3RANGE " .. csv(d3rolls))

    setRngState({1, 2, 3, 4})
    local d6rolls = sampleRolls(6, 1000)
    print("D6RANGE " .. csv(d6rolls))

    setRngState({1, 2, 3, 4})
    local d20rolls = sampleRolls(20, 1000)
    print("D20RANGE " .. csv(d20rolls))

    setRngState({1, 2, 3, 4})
    local counts3 = {0, 0, 0}
    for _ = 1, 120000 do
        local face = rollFace(3)
        counts3[face] = counts3[face] + 1
    end
    print("COUNTS3 " .. csv(counts3))

    setRngState({1, 2, 3, 4})
    local counts6 = {0, 0, 0, 0, 0, 0}
    for _ = 1, 120000 do
        local face = rollFace(6)
        counts6[face] = counts6[face] + 1
    end
    print("COUNTS6 " .. csv(counts6))

    setRngState({1, 2, 3, 4})
    local counts20 = {}
    for i = 1, 20 do
        counts20[i] = 0
    end
    for _ = 1, 200000 do
        local face = rollFace(20)
        counts20[face] = counts20[face] + 1
    end
    print("COUNTS20 " .. csv(counts20))

    setRngState({1, 2, 3, 4})
    for _ = 1, 10 do
        nextRngU32()
    end
    local saved = {rngState[1], rngState[2], rngState[3], rngState[4]}
    local resume_a = {}
    for i = 1, 10 do
        resume_a[i] = nextRngU32()
    end
    setRngState(saved)
    local resume_b = {}
    for i = 1, 10 do
        resume_b[i] = nextRngU32()
    end
    print("RESUME_A " .. csv(resume_a))
    print("RESUME_B " .. csv(resume_b))
    """
).strip()


def choose_lua_binary() -> str:
    env_bin = os.environ.get("LUA_BIN")
    if env_bin:
        return env_bin
    for candidate in ("lua", "lua5.4", "lua5.3", "lua5.2", "luajit"):
        path = shutil.which(candidate)
        if path:
            return path
    raise SystemExit(
        "No Lua interpreter found. Set LUA_BIN or install lua/lua5.2/luajit."
    )


def run_lua_harness(lua_bin: str) -> dict[str, list[int]]:
    with tempfile.NamedTemporaryFile("w", suffix=".lua", delete=False) as handle:
        handle.write(LUA_HARNESS)
        temp_path = handle.name

    try:
        proc = subprocess.run(
            [lua_bin, temp_path],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"Lua harness failed with {lua_bin}:\nSTDOUT:\n{exc.stdout}\nSTDERR:\n{exc.stderr}"
        ) from exc
    finally:
        try:
            os.unlink(temp_path)
        except OSError:
            pass

    parsed: dict[str, list[int]] = {}
    for line in proc.stdout.splitlines():
        key, values = line.split(" ", 1)
        parsed[key] = [int(v) for v in values.split(",") if v]
    return parsed


def assert_equal(label: str, lhs: Iterable[int], rhs: Iterable[int]) -> None:
    lhs_list = list(lhs)
    rhs_list = list(rhs)
    if lhs_list != rhs_list:
        raise AssertionError(f"{label} mismatch\nexpected: {rhs_list}\nactual:   {lhs_list}")


def assert_range(label: str, values: Iterable[int], low: int, high: int) -> None:
    bad = [v for v in values if v < low or v > high]
    if bad:
        raise AssertionError(f"{label} produced out-of-range values: {bad[:10]}")


def max_abs_zscore(counts: list[int]) -> float:
    total = sum(counts)
    buckets = len(counts)
    expected = total / buckets
    p = 1.0 / buckets
    sigma = math.sqrt(total * p * (1.0 - p))
    return max(abs((count - expected) / sigma) for count in counts)


def main() -> int:
    lua_bin = choose_lua_binary()
    lua_results = run_lua_harness(lua_bin)

    ref = Xoshiro128PlusPlus(1, 2, 3, 4)
    expected_u32 = [ref.next_u32() for _ in range(20)]
    assert_equal("U32 sequence", lua_results["U32"], expected_u32)

    ref = Xoshiro128PlusPlus(1, 2, 3, 4)
    expected_d6 = [ref.roll_face(6) for _ in range(50)]
    assert_equal("D6 sequence", lua_results["D6SEQ"], expected_d6)

    assert_range("D3 range", lua_results["D3RANGE"], 1, 3)
    assert_range("D6 range", lua_results["D6RANGE"], 1, 6)
    assert_range("D20 range", lua_results["D20RANGE"], 1, 20)

    assert_equal("Resume sequence", lua_results["RESUME_A"], lua_results["RESUME_B"])

    z3 = max_abs_zscore(lua_results["COUNTS3"])
    z6 = max_abs_zscore(lua_results["COUNTS6"])
    z20 = max_abs_zscore(lua_results["COUNTS20"])

    if z3 > 6.0:
        raise AssertionError(f"D3 distribution looks suspicious: max |z| = {z3:.2f}")
    if z6 > 6.0:
        raise AssertionError(f"D6 distribution looks suspicious: max |z| = {z6:.2f}")
    if z20 > 6.0:
        raise AssertionError(f"D20 distribution looks suspicious: max |z| = {z20:.2f}")

    print(f"Lua interpreter: {lua_bin}")
    print("Exact-sequence checks: PASS")
    print("Range checks: PASS")
    print("Resume/state checks: PASS")
    print(f"Distribution sanity: PASS (max |z| d3={z3:.2f}, d6={z6:.2f}, d20={z20:.2f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
