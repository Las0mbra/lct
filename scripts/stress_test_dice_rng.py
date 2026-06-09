#!/usr/bin/env python3
"""Stress-test the dice roller RNG and recovery assumptions.

This is intentionally independent from TTS. It compares a model of the portable
Lua arithmetic against Python's native 32-bit bit operations, fuzzes arbitrary
states, rejects sparse/corrupt states, and simulates long sessions of dice pools.

Usage:
    python3 scripts/stress_test_dice_rng.py
    python3 scripts/stress_test_dice_rng.py --quick
"""

from __future__ import annotations

import argparse
import math
import random
import time


UINT32 = 1 << 32
MASK32 = UINT32 - 1
FALLBACK_STATE = (0x9E3779B9, 0x243F6A88, 0xB7E15162, 0x8AED2A6B)
REPORTED_BAD_STATE = (0, 0, 1020716019, 0)
XOR_NIBBLE = tuple(tuple(a ^ b for b in range(16)) for a in range(16))


def u32(value: int) -> int:
    return value % UINT32


def portable_xor_two(a: int, b: int) -> int:
    value = 0
    place = 1
    a, b = u32(a), u32(b)
    for _ in range(8):
        value += XOR_NIBBLE[a % 16][b % 16] * place
        a //= 16
        b //= 16
        place *= 16
    return value


def portable_xor(*values: int) -> int:
    result = 0
    for value in values:
        result = portable_xor_two(result, value)
    return result


def portable_lshift(value: int, amount: int) -> int:
    return u32(u32(value) * (2**amount))


def portable_rshift(value: int, amount: int) -> int:
    return u32(value) // (2**amount)


def portable_rotl(value: int, amount: int) -> int:
    amount %= 32
    value = u32(value)
    if amount == 0:
        return value
    return u32(portable_lshift(value, amount) + portable_rshift(value, 32 - amount))


def native_rotl(value: int, amount: int) -> int:
    amount %= 32
    value &= MASK32
    return ((value << amount) | (value >> (32 - amount))) & MASK32


def portable_step(state: tuple[int, int, int, int]) -> tuple[int, tuple[int, int, int, int]]:
    s0, s1, s2, s3 = state
    result = u32(portable_rotl(u32(s0 + s3), 7) + s0)
    t = portable_lshift(s1, 9)
    s2 = portable_xor(s2, s0)
    s3 = portable_xor(s3, s1)
    s1 = portable_xor(s1, s2)
    s0 = portable_xor(s0, s3)
    s2 = portable_xor(s2, t)
    s3 = portable_rotl(s3, 11)
    return result, (s0, s1, s2, s3)


def native_step(state: tuple[int, int, int, int]) -> tuple[int, tuple[int, int, int, int]]:
    s0, s1, s2, s3 = state
    result = (native_rotl((s0 + s3) & MASK32, 7) + s0) & MASK32
    t = (s1 << 9) & MASK32
    s2 ^= s0
    s3 ^= s1
    s1 ^= s2
    s0 ^= s3
    s2 ^= t
    s3 = native_rotl(s3, 11)
    return result, tuple(v & MASK32 for v in (s0, s1, s2, s3))


def usable_state(state: object) -> bool:
    if not isinstance(state, (tuple, list)) or len(state) < 4:
        return False
    try:
        return sum(1 for value in state[:4] if u32(int(value)) != 0) >= 2
    except (TypeError, ValueError, OverflowError):
        return False


def healthy_state(state: object) -> bool:
    if not usable_state(state):
        return False
    probe = tuple(u32(int(v)) for v in state[:4])
    seen: set[int] = set()
    for _ in range(8):
        raw, probe = portable_step(probe)
        if raw in seen:
            return False
        seen.add(raw)
    return True


def bounded(raw: int, faces: int) -> int:
    return raw % faces + 1


def max_abs_zscore(counts: list[int]) -> float:
    total = sum(counts)
    expected = total / len(counts)
    p = 1.0 / len(counts)
    sigma = math.sqrt(total * p * (1.0 - p))
    return max(abs((count - expected) / sigma) for count in counts)


