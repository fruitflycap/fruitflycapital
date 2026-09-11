"""Canonical table schemas.

The source files are intentionally not forced into a narrower schema than the
dataset provides. Canonical fields are normalized, while all source columns
that are not mapped are retained as additional columns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

NEURON_COLUMNS = (
    "body_id",
    "type",
    "class",
    "subclass",
    "superclass",
    "side",
    "nerve",
    "entry_nerve",
    "exit_nerve",
    "hemilineage",
    "itolee_hemilineage",
    "truman_hemilineage",
    "status",
    "predicted_neurotransmitter",
    "neurotransmitter_confidence",
    "pre_count",
    "post_count",
)

EDGE_COLUMNS = ("source_body_id", "target_body_id", "synapse_weight")


@dataclass(frozen=True)
class NeuronRecord:
    body_id: int
    type: str | None = None
    class_: str | None = None
    subclass: str | None = None
    side: str | None = None
    nerve: str | None = None
    hemilineage: str | None = None
    status: str | None = None
    predicted_neurotransmitter: str | None = None
    neurotransmitter_confidence: float | None = None
    pre_count: int | None = None
    post_count: int | None = None
    extra: dict[str, Any] | None = None


@dataclass(frozen=True)
class EdgeRecord:
    source_body_id: int
    target_body_id: int
    synapse_weight: float
    extra: dict[str, Any] | None = None


@dataclass
class NeuronTable:
    """A validated pandas DataFrame wrapper for the unified neuron table."""

    frame: Any

    def __post_init__(self) -> None:
        _require_columns(self.frame, ("body_id",))

    @property
    def dataframe(self) -> Any:
        return self.frame

    def __len__(self) -> int:
        return len(self.frame)


@dataclass
class EdgeTable:
    """A validated pandas DataFrame wrapper for the unified edge table."""

    frame: Any

    def __post_init__(self) -> None:
        _require_columns(self.frame, EDGE_COLUMNS)

    @property
    def dataframe(self) -> Any:
        return self.frame

    def __len__(self) -> int:
        return len(self.frame)


def _require_columns(frame: Any, columns: Iterable[str]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing required canonical columns: {missing}")
