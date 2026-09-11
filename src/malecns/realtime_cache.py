"""Build the explicit official-data subgraph used by the live Brian2 adapter.

The full MaleCNS v1.0 weighted graph is the source of truth, but stepping all
211k annotated neurons and 151M weighted edges at browser cadence is not a
reasonable first interactive reference.  This builder retains the exact
weighted paths from the checked-in sensory populations to the annotated flight
    readout populations within a documented hop boundary.

The connectivity Feather is scanned in batches.  No edge is reweighted,
normalized, synthesized, or connected across fly copies.
"""

from __future__ import annotations

import argparse
import csv
import gc
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .loader import normalize_edges, normalize_neurons, read_feather
from .motor.flight_registry import flight_population_ids


ANNOTATIONS = "body-annotations-male-cns-v1.0-minconf-0.5.feather"
NEUROTRANSMITTERS = "body-neurotransmitters-male-cns-v1.0.feather"
CONNECTIVITY = "connectome-weights-male-cns-v1.0-minconf-0.5.feather"
MAPPING = Path("data/mappings/malecns_sensory_motor_ids.csv")


def _unique(values: Iterable[Any]) -> set[int]:
    return {int(value) for value in values}


def _mapping_source_ids(path: Path) -> dict[str, list[int]]:
    """Load exact sensory IDs from the generated official-data inventory."""
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    populations = {
        "visual_R8d": ["visual_R8d"],
        "olfactory_ORN_DA1": ["olfactory_ORN_DA1"],
        "mechanosensory_auditory_JO-B1_b": ["mechanosensory_auditory_JO-B1_b"],
    }
    result: dict[str, list[int]] = {}
    for key, names in populations.items():
        result[key] = sorted({int(row["bodyId"]) for row in rows if row.get("population") in names})
    return result


def _iter_connectivity(path: Path, batch_size: int = 1_000_000):
    """Yield NumPy arrays for the three official weighted edge columns."""
    try:
        import pyarrow.feather as feather
    except ImportError as exc:  # pragma: no cover - dependency environment
        raise ImportError("Install pyarrow to build the MaleCNS realtime cache") from exc
    table = feather.read_table(path, columns=["body_pre", "body_post", "weight"], memory_map=True)
    for batch in table.to_batches(max_chunksize=batch_size):
        yield (
            np.asarray(batch.column("body_pre")),
            np.asarray(batch.column("body_post")),
            np.asarray(batch.column("weight")),
        )
    del table


def _collect_reverse_layers(
    connectivity_path: Path,
    target_ids: set[int],
    *,
    batch_size: int,
    path_hops: int,
) -> list[set[int]]:
    """Find reverse layers 1..N-1 that can reach the output population."""
    if path_hops < 2:
        raise ValueError("path_hops must be at least 2")
    reverse_layers: list[set[int]] = []
    downstream = set(target_ids)
    for layer_number in range(1, path_hops):
        downstream_array = np.asarray(sorted(downstream), dtype=np.int64)
        upstream: set[int] = set()
        for pre, post, _ in _iter_connectivity(connectivity_path, batch_size):
            mask = np.isin(post, downstream_array)
            upstream.update(int(value) for value in pre[mask])
        reverse_layers.append(upstream)
        print(f"reverse layer {layer_number}: {len(upstream):,} neurons", flush=True)
        downstream = upstream
    return reverse_layers


def _collect_path_edges(
    connectivity_path: Path,
    source_ids: set[int],
    reverse_layers: list[set[int]],
    target_ids: set[int],
    *,
    batch_size: int,
) -> tuple[pd.DataFrame, dict[str, int]]:
    """Copy exact source/reverse-layer/target rows from the official graph."""
    empty_columns = ["source_body_id", "target_body_id", "synapse_weight"]
    current = set(source_ids)
    path_parts: list[pd.DataFrame] = []
    path_counts: dict[str, int] = {}
    # A source reaches reverse layer N-1 first, then N-2, ..., then targets.
    allowed_posts = list(reversed(reverse_layers)) + [set(target_ids)]
    for hop, allowed in enumerate(allowed_posts, start=1):
        current_array = np.asarray(sorted(current), dtype=np.int64)
        allowed_array = np.asarray(sorted(allowed), dtype=np.int64)
        parts: list[pd.DataFrame] = []
        for pre, post, weight in _iter_connectivity(connectivity_path, batch_size):
            selected = np.isin(pre, current_array) & np.isin(post, allowed_array)
            if selected.any():
                parts.append(pd.DataFrame({
                    "source_body_id": pre[selected],
                    "target_body_id": post[selected],
                    "synapse_weight": weight[selected],
                }))
        step_edges = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame(columns=empty_columns)
        current = _unique(step_edges["target_body_id"])
        path_counts[f"hop_{hop}"] = int(len(step_edges))
        path_parts.append(step_edges)
        print(f"forward hop {hop}: {len(current):,} neurons / {len(step_edges):,} edges", flush=True)

    edges = pd.concat(path_parts, ignore_index=True)
    # The source file has one weighted row per body pair. This also makes the
    # path union deterministic if a boundary pair is encountered in two
    # retained path categories.
    edges = edges.drop_duplicates(subset=["source_body_id", "target_body_id"], keep="first")
    return edges, {
        **path_counts,
    }


