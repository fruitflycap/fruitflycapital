"""Annotation/evidence-grounded output populations for MaleCNS.

These helpers identify candidate output/readout cells. They intentionally do
not attach movement gains, remap signs, or choose cells by simulated activity.
"""

from __future__ import annotations

from typing import Any, Iterable


TURN_TYPES = ("DNa01", "DNa02")
FORWARD_TYPES = ("DNp09", "DNp28")
STOP_TYPES = ("FG", "BB", "BRK")


def _frame(neurons: Any) -> Any:
    return getattr(neurons, "dataframe", neurons)


def _ids(frame: Any, mask: Any) -> list[int]:
    return sorted(frame.loc[mask, "body_id"].astype("int64").tolist())


def _descending(frame: Any, types: Iterable[str], side: str | None = None) -> list[int]:
    mask = frame["superclass"].astype("string").isin(["descending_neuron", "descending_neuron_tbc"])
    mask &= frame["type"].astype("string").isin(list(types))
    if side is not None:
        mask &= frame["side"].astype("string").eq(side)
    return _ids(frame, mask)


def descending_ids(neurons: Any, *, side: str | None = None) -> list[int]:
    frame = _frame(neurons)
    mask = frame["superclass"].astype("string").isin(["descending_neuron", "descending_neuron_tbc"])
    if side is not None:
        mask &= frame["side"].astype("string").eq(side)
    return _ids(frame, mask)


def turn_left_output_ids(neurons: Any) -> list[int]:
    """Ipsilateral DNa01/DNa02 candidates for left steering."""
    return _descending(_frame(neurons), TURN_TYPES, "L")


def turn_right_output_ids(neurons: Any) -> list[int]:
    """Ipsilateral DNa01/DNa02 candidates for right steering."""
    return _descending(_frame(neurons), TURN_TYPES, "R")


def forward_output_ids(neurons: Any, *, types: Iterable[str] = FORWARD_TYPES, side: str | None = None) -> list[int]:
    """Return exact MaleCNS types with published forward-walking evidence."""
    return _descending(_frame(neurons), types, side)


def stop_output_ids(neurons: Any, *, types: Iterable[str] = STOP_TYPES, side: str | None = None) -> list[int]:
    """Return exact annotated stop candidates, if MaleCNS exposes those names.

    The current MaleCNS v1.0 annotation file has no exact FG/BB/BRK rows, so
    the default result is intentionally empty rather than a guessed proxy.
    """
    return _descending(_frame(neurons), types, side)


def walking_state_ids(neurons: Any) -> list[int]:
    """Return a dedicated walking-state population when explicitly annotated.

    No dedicated state label is currently defined by the MaleCNS v1.0 schema;
    an empty list records that limitation instead of relabeling a command
    neuron as a state neuron.
    """
    return []


def descending_walking_readout_ids(neurons: Any) -> list[int]:
    """Candidate command/readout union used for population-level reports."""
    return sorted(set(turn_left_output_ids(neurons) + turn_right_output_ids(neurons) + forward_output_ids(neurons)))
