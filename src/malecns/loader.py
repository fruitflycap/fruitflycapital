"""Load and normalize official MaleCNS v1.0 Feather tables."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .schema import EdgeTable, NeuronTable

OFFICIAL_FILENAMES = {
    "annotations": "body-annotations-male-cns-v1.0-minconf-0.5.feather",
    "neurotransmitters": "body-neurotransmitters-male-cns-v1.0.feather",
    "stats": "body-stats-male-cns-v1.0-minconf-0.5.feather",
    "connectivity": "connectome-weights-male-cns-v1.0-minconf-0.5.feather",
}

# These aliases cover the names documented by neuPrint and common spellings
# found in exported Arrow tables. No values are synthesized when no alias is
# present; the canonical field remains nullable.
NEURON_ALIASES = {
    "body_id": ("body_id", "bodyId", "body", "body_pre"),
    "type": ("type", "cell_type", "cellType", "instance"),
    "class": ("class", "cell_class", "cellClass"),
    "subclass": ("subclass", "sub_class", "cell_subclass", "cellSubclass"),
    "superclass": ("superclass", "super_class", "cell_superclass", "cellSuperclass"),
    # MaleCNS v1.0 provides both somaSide and rootSide. somaSide is the
    # closest direct match to the requested canonical side field; rootSide is
    # retained as an additional source column.
    "side": ("side", "somaSide", "rootSide", "hemisphere"),
    "nerve": ("nerve", "nerve_name"),
    "entry_nerve": ("entry_nerve", "entryNerve"),
    "exit_nerve": ("exit_nerve", "exitNerve"),
    "hemilineage": ("hemilineage", "hemilineage_name"),
    "itolee_hemilineage": ("itolee_hemilineage", "itoleeHl"),
    "truman_hemilineage": ("truman_hemilineage", "trumanHl"),
    "status": ("status", "statusLabel", "status_label"),
    "predicted_neurotransmitter": (
        "predicted_neurotransmitter", "predictedNt", "predicted_nt", "nt",
        "neurotransmitter", "primary_neurotransmitter",
    ),
    "neurotransmitter_confidence": (
        "neurotransmitter_confidence", "nt_confidence", "predictedNtConfidence",
        "predicted_nt_confidence", "confidence",
    ),
    "pre_count": ("pre_count", "pre", "pre_synapses", "presynaptic_count"),
    "post_count": ("post_count", "post", "post_synapses", "postsynaptic_count"),
}

EDGE_ALIASES = {
    "source_body_id": ("source_body_id", "body_pre", "bodyId_pre", "pre", "source"),
    "target_body_id": ("target_body_id", "body_post", "bodyId_post", "post", "target"),
    "synapse_weight": ("synapse_weight", "weight", "connectivity", "synapse_count"),
}


class DependencyError(ImportError):
    """Raised when a local Feather operation lacks pandas/pyarrow."""


class SchemaError(ValueError):
    """Raised when a source table cannot be mapped to its required fields."""


def read_feather(path: str | Path) -> Any:
    """Read a Feather file through pandas, with a focused dependency error."""
    try:
        import pandas as pd
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise DependencyError("Install pandas and pyarrow to read Feather files") from exc
    try:
        return pd.read_feather(path)
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise DependencyError("Install pyarrow to read Feather files") from exc


def _find_column(frame: Any, aliases: tuple[str, ...]) -> str | None:
    by_lower = {str(column).lower(): column for column in frame.columns}
    for alias in aliases:
        if alias in frame.columns:
            return alias
        if alias.lower() in by_lower:
            return by_lower[alias.lower()]
    return None


def _copy_canonical(frame: Any, aliases: Mapping[str, tuple[str, ...]], required: tuple[str, ...]) -> Any:
    """Copy source columns to canonical names and retain every extra column."""
    result = frame.copy()
    source_columns = set(frame.columns)
    for canonical, candidates in aliases.items():
        if canonical in result.columns:
            continue
        source = _find_column(frame, candidates)
        if source is not None:
            result[canonical] = frame[source]
    missing = [name for name in required if name not in result.columns]
    if missing:
        raise SchemaError(f"Could not map required fields {missing}; source columns: {list(source_columns)}")
    return result


def _coerce_ids(frame: Any, columns: tuple[str, ...]) -> Any:
    import pandas as pd
    for column in columns:
        numeric = pd.to_numeric(frame[column], errors="coerce")
        if numeric.isna().any():
            bad = frame.loc[numeric.isna(), column].head(3).tolist()
            raise SchemaError(f"Non-numeric body ID in {column}: {bad}")
        frame[column] = numeric.astype("int64")
    return frame


def _merge_optional(base: Any, extra: Any, suffix: str) -> Any:
    if extra is None:
        return base
    extra = extra.copy()
    body_column = _find_column(extra, NEURON_ALIASES["body_id"])
    if body_column is None:
        raise SchemaError(f"{suffix} table has no body ID column")
    extra["body_id"] = extra[body_column]
    extra = _coerce_ids(extra, ("body_id",))
    if extra["body_id"].duplicated().any():
        raise SchemaError(f"{suffix} table contains duplicate body IDs")
    overlap = [c for c in extra.columns if c != "body_id" and c in base.columns]
    if overlap:
        extra = extra.drop(columns=overlap)
    return base.merge(extra, on="body_id", how="left", validate="one_to_one")


def normalize_neurons(
    annotations: Any,
    neurotransmitters: Any | None = None,
    stats: Any | None = None,
) -> NeuronTable:
    """Build the unified Neuron table from official source tables.

    Annotation and neurotransmitter tables are joined by the official body ID.
    Synapse counts are taken from body stats when that file is supplied; they
    are never estimated from edge rows.
    """
    frame = _copy_canonical(annotations, NEURON_ALIASES, ("body_id",))
    frame = _coerce_ids(frame, ("body_id",))
    if frame["body_id"].duplicated().any():
        raise SchemaError("Neuron annotations contain duplicate body IDs")

    if neurotransmitters is not None:
        nt = _copy_canonical(neurotransmitters, NEURON_ALIASES, ("body_id",))
        frame = _merge_optional(frame, nt, "neurotransmitters")
    if stats is not None:
        st = _copy_canonical(stats, NEURON_ALIASES, ("body_id",))
        frame = _merge_optional(frame, st, "stats")

    for canonical, candidates in NEURON_ALIASES.items():
        if canonical not in frame.columns:
            frame[canonical] = None

    # MaleCNS uses somaSide for many central neurons but leaves it null for
    # many sensory neurons. rootSide is the source hemisphere annotation for
    # those cells. Coalesce only these source fields; never infer side from a
    # type or instance string.
    if "side" in frame.columns and "rootSide" in frame.columns:
        frame["side"] = frame["side"].where(frame["side"].notna(), frame["rootSide"])

    # Keep canonical columns first, then every source-specific field.
    extras = [c for c in frame.columns if c not in NEURON_ALIASES]
    frame = frame[list(NEURON_ALIASES) + extras]
    return NeuronTable(frame)


def normalize_edges(connectivity: Any) -> EdgeTable:
    """Build the unified Edge table from the full weighted connection graph."""
    frame = _copy_canonical(connectivity, EDGE_ALIASES, tuple(EDGE_ALIASES))
    frame = _coerce_ids(frame, ("source_body_id", "target_body_id"))
    import pandas as pd
    frame["synapse_weight"] = pd.to_numeric(frame["synapse_weight"], errors="coerce")
    if frame["synapse_weight"].isna().any():
        raise SchemaError("Connectivity contains non-numeric synapse weights")
    if (frame["synapse_weight"] < 0).any():
        raise SchemaError("Connectivity contains negative synapse weights")
    extras = [c for c in frame.columns if c not in EDGE_ALIASES]
    frame = frame[list(EDGE_ALIASES) + extras]
    return EdgeTable(frame)


def _path_for(root: Path, key: str) -> Path | None:
    exact = root / OFFICIAL_FILENAMES[key]
    if exact.exists():
        return exact
    # Allow a locally renamed version only when its name still clearly names
    # the relevant official table; do not select arbitrary Feather files.
    patterns = {
        "annotations": "body-annotations-*.feather",
        "neurotransmitters": "body-neurotransmitters-*.feather",
        "stats": "body-stats-*.feather",
        "connectivity": "connectome-weights-*.feather",
    }
    matches = sorted(root.glob(patterns[key]))
    return matches[0] if len(matches) == 1 else None


def load_malecns_tables(data_dir: str | Path = "data/raw") -> tuple[NeuronTable, EdgeTable]:
    """Load the available official local Feather files.

    Annotations and connectivity are required. Neurotransmitter and stats
    files are optional and are joined when present. Missing optional files are
    reported by the CLI and represented as nullable canonical fields.
    """
    root = Path(data_dir)
    annotation_path = _path_for(root, "annotations")
    connectivity_path = _path_for(root, "connectivity")
    if annotation_path is None:
        raise FileNotFoundError(f"Official MaleCNS annotation Feather not found in {root}")
    if connectivity_path is None:
        raise FileNotFoundError(f"Official MaleCNS connectivity Feather not found in {root}")
    nt_path = _path_for(root, "neurotransmitters")
    stats_path = _path_for(root, "stats")
    neurons = normalize_neurons(
        read_feather(annotation_path),
        read_feather(nt_path) if nt_path else None,
        read_feather(stats_path) if stats_path else None,
    )
    edges = normalize_edges(read_feather(connectivity_path))
    return neurons, edges
