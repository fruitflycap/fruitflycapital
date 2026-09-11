"""Stimulate the documented MaleCNS DNge104 type and plot propagation.

Requires the official annotation, neurotransmitter (recommended), and full
connectivity Feather files in data/raw. The demo deliberately uses the default
conservative transmitter-sign policy: ambiguous source predictions are not
turned into excitatory synapses.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt

from malecns.annotations import outgoing_edges, query_neurons
from malecns.brain.parameters import LIFParameters
from malecns.brain.simulation import BrainSimulation
from malecns.loader import load_malecns_tables


def main() -> int:
    data_dir = Path("data/raw")
    neurons, edges = load_malecns_tables(data_dir)
    selected = query_neurons(neurons, type="DNge104")
    if selected.empty:
        raise RuntimeError("No annotated MaleCNS neuron with type DNge104 was found")
    body_id = int(selected.iloc[0]["body_id"])
    cell_type = selected.iloc[0].get("type")
    print(f"stimulated body_id={body_id} type={cell_type!r}")

    brain = BrainSimulation.from_tables(
        neurons,
        edges,
        parameters=LIFParameters.load("data/parameters/shiu-male-cns-v1.json"),
        seed=7,
        unknown_sign="exclude",
    )
    brain.stimulate([body_id], frequency_hz=150.0)
    result = brain.run(duration_ms=500.0)

    downstream_ids = set(outgoing_edges(edges, [body_id])["target_body_id"].tolist())
    rates = result.firing_rates[result.firing_rates["body_id"].isin(downstream_ids)]
    rates = rates.sort_values("firing_rate_hz", ascending=False).head(20)
    print("top downstream firing neurons:")
    print(rates[["body_id", "type", "firing_rate_hz"]].to_string(index=False))
    print(f"recorded spikes={len(result.spikes)}")

    output = Path("results/connectome_propagation_raster.png")
    output.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(11, 6))
    plt.scatter(result.spikes["time_ms"], result.spikes["body_id"], s=2)
    plt.xlabel("time (ms)")
    plt.ylabel("MaleCNS body ID")
    plt.title(f"MaleCNS v1.0 propagation from {cell_type} body {body_id}")
    plt.tight_layout()
    plt.savefig(output, dpi=160)
    print(f"raster={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
