from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pandas as pd

from malecns.brain_server import RuntimeRegistry
from malecns.brain import BrainSimulation
from malecns.loader import normalize_edges, normalize_neurons


class FakeRuntime:
    """Small stateful runtime used to test the server population boundary."""

    def __init__(self, cache_dir: str | Path, *, seed: int, window_ms: float) -> None:
        self.cache_dir = Path(cache_dir)
        self.seed = seed
        self.window_ms = window_ms
        self.spike_history: list[dict[str, Any]] = []
        self.motor_output: list[int] = []

    def step(self, stimulation: dict[str, Any]) -> None:
        self.spike_history.append(stimulation)
        # The real runtime derives motor output from its own Brian2 state.
        # This sentinel makes accidental object/seed sharing observable here.
        self.motor_output.append(self.seed + len(self.spike_history))


class TestRuntimePopulationIndependence:
    def test_each_fly_gets_distinct_persistent_state_and_seed(self) -> None:
        async def load_population() -> tuple[FakeRuntime, FakeRuntime, FakeRuntime]:
            registry = RuntimeRegistry("unused-cache", base_seed=17, runtime_factory=FakeRuntime)
            first = await registry.get("fly-001")
            second = await registry.get("fly-002")
            first_again = await registry.get("fly-001")
            assert isinstance(first, FakeRuntime)
            assert isinstance(second, FakeRuntime)
            assert isinstance(first_again, FakeRuntime)
            return first, second, first_again

        first, second, first_again = asyncio.run(load_population())
        assert first is first_again
        assert first is not second
        assert first.seed != second.seed

        first.step({"visual": [{"bodyId": 11, "rateHz": 150.0}]})
        second.step({"visual": [{"bodyId": 22, "rateHz": 0.0}]})
        assert first.spike_history != second.spike_history
        assert first.motor_output != second.motor_output

    def test_two_brain_copies_have_separate_brian2_spike_state(self) -> None:
        neurons = normalize_neurons(
            pd.DataFrame(
                {
                    "bodyId": [1, 2],
                    "type": ["Sensory", "Downstream"],
                    "class": ["visual", "descending"],
                    "predicted_nt": ["acetylcholine", "acetylcholine"],
                }
            )
        )
        edges = normalize_edges(
            pd.DataFrame({"bodyId_pre": [1], "bodyId_post": [2], "weight": [100]})
        )
        first = BrainSimulation.from_tables(neurons, edges, seed=101)
        second = BrainSimulation.from_tables(neurons, edges, seed=202)

        first.set_external_rates({1: 150.0})
        second.set_external_rates({1: 0.0})
        _, first_counts = first.advance(100.0)
        _, second_counts = second.advance(100.0)

        assert first is not second
        assert first.seed != second.seed
        assert first_counts != second_counts
        assert first_counts.get(2, 0) > 0
        assert second_counts.get(2, 0) == 0
