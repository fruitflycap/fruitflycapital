"""Reference CPU simulation around the MaleCNS graph."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
from typing import Any

import numpy as np
import pandas as pd

from ..loader import load_malecns_tables
from ..schema import EdgeTable, NeuronTable
from .connectivity import ConnectivityMatrix
from .lif import build_neuron_group
from .parameters import LIFParameters


@dataclass(frozen=True)
class NeuronState:
    body_id: int
    index: int
    type: str | None = None
    class_: str | None = None
    side: str | None = None


@dataclass(frozen=True)
class Stimulus:
    body_ids: tuple[int, ...]
    frequency_hz: float


@dataclass
class SimulationResult:
    spikes: pd.DataFrame
    firing_rates: pd.DataFrame


class SpikeRecorder:
    """Convert Brian2 spike monitor output back to MaleCNS body IDs."""

    def record(self, monitor: Any, neuron_frame: Any, duration_ms: float) -> SimulationResult:
        indices = np.asarray(monitor.i, dtype=int)
        times_ms = np.asarray(monitor.t / self._ms, dtype=float)
        body_ids = neuron_frame["body_id"].to_numpy(dtype=np.int64)
        spike_data = {
            "time_ms": times_ms,
            "neuron_index": indices,
            "body_id": body_ids[indices] if len(indices) else np.array([], dtype=np.int64),
        }
        for column in ("type", "class", "side"):
            if column in neuron_frame.columns:
                values = neuron_frame[column].astype("string").to_numpy()
                spike_data[column] = values[indices] if len(indices) else np.array([], dtype=object)
        spikes = pd.DataFrame(spike_data)
        counts = np.bincount(indices, minlength=len(neuron_frame))
        rates = pd.DataFrame(
            {
                "body_id": body_ids,
                "spike_count": counts,
                "firing_rate_hz": counts * 1000.0 / float(duration_ms),
            }
        )
        for column in ("type", "class", "side"):
            if column in neuron_frame.columns:
                rates[column] = neuron_frame[column].to_numpy()
        return SimulationResult(spikes=spikes, firing_rates=rates)

    @property
    def _ms(self):
        from brian2 import ms
        return ms


class BrainSimulation:
    """A single MaleCNS copy with no external fly-to-fly neural pathway."""

    def __init__(
        self,
        neurons: NeuronTable | Any,
        edges: EdgeTable | Any,
        *,
        parameters: LIFParameters | None = None,
        seed: int = 0,
        unknown_sign: str = "exclude",
        transmitter_column: str = "predicted_neurotransmitter",
    ):
        self.neuron_table = neurons
        self.edge_table = edges
        self.parameters = parameters or LIFParameters()
        self.seed = int(seed)
        self.connectivity = ConnectivityMatrix.from_tables(
            neurons,
            edges,
            synapse_scale_mV=self.parameters.synapse_scale_mV,
            unknown_sign=unknown_sign,
            transmitter_column=transmitter_column,
        )
        self._neuron_frame = getattr(neurons, "dataframe", neurons)
        self._stimuli: list[Stimulus] = []
        self._silenced: set[int] = set()
        self._external_group: Any | None = None
        self._external_synapses: Any | None = None
        self._external_body_ids = self._neuron_frame["body_id"].astype("int64").to_numpy()
        self._body_to_index = {
            int(body_id): index for index, body_id in enumerate(self._external_body_ids)
        }
        self._external_refractory_cleared: set[int] = set()
        self._network, self.neurons, self.synapses, self.spike_monitor = self._build_network()
        self._recorder = SpikeRecorder()

    @classmethod
    def from_malecns(cls, data_dir: str = "data/raw", **kwargs) -> "BrainSimulation":
        neurons, edges = load_malecns_tables(data_dir)
        return cls(neurons, edges, **kwargs)

    @classmethod
    def from_tables(cls, neurons: Any, edges: Any, **kwargs) -> "BrainSimulation":
        return cls(neurons, edges, **kwargs)

    def _build_network(self):
        from brian2 import Network, Synapses, defaultclock, mV, ms

        defaultclock.dt = self.parameters.dt_ms * ms
        group = build_neuron_group(len(self._neuron_frame), self.parameters)
        matrix = self.connectivity
        synapses = Synapses(
            group,
            group,
            model="w : volt",
            on_pre="g_post += w",
            delay=self.parameters.delay_ms * ms,
            name="malecns_synapses",
        )
        if len(matrix.included_edges):
            synapses.connect(i=matrix.source_indices, j=matrix.target_indices)
            synapses.w = matrix.signed_weights_mV * mV
        monitor = __import__("brian2", fromlist=["SpikeMonitor"]).SpikeMonitor(group)
        return Network(group, synapses, monitor), group, synapses, monitor

    def _indices(self, body_ids: list[int] | tuple[int, ...]) -> np.ndarray:
        requested = [int(body_id) for body_id in body_ids]
        missing = [body_id for body_id in requested if body_id not in self._body_to_index]
        if missing:
            raise KeyError(f"Unknown MaleCNS body IDs: {missing[:5]}")
        return np.asarray([self._body_to_index[body_id] for body_id in requested], dtype=int)

    def stimulate(self, body_ids: list[int] | tuple[int, ...], frequency_hz: float) -> Stimulus:
        """Add Shiu-style PoissonInput stimulation to selected neurons."""
        from brian2 import Hz, PoissonInput, mV, ms

        if frequency_hz < 0:
            raise ValueError("frequency_hz must be non-negative")
        body_ids_tuple = tuple(int(body_id) for body_id in body_ids)
        indices = self._indices(body_ids_tuple)
        for index in indices:
            poisson = PoissonInput(
                target=self.neurons[int(index)],
                target_var="v",
                N=1,
                rate=float(frequency_hz) * Hz,
                weight=self.parameters.synapse_scale_mV * self.parameters.poisson_scale * mV,
            )
            self._network.add(poisson)
            # Faithful to the published helper: stimulated targets have no
            # refractory period while externally driven.
            self.neurons[int(index)].rfc = 0 * ms
        stimulus = Stimulus(body_ids_tuple, float(frequency_hz))
        self._stimuli.append(stimulus)
        return stimulus

    def set_external_rates(self, rates_hz: Mapping[int, float]) -> None:
        """Set persistent Poisson drive for a live sensory frame.

        Brian2's ``PoissonInput`` compiles its rate expression at construction
        and exposes it read-only. For a live frame stream, use one reusable
        ``PoissonGroup`` with one input neuron per MaleCNS neuron and a
        one-to-one synapse. Updating the group's rate vector is equivalent to
        the published one-input-per-target Poisson drive, without creating
        new input objects on every browser frame.
        """
        from brian2 import Hz, PoissonGroup, Synapses, mV, ms

        requested = {int(body_id): max(0.0, float(rate)) for body_id, rate in rates_hz.items()}
        unknown = sorted(set(requested) - set(self._external_body_ids.tolist()))
        if unknown:
            raise KeyError(f"Unknown MaleCNS body IDs: {unknown[:5]}")
        if self._external_group is None:
            self._external_group = PoissonGroup(
                len(self._neuron_frame),
                rates=0 * Hz,
                name="malecns_external_poisson",
            )
            self._external_synapses = Synapses(
                self._external_group,
                self.neurons,
                model="w : volt",
                on_pre="v_post += w",
                delay=0 * ms,
                name="malecns_external_synapses",
            )
            indices = np.arange(len(self._neuron_frame), dtype=np.int64)
            self._external_synapses.connect(i=indices, j=indices)
            self._external_synapses.w = (
                self.parameters.synapse_scale_mV * self.parameters.poisson_scale * mV
            )
            self._network.add(self._external_group, self._external_synapses)

        rates = np.zeros(len(self._neuron_frame), dtype=float)
        for body_id, rate_hz in requested.items():
            index = self._body_to_index[body_id]
            rates[index] = rate_hz
            if rate_hz > 0 and body_id not in self._external_refractory_cleared:
                # This matches the published helper's externally driven
                # target behavior; it is not a new refractory assumption.
                self.neurons[index].rfc = 0 * ms
                self._external_refractory_cleared.add(body_id)
        self._external_group.rates = rates * Hz

    def advance(self, duration_ms: float) -> tuple[dict[int, float], dict[int, int]]:
        """Advance one live window and return only spikes from that window."""
        if duration_ms <= 0:
            raise ValueError("duration_ms must be positive")
        from brian2 import ms

        start = len(self.spike_monitor.i)
        self._network.run(float(duration_ms) * ms)
        indices = np.asarray(self.spike_monitor.i, dtype=int)[start:]
        counts = np.bincount(indices, minlength=len(self._neuron_frame))
        body_ids = self._neuron_frame["body_id"].to_numpy(dtype=np.int64)
        scale = 1000.0 / float(duration_ms)
        spike_counts = {int(body_ids[index]): int(count) for index, count in enumerate(counts) if count}
        spike_rates = {body_id: count * scale for body_id, count in spike_counts.items()}
        return spike_rates, spike_counts

    def silence(self, body_ids: list[int] | tuple[int, ...]) -> None:
        """Set all outgoing synaptic weights from IDs to zero, as Shiu did."""
        from brian2 import mV

        indices = self._indices(tuple(body_ids))
        for index in indices:
            positions = np.flatnonzero(self.connectivity.source_indices == index)
            if len(positions):
                self.synapses.w[positions] = 0 * mV
            self._silenced.add(int(self._neuron_frame.iloc[index]["body_id"]))

    def run(self, duration_ms: float) -> SimulationResult:
        if duration_ms <= 0:
            raise ValueError("duration_ms must be positive")
        from brian2 import ms, seed

        seed(self.seed)
        self._network.run(float(duration_ms) * ms)
        return self._recorder.record(self.spike_monitor, self._neuron_frame, float(duration_ms))
