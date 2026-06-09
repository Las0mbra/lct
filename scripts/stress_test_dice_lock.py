#!/usr/bin/env python3
"""Stress-test the dice roller hard-lock timing model.

This models the lock/timer decisions controlled by the Lua scripts. It does not
attempt to reproduce TTS physics. The scenarios intentionally include delayed
container events, missing callbacks, manual drops, and repeated scripted rolls.

Usage:
    python3 scripts/stress_test_dice_lock.py
    python3 scripts/stress_test_dice_lock.py --quick
"""

from __future__ import annotations

import argparse
import heapq
import random
from dataclasses import dataclass, field
from typing import Callable


COLLECT_DELAY = 1.0
COMPLETE_DELAY = 0.1
SAFETY_TIMEOUT = 15.0


@dataclass
class Batch:
    roll_id: int
    expected: int | None
    manual: bool
    phase: str = "collecting"
    arrivals: set[int] = field(default_factory=set)
    pending_callbacks: int = 0
    extraction_scheduled: bool = False
    timer_generation: int = 0


class RollerModel:
    def __init__(self) -> None:
        self.now = 0.0
        self.next_roll_id = 0
        self.active: Batch | None = None
        self.events: list[tuple[float, int, Callable[[], None]]] = []
        self.event_seq = 0
        self.accepted_rolls = 0
        self.rejected_rolls = 0
        self.completed_rolls = 0
        self.timed_out_rolls = 0
        self.partial_rolls = 0
        self.ejected_dice = 0
        self.rolled_dice = 0

    def schedule(self, delay: float, callback: Callable[[], None]) -> None:
        self.event_seq += 1
        heapq.heappush(self.events, (self.now + delay, self.event_seq, callback))

    def run_until(self, target: float) -> None:
        while self.events and self.events[0][0] <= target:
            when, _, callback = heapq.heappop(self.events)
            self.now = when
            callback()
        self.now = target

    def run_all(self) -> None:
        while self.events:
            self.run_until(self.events[0][0])

    def release(self, batch: Batch, timeout: bool = False) -> None:
        if self.active is not batch:
            return
        if timeout:
            self.timed_out_rolls += 1
        self.active = None

    def begin_scripted(self, expected: int) -> int | None:
        if self.active:
            self.rejected_rolls += 1
            return None
        self.next_roll_id += 1
        batch = Batch(self.next_roll_id, expected, False)
        self.active = batch
        self.accepted_rolls += 1
        self.schedule(
            SAFETY_TIMEOUT,
            lambda batch=batch: self.release(batch, timeout=True),
        )
        return batch.roll_id

    def enter(self, die_id: int, roll_id: int | None, callback_delay: float = 0.01) -> None:
        batch = self.active
        belongs = batch is not None and roll_id == batch.roll_id

        if batch and batch.phase != "collecting":
            self.ejected_dice += 1
            return
        if batch and not belongs and not batch.manual:
            self.ejected_dice += 1
            return
        if batch is None:
            if roll_id is not None:
                self.ejected_dice += 1
                return
            self.next_roll_id += 1
            batch = Batch(self.next_roll_id, None, True)
            self.active = batch
            self.schedule(
                SAFETY_TIMEOUT,
                lambda batch=batch: self.release(batch, timeout=True),
            )

        batch.arrivals.add(die_id)
        batch.timer_generation += 1
        generation = batch.timer_generation
        complete = batch.expected is not None and len(batch.arrivals) >= batch.expected
        delay = COMPLETE_DELAY if complete else COLLECT_DELAY
        self.schedule(
            delay,
            lambda batch=batch, generation=generation, callback_delay=callback_delay:
                self.drain(batch, generation, callback_delay),
        )

    def drain(self, batch: Batch, generation: int, callback_delay: float) -> None:
        if self.active is not batch or batch.timer_generation != generation:
            return
        batch.phase = "processing"
        count = len(batch.arrivals)
        if batch.expected is not None and count != batch.expected:
            self.partial_rolls += 1
        batch.pending_callbacks = count
        batch.extraction_scheduled = True
        self.rolled_dice += count
        self.completed_rolls += 1
        if count == 0:
            self.release(batch)
            return
        for _ in range(count):
            self.schedule(
                callback_delay,
                lambda batch=batch: self.finish_callback(batch),
            )

    def finish_callback(self, batch: Batch) -> None:
        if self.active is not batch:
            return
        batch.pending_callbacks = max(0, batch.pending_callbacks - 1)
        if batch.extraction_scheduled and batch.pending_callbacks == 0:
            self.release(batch)