def _official_path(data_dir: Path, filename: str) -> Path:
    path = data_dir / filename
    if not path.exists():
        raise FileNotFoundError(f"Missing official MaleCNS file: {path}")
    return path


def build_cache(
    data_dir: str | Path = "data/raw",
    output_dir: str | Path = "data/runtime/malecns-realtime-3hop",
    *,
    mapping_path: str | Path = MAPPING,
    batch_size: int = 1_000_000,
    path_hops: int = 3,
) -> dict[str, Any]:
    data_root = Path(data_dir)
    output_root = Path(output_dir)
    output_root.mkdir(parents=True, exist_ok=True)
    annotations_path = _official_path(data_root, ANNOTATIONS)
    nt_path = data_root / NEUROTRANSMITTERS
    connectivity_path = _official_path(data_root, CONNECTIVITY)
    mapping_file = Path(mapping_path)
    if not mapping_file.exists():
        raise FileNotFoundError(f"Missing official sensory inventory mapping: {mapping_file}")

    annotations = read_feather(annotations_path)
    normalized_annotations = normalize_neurons(annotations)
    source_populations = _mapping_source_ids(mapping_file)
    source_ids = _unique(value for values in source_populations.values() for value in values)
    target_populations = flight_population_ids(normalized_annotations)
    target_ids = _unique(value for values in target_populations.values() for value in values)
    if not source_ids:
        raise ValueError("No exact sensory source IDs were found in the mapping inventory")
    if not target_ids:
        raise ValueError("No exact flight output IDs were found in MaleCNS annotations")
    print(f"sources: {len(source_ids):,} exact sensory neurons", flush=True)
    print(f"targets: {len(target_ids):,} exact annotated flight neurons", flush=True)

    reverse_layers = _collect_reverse_layers(connectivity_path, target_ids, path_hops=path_hops, batch_size=batch_size)
    edge_frame, path_counts = _collect_path_edges(
        connectivity_path,
        source_ids,
        reverse_layers,
        target_ids,
        batch_size=batch_size,
    )
    node_ids = source_ids | target_ids | _unique(edge_frame["source_body_id"]) | _unique(edge_frame["target_body_id"])
    node_ids_array = np.asarray(sorted(node_ids), dtype=np.int64)
    sub_annotations = annotations[annotations["bodyId"].isin(node_ids_array)].copy().reset_index(drop=True)

    nt = None
    if nt_path.exists():
        nt = read_feather(nt_path)
        nt_body_column = "body" if "body" in nt.columns else "body_id"
        nt = nt[nt[nt_body_column].isin(node_ids_array)].copy().reset_index(drop=True)
    neurons = normalize_neurons(sub_annotations, nt)
    edges = normalize_edges(edge_frame)
    neurons.dataframe.to_feather(output_root / "neurons.feather")
    edges.dataframe.to_feather(output_root / "edges.feather")

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "graph": "official MaleCNS v1.0 weighted Feather",
        "source_data": {
            "annotations": str(annotations_path),
            "neurotransmitters": str(nt_path) if nt_path.exists() else None,
            "connectivity": str(connectivity_path),
        },
        "cache_is_analysis_boundary": True,
        "path_hops": path_hops,
        "source_populations": source_populations,
        "target_populations": target_populations,
        "source_ids": sorted(source_ids),
        "target_ids": sorted(target_ids),
        "reverse_layer_counts": [len(layer) for layer in reverse_layers],
        "node_count": len(neurons.dataframe),
        "edge_count": len(edges.dataframe),
        "path_edge_counts_before_pair_deduplication": path_counts,
        "raw_weight": float(edges.dataframe["synapse_weight"].sum()),
        "unknown_sign_default": "exclude",
        "batch_size": batch_size,
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ("node_count", "edge_count", "raw_weight")}, indent=2), flush=True)
    del annotations, normalized_annotations, nt, neurons, edges, edge_frame
    gc.collect()
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/runtime/malecns-realtime-3hop"))
    parser.add_argument("--path-hops", type=int, default=3)
    parser.add_argument("--mapping", type=Path, default=MAPPING)
    parser.add_argument("--batch-size", type=int, default=1_000_000)
    args = parser.parse_args()
    build_cache(args.data_dir, args.output_dir, mapping_path=args.mapping, batch_size=args.batch_size, path_hops=args.path_hops)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
