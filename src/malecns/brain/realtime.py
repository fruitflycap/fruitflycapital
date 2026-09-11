"""Persistent Brian2 runtime for the browser's numbered fly swarm.

The runtime consumes only encoded sensory population rates. It runs a cached
three-hop subgraph copied from the official MaleCNS v1.0 weighted graph so a
single 20 Hz browser connection does not attempt to simulate 211k neurons and
151M edges on every frame. The cache manifest records that boundary.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from typing import Any

from .parameters import LIFParameters
from .simulation import BrainSimulation
from .sensory_encoding import MaleCNSSensoryEncoder
from ..loader import normalize_edges, normalize_neurons, read_feather
from ..motor.flight_decoder import FlightDecodeResult, FlightMotorDecoder
from ..motor.flight_registry import flight_population_ids


class RealtimeRuntimeUnavailable(RuntimeError):
    """Raised when the explicit realtime subgraph cache is not available."""


@dataclass(frozen=True)
class LiveBrainStep:
    stimulation: dict[str, Any]
    spike_rates: dict[int, float]
    spike_counts: dict[int, int]
    decoded: FlightDecodeResult


class LiveMaleCNSRuntime:
    """One persistent MaleCNS copy for one browser fly ID."""

    def __init__(
        self,
        cache_dir: str | Path,
        *,
        seed: int = 0,
        window_ms: float = 50.0,
        parameters: LIFParameters | None = None,
        unknown_sign: str = "exclude",
    ) -> None:
        root = Path(cache_dir)
        neurons_path = root / "neurons.feather"
        edges_path = root / "edges.feather"
        manifest_path = root / "manifest.json"
        missing = [str(path) for path in (neurons_path, edges_path, manifest_path) if not path.exists()]
        if missing:
            raise RealtimeRuntimeUnavailable(
                "Missing MaleCNS realtime cache files: " + ", ".join(missing) +
                ". Run `malecns-realtime-cache --data-dir data/raw --output-dir data/runtime/malecns-realtime-3hop --path-hops 3`."
            )
        self.manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.seed = int(seed)
        self.window_ms = float(window_ms)
        if self.window_ms <= 0:
            raise ValueError("window_ms must be positive")
        neurons = normalize_neurons(read_feather(neurons_path))
        edges = normalize_edges(read_feather(edges_path))
        self.brain = BrainSimulation.from_tables(
            neurons,
            edges,
            parameters=parameters or LIFParameters.load("data/parameters/shiu-male-cns-v1.json"),
            seed=seed,
            unknown_sign=unknown_sign,
        )
        self.decoder = FlightMotorDecoder(flight_population_ids(neurons))
        self._seeded = False

    def step(self, stimulation: Mapping[str, Any]) -> LiveBrainStep:
        """Apply one encoded sensory frame and advance one fixed brain window."""
        if not self._seeded:
            # ``advance`` is intentionally separate from ``run`` for streaming,
            # so apply the same explicit RNG control on the first live window.
            from brian2 import seed

            seed(self.seed)
            self._seeded = True
        rates: dict[int, float] = {}
        for channel in ("visual", "olfactory", "mechanosensory"):
            entries = stimulation.get(channel, [])
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, Mapping):
                    continue
                body_id = entry.get("bodyId")
                rate_hz = entry.get("rateHz")
                if isinstance(body_id, Real) and isinstance(rate_hz, Real):
                    # Separate sensory channels should not duplicate an input;
                    # max preserves the strongest encoded drive if they do.
                    rates[int(body_id)] = max(rates.get(int(body_id), 0.0), float(rate_hz))
        self.brain.set_external_rates(rates)
        spike_rates, spike_counts = self.brain.advance(self.window_ms)
        decoded = self.decoder.decode(spike_rates, spike_counts)
        return LiveBrainStep(dict(stimulation), spike_rates, spike_counts, decoded)


def default_realtime_cache() -> Path:
    return Path("data/runtime/malecns-realtime-3hop")


def runtime_from_default_cache(*, seed: int = 0, window_ms: float = 50.0) -> LiveMaleCNSRuntime:
    return LiveMaleCNSRuntime(default_realtime_cache(), seed=seed, window_ms=window_ms)