def check_portable_matches_native(rng: random.Random, states: int, steps: int) -> int:
    comparisons = 0
    for _ in range(states):
        portable = tuple(rng.getrandbits(32) for _ in range(4))
        native = portable
        for _ in range(steps):
            portable_raw, portable = portable_step(portable)
            native_raw, native = native_step(native)
            assert portable_raw == native_raw
            assert portable == native
            comparisons += 1
    return comparisons


def check_corrupt_state_detection(rng: random.Random, random_cases: int) -> int:
    corrupt: list[object] = [
        (0, 0, 0, 0),
        REPORTED_BAD_STATE,
        (1, 0, 0, 0),
        (0, 2, 0, 0),
        (0, 0, 3, 0),
        (0, 0, 0, 4),
        (),
        (1, 2, 3),
        ("bad", 1, 2, 3),
        None,
    ]
    for _ in range(random_cases):
        position = rng.randrange(4)
        state = [0, 0, 0, 0]
        state[position] = rng.getrandbits(32) or 1
        corrupt.append(tuple(state))

    for state in corrupt:
        assert not healthy_state(state), f"corrupt state accepted: {state!r}"

    for _ in range(random_cases):
        while True:
            state = tuple(rng.getrandbits(32) for _ in range(4))
            if usable_state(state):
                break
        assert healthy_state(state), f"healthy random state rejected: {state!r}"

    assert healthy_state(FALLBACK_STATE)
    return len(corrupt) + random_cases + 1


def simulate_batches(
    rng: random.Random,
    sessions: int,
    batches_per_session: int,
    batch_sizes: tuple[int, ...],
) -> tuple[int, int, float, int]:
    total_rolls = 0
    all_same_batches = 0
    longest_same_run = 0
    counts = [0] * 6

    for _ in range(sessions):
        state = tuple(rng.getrandbits(32) for _ in range(4))
        if not healthy_state(state):
            state = FALLBACK_STATE
        previous = None
        same_run = 0

        for batch_index in range(batches_per_session):
            size = batch_sizes[batch_index % len(batch_sizes)]
            batch_counts = [0] * 6
            for _ in range(size):
                raw, state = portable_step(state)
                face = bounded(raw, 6)
                counts[face - 1] += 1
                batch_counts[face - 1] += 1
                total_rolls += 1
                if face == previous:
                    same_run += 1
                else:
                    previous = face
                    same_run = 1
                longest_same_run = max(longest_same_run, same_run)
            if size >= 26 and max(batch_counts) == size:
                all_same_batches += 1

    return total_rolls, all_same_batches, max_abs_zscore(counts), longest_same_run


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true", help="Run a smaller CI-friendly simulation.")
    args = parser.parse_args()

    rng = random.Random(0x1C7D1CE)
    if args.quick:
        fuzz_states, fuzz_steps = 2_000, 20
        corrupt_cases = 2_000
        sessions, batches = 100, 100
    else:
        fuzz_states, fuzz_steps = 10_000, 50
        corrupt_cases = 10_000
        sessions, batches = 500, 250

    started = time.monotonic()
    comparisons = check_portable_matches_native(rng, fuzz_states, fuzz_steps)
    state_cases = check_corrupt_state_detection(rng, corrupt_cases)
    rolls, all_same, max_z, longest_run = simulate_batches(
        rng,
        sessions,
        batches,
        (1, 2, 5, 26, 50, 76, 100, 128),
    )

    assert all_same == 0, f"observed {all_same} all-same large batches"
    assert max_z < 6.0, f"distribution suspicious: max |z| = {max_z:.2f}"
    assert longest_run < 30, f"implausibly long same-face run: {longest_run}"

    elapsed = time.monotonic() - started
    print(f"Portable/native transition comparisons: PASS ({comparisons:,})")
    print(f"Corrupt/healthy state classifications: PASS ({state_cases:,})")
    print(f"Simulated D6 rolls: PASS ({rolls:,})")
    print(f"All-same 26+ die batches: {all_same}")
    print(f"Distribution max |z|: {max_z:.2f}")
    print(f"Longest identical-face run: {longest_run}")
    print(f"Elapsed: {elapsed:.2f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
