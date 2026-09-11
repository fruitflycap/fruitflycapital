"""MaleCNS weighted graph adaptation for Brian2."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from ..schema import EdgeTable, NeuronTable

# Only transmitter classes with a defensible default sign are assigned a sign.
# Glutamate and most biogenic amines remain ambiguous here because a
# neuron-level prediction does not identify the postsynaptic receptor. Visual
# histamine is handled below only when the presynaptic MaleCNS class is
# explicitly ``visual``; Drosophila photoreceptor histamine is documented as
# acting through histamine-gated chloride channels in the image-forming visual
# system.
TRANSMITTER_SIGNS = {
    "acetylcholine": 1.0,
    "gaba": -1.0,
}


@dataclass
class ConnectivityMatrix:
    """Sparse edge list preserving raw body IDs, direction, and weights."""

    neurons: Any
    edges: Any
    included_edges: Any
    excluded_edges: Any
    unknown_sign: str
    transmitter_column: str
    synapse_scale_mV: float

    @classmethod
    def from_tables(
        cls,
        neurons: NeuronTable | Any,
        edges: EdgeTable | Any,
        *,
        synapse_scale_mV: float = 0.275,
        unknown_sign: str = "exclude",
        transmitter_column: str = "predicted_neurotransmitter",
    ) -> "ConnectivityMatrix":
        if unknown_sign not in {"exclude", "positive"}:
            raise ValueError("unknown_sign must be 'exclude' or 'positive'")
        neuron_frame = getattr(neurons, "dataframe", neurons).copy()
        edge_frame = getattr(edges, "dataframe", edges).copy()
        if "body_id" not in neuron_frame.columns:
            raise ValueError("Neuron table must contain body_id")
        index_by_body = pd.Series(neuron_frame.index, index=neuron_frame["body_id"].astype("int64"))
        work = edge_frame.copy()
        work["source_index"] = work["source_body_id"].map(index_by_body)
        work["target_index"] = work["target_body_id"].map(index_by_body)
        work["transmitter"] = work["source_body_id"].map(
            pd.Series(neuron_frame[transmitter_column].values, index=neuron_frame["body_id"].astype("int64"))
            if transmitter_column in neuron_frame.columns
            else pd.Series(dtype="object")
        )
        work["transmitter_normalized"] = work["transmitter"].astype("string").str.strip().str.lower()
        work["sign"] = work["transmitter_normalized"].map(TRANSMITTER_SIGNS)
        source_class = work["source_body_id"].map(
            pd.Series(neuron_frame["class"].values, index=neuron_frame["body_id"].astype("int64"))
            if "class" in neuron_frame.columns
            else pd.Series(dtype="object")
        )
        visual_histamine = source_class.astype("string").eq("visual") & work["transmitter_normalized"].eq("histamine")
        work.loc[visual_histamine, "sign"] = -1.0
        work["sign_basis"] = "generic transmitter sign"
        work.loc[visual_histamine, "sign_basis"] = "visual photoreceptor histamine; chloride-channel evidence"
        has_valid_endpoints = work["source_index"].notna() & work["target_index"].notna()
        if unknown_sign == "positive":
            work.loc[work["sign"].isna(), "sign"] = 1.0
        included = work[has_valid_endpoints & work["sign"].notna()].copy()
        excluded = work[~(has_valid_endpoints & work["sign"].notna())].copy()
        included["source_index"] = included["source_index"].astype("int64")
        included["target_index"] = included["target_index"].astype("int64")
        included["signed_weight_mV"] = included["synapse_weight"] * included["sign"] * synapse_scale_mV
        excluded["exclusion_reason"] = "unknown_transmitter_sign_or_unannotated_endpoint"
        return cls(neuron_frame, edge_frame, included, excluded, unknown_sign, transmitter_column, synapse_scale_mV)

    @property
    def source_indices(self):
        return self.included_edges["source_index"].to_numpy(dtype="int64")

    @property
    def target_indices(self):
        return self.included_edges["target_index"].to_numpy(dtype="int64")

    @property
    def signed_weights_mV(self):
        return self.included_edges["signed_weight_mV"].to_numpy(dtype=float)

    @property
    def excluded_edge_count(self) -> int:
        return int(len(self.excluded_edges))

    @property
    def total_raw_weight(self) -> float:
        return float(self.edges["synapse_weight"].sum())

    @property
    def total_included_raw_weight(self) -> float:
        return float(self.included_edges["synapse_weight"].sum())
