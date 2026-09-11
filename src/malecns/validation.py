"""Validation/reporting for the data milestone."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DataReport:
    loaded_neurons: int
    loaded_edges: int
    total_synaptic_weight: float
    neurotransmitter_distribution: dict[str, int]
    left_right_distribution: dict[str, int]
    sensory_neurons: int | None
    descending_neurons: int | None
    motor_neurons: int | None
    category_basis: str
    expected_but_missing_fields: list[str]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _distribution(frame: Any, column: str) -> dict[str, int]:
    if column not in frame.columns:
        return {}
    series = frame[column].dropna().astype(str)
    series = series[series.str.strip() != ""]
    return {str(key): int(value) for key, value in series.value_counts().sort_index().items()}


_MALECNS_SUPERCLASS_CATEGORIES = {
    "sensory": {
        "ol_sensory", "cb_sensory", "vnc_sensory", "sensory_ascending",
        "sensory_descending", "ol_sensory_tbc", "cb_sensory_tbc",
        "vnc_sensory_tbc", "sensory_ascending_tbc",
    },
    "descending": {"descending_neuron", "descending_neuron_tbc", "sensory_descending", "efferent_descending"},
    "motor": {"vnc_motor", "cb_motor"},
}


def _category_count(frame: Any, category: str) -> int | None:
    available = [column for column in ("class", "subclass") if column in frame.columns]
    populated = False
    masks = []
    for column in available:
        series = frame[column].astype("string")
        populated = populated or bool(series.notna().any())
        masks.append(series.str.strip().str.lower().eq(category))
    if "superclass" in frame.columns:
        series = frame["superclass"].astype("string").str.strip().str.lower()
        populated = populated or bool(series.notna().any())
        labels = _MALECNS_SUPERCLASS_CATEGORIES.get(category, set())
        if labels:
            masks.append(series.isin(labels))
    if not populated:
        return None
    if not masks:
        return None
    import pandas as pd
    mask = masks[0]
    for other in masks[1:]:
        mask = mask | other
    if not bool(mask.any()) and category not in {
        str(value).strip().lower()
        for column in ("class", "subclass")
        if column in frame.columns
        for value in frame[column].dropna().tolist()
    }:
        superclass_values = set(frame["superclass"].dropna().astype(str).str.strip().str.lower()) if "superclass" in frame.columns else set()
        if not (superclass_values & _MALECNS_SUPERCLASS_CATEGORIES.get(category, set())):
            return None
    return int(mask.sum())


def make_report(neurons: Any, edges: Any) -> DataReport:
    neuron_frame = getattr(neurons, "dataframe", neurons)
    edge_frame = getattr(edges, "dataframe", edges)
    expected = [
        "body_id", "type", "class", "subclass", "side", "nerve", "hemilineage",
        "status", "predicted_neurotransmitter", "neurotransmitter_confidence",
        "pre_count", "post_count",
    ]
    missing = [column for column in expected if column not in neuron_frame.columns or neuron_frame[column].isna().all()]
    return DataReport(
        loaded_neurons=int(len(neuron_frame)),
        loaded_edges=int(len(edge_frame)),
        total_synaptic_weight=float(edge_frame["synapse_weight"].sum()),
        neurotransmitter_distribution=_distribution(neuron_frame, "predicted_neurotransmitter"),
        left_right_distribution=_distribution(neuron_frame, "side"),
        sensory_neurons=_category_count(neuron_frame, "sensory"),
        descending_neurons=_category_count(neuron_frame, "descending"),
        motor_neurons=_category_count(neuron_frame, "motor"),
        category_basis=(
            "Exact case-insensitive class/subclass equality plus the explicit MaleCNS superclass label sets "
            f"{_MALECNS_SUPERCLASS_CATEGORIES}; no DN/MN/type-name inference."
        ),
        expected_but_missing_fields=missing,
    )
