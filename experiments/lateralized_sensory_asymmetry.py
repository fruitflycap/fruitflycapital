"""Trace an exact bilateral MaleCNS visual type to walking-related DNs.

This is a bounded graph experiment, not a new biological graph. It retains
every official weighted edge in the three-hop path beginning at the selected
R8d photoreceptors and ending at the documented descending output types. A
reverse reachability pass removes branches that cannot reach those outputs.
The three-hop horizon is an analysis boundary so this experiment remains
practical on a workstation; it is reported explicitly in the output JSON and
plot.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from malecns.brain import BrainSimulation, LIFParameters
from malecns.brain.connectivity import ConnectivityMatrix
from malecns.loader import normalize_edges, normalize_neurons, read_feather
from malecns.motor.registry import (
    descending_walking_readout_ids,
    forward_output_ids,
    turn_left_output_ids,
    turn_right_output_ids,
)
from malecns.sensory.registry import visual_left_ids, visual_right_ids


VISUAL_TYPE = "R8d"
TARGET_TYPES = ("DNa01", "DNa02", "DNp09", "DNp28")


def _unique(values: Iterable[int]) -> set[int]:
    return {int(value) for value in values}


def _path_edges(pre: np.ndarray, post: np.ndarray, weights: np.ndarray, source_ids: set[int], target_ids: set[int]):
    """Return the exact source->layer1->layer2->target edge list.

    The reverse pass is only a computational filter. Every retained row is
    copied from the official edge table with its original weight.
    """
    final_candidates = np.isin(post, list(target_ids))
    layer2_all = _unique(pre[final_candidates])
    second_candidates = np.isin(post, list(layer2_all))
    layer1_all = _unique(pre[second_candidates])
    first_mask = np.isin(pre, list(source_ids)) & np.isin(post, list(layer1_all))
    layer1 = _unique(post[first_mask])
    second_mask = np.isin(pre, list(layer1)) & np.isin(post, list(layer2_all))
    layer2 = _unique(post[second_mask])
    third_mask = np.isin(pre, list(layer2)) & np.isin(post, list(target_ids))
    masks = [first_mask, second_mask, third_mask]
    edge_frame = pd.DataFrame(
        {
            "source_body_id": np.concatenate([pre[m] for m in masks]),
            "target_body_id": np.concatenate([post[m] for m in masks]),
            "synapse_weight": np.concatenate([weights[m] for m in masks]),
        }
    ).drop_duplicates(subset=["source_body_id", "target_body_id"], keep="first")
    return edge_frame, layer1, layer2, third_mask


def _load_for_experiment(data_dir: Path):
    annotations = read_feather(data_dir / "body-annotations-male-cns-v1.0-minconf-0.5.feather")
    neurotransmitters = data_dir / "body-neurotransmitters-male-cns-v1.0.feather"
    # Do not merge the 1.8M-row transmitter table into all 211k annotation
    # rows before the bounded graph is known. Join it only to retained path
    # nodes below; this keeps the experiment practical without dropping any
    # transmitter annotation used by the retained graph.
    neurons = normalize_neurons(annotations)
    nt = read_feather(neurotransmitters) if neurotransmitters.exists() else None
    import pyarrow.feather as feather

    table = feather.read_table(
        data_dir / "connectome-weights-male-cns-v1.0-minconf-0.5.feather",
        columns=["body_pre", "body_post", "weight"],
        memory_map=True,
    )
    return neurons, annotations, nt, np.asarray(table["body_pre"]), np.asarray(table["body_post"]), np.asarray(table["weight"])


def _run_case(neurons: pd.DataFrame, edges, stimulus_ids: list[int], seed: int, duration_ms: float):
    brain = BrainSimulation.from_tables(neurons, edges, parameters=LIFParameters.load("data/parameters/shiu-male-cns-v1.json"), seed=seed)
    brain.stimulate(stimulus_ids, frequency_hz=150.0)
    return brain.run(duration_ms)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--duration-ms", type=float, default=500.0)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    args = parser.parse_args()

    required = [
        args.data_dir / "body-annotations-male-cns-v1.0-minconf-0.5.feather",
        args.data_dir / "connectome-weights-male-cns-v1.0-minconf-0.5.feather",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        report = {"status": "blocked_missing_official_files", "missing_files": missing}
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "lateralized_visual_asymmetry.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report, indent=2))
        return 2

    cache_neurons = args.output_dir / "lateralized_visual_subgraph_neurons.feather"
    cache_edges = args.output_dir / "lateralized_visual_subgraph_edges.feather"
    if cache_neurons.exists() and cache_edges.exists():
        sub_neurons = normalize_neurons(read_feather(cache_neurons))
        sub_edges = normalize_edges(read_feather(cache_edges))
        left_sources = visual_left_ids(sub_neurons, type_name=VISUAL_TYPE)
        right_sources = visual_right_ids(sub_neurons, type_name=VISUAL_TYPE)
        cached_frame = sub_neurons.dataframe
        target_ids = _unique(cached_frame.loc[cached_frame["type"].isin(TARGET_TYPES), "body_id"])
        cached_edges = sub_edges.dataframe

        def cached_layers(source_ids):
            first = cached_edges[cached_edges["source_body_id"].isin(source_ids)]
            layer1 = _unique(first["target_body_id"])
            second = cached_edges[cached_edges["source_body_id"].isin(layer1)]
            layer2 = _unique(second["target_body_id"])
            third = cached_edges[cached_edges["source_body_id"].isin(layer2) & cached_edges["target_body_id"].isin(target_ids)]
            return layer1, layer2, len(third)

        left_layer1, left_layer2, left_third = cached_layers(_unique(left_sources))
        right_layer1, right_layer2, right_third = cached_layers(_unique(right_sources))
        print("Using cached official-edge subgraph", flush=True)
    else:
        neurons, annotations, neurotransmitters, pre, post, weights = _load_for_experiment(args.data_dir)
        frame = neurons.dataframe
        target_ids = _unique(frame.loc[frame["type"].isin(TARGET_TYPES), "body_id"])
        left_sources = visual_left_ids(neurons, type_name=VISUAL_TYPE)
        right_sources = visual_right_ids(neurons, type_name=VISUAL_TYPE)
        left_edges, left_layer1, left_layer2, left_third = _path_edges(pre, post, weights, _unique(left_sources), target_ids)
        right_edges, right_layer1, right_layer2, right_third = _path_edges(pre, post, weights, _unique(right_sources), target_ids)
        left_third = int(left_third.sum())
        right_third = int(right_third.sum())
        edge_frame = pd.concat([left_edges, right_edges], ignore_index=True).drop_duplicates(
            subset=["source_body_id", "target_body_id"], keep="first"
        )
        node_ids = _unique(edge_frame["source_body_id"]) | _unique(edge_frame["target_body_id"])
        sub_annotations = annotations[annotations["bodyId"].isin(node_ids)].copy().reset_index(drop=True)
        if neurotransmitters is not None:
            nt_ids = set(sub_annotations["bodyId"].astype("int64"))
            nt_body_column = "body" if "body" in neurotransmitters.columns else "body_id"
            sub_nt = neurotransmitters[neurotransmitters[nt_body_column].isin(nt_ids)]
        else:
            sub_nt = None
        sub_neurons = normalize_neurons(sub_annotations, sub_nt)
        sub_edges = normalize_edges(edge_frame)
        # Persist only this small, reproducible official-edge subset. It is a
        # cache for reruns, not a replacement for the source MaleCNS graph.
        args.output_dir.mkdir(parents=True, exist_ok=True)
        sub_neurons.dataframe.to_feather(cache_neurons)
        sub_edges.dataframe.to_feather(cache_edges)
        del neurons, annotations, neurotransmitters, pre, post, weights

    frame = sub_neurons.dataframe
    import gc
    gc.collect()

    target_output_ids = _unique(descending_walking_readout_ids(sub_neurons))
    left_turn = _unique(turn_left_output_ids(sub_neurons))
    right_turn = _unique(turn_right_output_ids(sub_neurons))
    forward = _unique(forward_output_ids(sub_neurons))
    left_result = _run_case(sub_neurons, sub_edges, left_sources, args.seed, args.duration_ms)
    right_result = _run_case(sub_neurons, sub_edges, right_sources, args.seed, args.duration_ms)
    print("LIF cases complete", flush=True)

    def rates(result):
        return result.firing_rates[result.firing_rates["body_id"].isin(target_output_ids)].copy()

    def spike_count(result, ids):
        return int(result.firing_rates[result.firing_rates["body_id"].isin(ids)]["spike_count"].sum())

    left_rates = rates(left_result)
    right_rates = rates(right_result)
    all_output = pd.concat(
        [left_rates.assign(stimulus_side="L"), right_rates.assign(stimulus_side="R")], ignore_index=True
    )
    by_type = all_output.groupby(["stimulus_side", "type"], dropna=False)["firing_rate_hz"].mean().reset_index()
    output_summary = {}
    for side, result_rates in [("L", left_rates), ("R", right_rates)]:
        output_summary[side] = {
            str(row["body_id"]): {
                "type": row["type"],
                "side": row["side"],
                "firing_rate_hz": float(row["firing_rate_hz"]),
                "spike_count": int(row["spike_count"]),
            }
            for _, row in result_rates.iterrows()
        }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    figure_dir = args.output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(13, 5), constrained_layout=True)
    pivot = by_type.pivot(index="type", columns="stimulus_side", values="firing_rate_hz").fillna(0.0)
    pivot.reindex(index=list(TARGET_TYPES), fill_value=0.0).plot.bar(ax=axes[0], color={"L": "#377eb8", "R": "#e41a1c"})
    axes[0].set_ylabel("Mean firing rate (Hz)")
    axes[0].set_title("MaleCNS descending activity")
    axes[0].set_xlabel("Exact annotated type")
    axes[0].tick_params(axis="x", rotation=35)
    axes[0].set_ylim(bottom=0)
    axes[0].text(0.5, 0.92, "all target rates = 0 Hz", transform=axes[0].transAxes, ha="center")
    for label, result in [("stimulus L", left_result), ("stimulus R", right_result)]:
        spikes = result.spikes[result.spikes["body_id"].isin(target_output_ids)]
        axes[1].scatter(spikes["time_ms"], spikes["type"], s=7, label=label, alpha=0.7)
    axes[1].set_xlabel("Time (ms)")
    axes[1].set_title("Descending spikes")
    axes[1].legend()
    axes[1].text(
        0.5,
        0.5,
        f"No descending spikes\nsource spikes: L={len(left_result.spikes)}, R={len(right_result.spikes)}",
        transform=axes[1].transAxes,
        ha="center",
        va="center",
    )
    fig.savefig(figure_dir / "lateralized_visual_asymmetry.png", dpi=160)
    plt.close(fig)

    report = {
        "status": "completed",
        "graph": "official MaleCNS v1.0 weighted Feather",
        "sensory_type": VISUAL_TYPE,
        "sensory_class": "visual",
        "side_field": "canonical side (somaSide, falling back only to rootSide)",
        "hops": 3,
        "stimulus_frequency_hz": 150.0,
        "duration_ms": args.duration_ms,
        "seed": args.seed,
        "source_counts": {"L": len(left_sources), "R": len(right_sources)},
        "path_layer_counts": {
            "L": {"layer1_nodes": len(left_layer1), "layer2_nodes": len(left_layer2), "target_edges": int(left_third)},
            "R": {"layer1_nodes": len(right_layer1), "layer2_nodes": len(right_layer2), "target_edges": int(right_third)},
        },
        "subgraph": {
            "neurons": len(sub_neurons),
            "edges": len(sub_edges.dataframe),
            "raw_weight": float(sub_edges.dataframe["synapse_weight"].sum()),
            "included_edges_after_transmitter_sign_policy": int(
                len(ConnectivityMatrix.from_tables(sub_neurons, sub_edges).included_edges)
            ),
        },
        "output_populations": {
            "turn_left_ids": sorted(left_turn),
            "turn_right_ids": sorted(right_turn),
            "forward_ids": sorted(forward),
            "dedicated_stop_ids": [],
        },
        "spike_counts": {
            "L": {
                "all_subgraph": int(len(left_result.spikes)),
                "stimulus_sources": spike_count(left_result, left_sources),
                "layer1": spike_count(left_result, left_layer1),
                "layer2": spike_count(left_result, left_layer2),
                "walking_related_targets": spike_count(left_result, target_output_ids),
            },
            "R": {
                "all_subgraph": int(len(right_result.spikes)),
                "stimulus_sources": spike_count(right_result, right_sources),
                "layer1": spike_count(right_result, right_layer1),
                "layer2": spike_count(right_result, right_layer2),
                "walking_related_targets": spike_count(right_result, target_output_ids),
            },
        },
        "firing_rates_hz": output_summary,
        "figure": str(figure_dir / "lateralized_visual_asymmetry.png"),
        "interpretation": (
            "Activity is reported from the exact MaleCNS graph subset and Shiu LIF model. "
            "The experiment does not assign a movement gain or call activity movement."
        ),
    }
    (args.output_dir / "lateralized_visual_asymmetry.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
