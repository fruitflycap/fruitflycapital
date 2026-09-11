"""Deterministic queries over the unified Neuron table."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _values(value: Any) -> list[Any] | None:
    if value is None:
        return None
    if isinstance(value, (str, bytes)):
        return [value]
    if isinstance(value, Iterable):
        return list(value)
    return [value]


def query_neurons(
    neurons: Any,
    *,
    body_id: Any = None,
    type: Any = None,
    class_name: Any = None,
    class_: Any = None,
    side: Any = None,
    exact: bool = True,
) -> Any:
    """Query by body ID, type, class, and side without category inference."""
    if class_name is not None and class_ is not None:
        raise ValueError("Pass only one of class_name or class_")
    frame = getattr(neurons, "dataframe", neurons)
    result = frame
    filters = {"body_id": body_id, "type": type, "class": class_name if class_name is not None else class_, "side": side}
    for column, requested in filters.items():
        requested_values = _values(requested)
        if requested_values is None:
            continue
        if column not in result.columns:
            raise ValueError(f"Cannot query by {column!r}: canonical column is absent")
        if exact:
            result = result[result[column].isin(requested_values)]
        else:
            pattern = "|".join(str(v) for v in requested_values)
            result = result[result[column].astype("string").str.contains(pattern, case=False, na=False, regex=True)]
    return result.copy()


def incoming_edges(edges: Any, body_ids: Any) -> Any:
    """Return all local edges targeting one or more body IDs."""
    frame = getattr(edges, "dataframe", edges)
    ids = _values(body_ids) or []
    return frame[frame["target_body_id"].isin(ids)].copy()


def outgoing_edges(edges: Any, body_ids: Any) -> Any:
    """Return all local edges originating at one or more body IDs."""
    frame = getattr(edges, "dataframe", edges)
    ids = _values(body_ids) or []
    return frame[frame["source_body_id"].isin(ids)].copy()