def run_normal_long_game(rng: random.Random, rolls: int) -> RollerModel:
    model = RollerModel()
    sizes = (1, 2, 5, 10, 26, 50, 76, 100, 128)
    for roll_index in range(rolls):
        size = sizes[roll_index % len(sizes)]
        roll_id = model.begin_scripted(size)
        assert roll_id is not None
        arrivals = sorted(rng.uniform(0.0, 0.20) for _ in range(size))
        start = model.now
        for die_index, delay in enumerate(arrivals):
            model.run_until(start + delay)
            model.enter(die_index, roll_id, callback_delay=rng.uniform(0.0, 0.08))
        model.run_until(start + 0.5)
        assert model.active is None
    assert model.partial_rolls == 0
    assert model.ejected_dice == 0
    assert model.timed_out_rolls == 0
    return model


def run_button_spam(rng: random.Random, attempts: int) -> RollerModel:
    model = RollerModel()
    for attempt in range(attempts):
        if model.active is None:
            roll_id = model.begin_scripted(76)
            assert roll_id is not None
            for die_id in range(76):
                model.schedule(
                    rng.uniform(0.0, 0.15),
                    lambda die_id=die_id, roll_id=roll_id:
                        model.enter(die_id, roll_id, callback_delay=0.03),
                )
        else:
            model.begin_scripted(76)
        model.run_until(model.now + rng.uniform(0.0, 0.03))
    model.run_all()
    assert model.active is None
    assert model.partial_rolls == 0
    return model


def run_manual_intrusion(rng: random.Random, rolls: int) -> RollerModel:
    model = RollerModel()
    intrusions = 0
    for _ in range(rolls):
        roll_id = model.begin_scripted(76)
        assert roll_id is not None
        for die_id in range(76):
            model.schedule(
                rng.uniform(0.0, 0.1),
                lambda die_id=die_id, roll_id=roll_id:
                    model.enter(die_id, roll_id, callback_delay=0.30),
            )
        for extra in range(rng.randint(1, 8)):
            intrusions += 1
            model.schedule(
                rng.uniform(0.22, 0.28),
                lambda extra=extra: model.enter(10_000 + extra, None),
            )
        model.run_until(model.now + 0.7)
        assert model.active is None
    assert model.ejected_dice == intrusions
    assert model.partial_rolls == 0
    return model


def run_delayed_arrival_sweep() -> list[tuple[float, RollerModel]]:
    results = []
    for gap in (0.25, 0.75, 0.99, 1.01, 1.5, 5.0, 16.0):
        model = RollerModel()
        roll_id = model.begin_scripted(10)
        assert roll_id is not None
        for die_id in range(5):
            model.enter(die_id, roll_id)
        model.run_until(gap)
        for die_id in range(5, 10):
            model.enter(die_id, roll_id)
        model.run_all()
        results.append((gap, model))
    return results


def run_missing_callback_recovery() -> RollerModel:
    model = RollerModel()
    roll_id = model.begin_scripted(10)
    assert roll_id is not None
    for die_id in range(10):
        model.enter(die_id, roll_id, callback_delay=30.0)
    model.run_until(15.1)
    assert model.active is None
    next_id = model.begin_scripted(1)
    assert next_id is not None
    model.enter(999, next_id)
    model.run_all()
    assert model.active is None
    return model


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    rng = random.Random(0xD1CE10CC)

    normal_rolls = 10_000 if args.quick else 100_000
    spam_attempts = 10_000 if args.quick else 100_000
    intrusion_rolls = 1_000 if args.quick else 10_000

    normal = run_normal_long_game(rng, normal_rolls)
    spam = run_button_spam(rng, spam_attempts)
    intrusion = run_manual_intrusion(rng, intrusion_rolls)
    delayed = run_delayed_arrival_sweep()
    missing = run_missing_callback_recovery()

    print(
        f"Normal long game: PASS ({normal.completed_rolls:,} rolls, "
        f"{normal.rolled_dice:,} dice, 0 partial/ejected/timeouts)"
    )
    print(
        f"Button spam: PASS ({spam.accepted_rolls:,} accepted, "
        f"{spam.rejected_rolls:,} safely rejected)"
    )
    print(
        f"Manual intrusion: PASS ({intrusion.ejected_dice:,} unexpected dice ejected)"
    )
    print("Delayed arrival sweep:")
    for gap, model in delayed:
        print(
            f"  gap={gap:>5.2f}s partial={model.partial_rolls} "
            f"ejected={model.ejected_dice} timeouts={model.timed_out_rolls}"
        )
    print(
        f"Missing callback recovery: PASS ({missing.timed_out_rolls} timeout, "
        "next scripted roll accepted)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
