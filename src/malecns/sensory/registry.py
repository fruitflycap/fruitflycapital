"""Annotation-grounded MaleCNS sensory population registries.

The registry selects exact MaleCNS ``class``/``subclass``/``type`` labels and
uses the source ``somaSide`` or ``rootSide`` annotation already coalesced into
the canonical ``side`` field. It does not select neurons because they produce
a convenient simulation response.
"""

from __future__ import annotations

from typing import Any


MECHANOSENSORY_CLASSES = frozenset(
    {"mechanosensory", "mechanosensory_tactile", "mechanosensory_proprioceptive"}
)


def _frame(neurons: Any) -> Any:
    return getattr(neurons, "dataframe", neurons)


def _side(frame: Any):
    """Return effective side without inferring it from a name."""
    if "side" in frame.columns:
        result = frame["side"].copy()
    else:
        result = frame.get("somaSide")
    if result is None:
        result = frame.get("rootSide")
    elif "rootSide" in frame.columns:
        result = result.where(result.notna(), frame["rootSide"])
    return result


def _ids(frame: Any, mask: Any) -> list[int]:
    return sorted(frame.loc[mask, "body_id"].astype("int64").tolist())


def visual_ids(neurons: Any, *, side: str | None = None, type_name: str | None = None) -> list[int]:
    """Return exact MaleCNS visual neurons, optionally by side and type."""
    frame = _frame(neurons)
    mask = frame["class"].astype("string").eq("visual")
    if type_name is not None:
        mask &= frame["type"].astype("string").eq(type_name)
    if side is not None:
        mask &= _side(frame).astype("string").eq(side)
    return _ids(frame, mask)


def visual_left_ids(neurons: Any, *, type_name: str | None = None) -> list[int]:
    return visual_ids(neurons, side="L", type_name=type_name)


def visual_right_ids(neurons: Any, *, type_name: str | None = None) -> list[int]:
    return visual_ids(neurons, side="R", type_name=type_name)


def olfactory_ids(
    neurons: Any,
    *,
    side: str | None = None,
    type_name: str | None = None,
    include_unknown_side: bool = False,
) -> list[int]:
    """Return exact MaleCNS olfactory neurons; no hemisphere is guessed."""
    frame = _frame(neurons)
    mask = frame["class"].astype("string").eq("olfactory")
    if type_name is not None:
        mask &= frame["type"].astype("string").eq(type_name)
    if side is not None:
        mask &= _side(frame).astype("string").eq(side)
    elif not include_unknown_side:
        # All class-labelled olfactory cells are returned when no side is
        # requested. Unknown-side cells are not assigned to L or R.
        pass
    return _ids(frame, mask)


def mechanosensory_ids(
    neurons: Any,
    *,
    side: str | None = None,
    modality: str | None = None,
    type_name: str | None = None,
) -> list[int]:
    """Return exact mechanosensory classes or an exact subclass modality.

    Observed modality values include ``tactile``, ``proprioceptive``,
    ``auditory``, ``chordotonal organ``, ``campaniform sensilla``, and
    ``hair plate``.
    """
    frame = _frame(neurons)
    classes = frame["class"].astype("string")
    mask = classes.isin(MECHANOSENSORY_CLASSES)
    if type_name is not None:
        mask &= frame["type"].astype("string").eq(type_name)
    if modality is not None:
        aliases = {"tactile": "mechanosensory_tactile", "proprioceptive": "mechanosensory_proprioceptive"}
        if modality in aliases:
            mask &= classes.eq(aliases[modality])
        else:
            if "subclass" not in frame.columns:
                return []
            mask &= frame["subclass"].astype("string").eq(modality)
    if side is not None:
        mask &= _side(frame).astype("string").eq(side)
    return _ids(frame, mask)


def mechanosensory_left_ids(neurons: Any, *, modality: str | None = None, type_name: str | None = None) -> list[int]:
    return mechanosensory_ids(neurons, side="L", modality=modality, type_name=type_name)


def mechanosensory_right_ids(neurons: Any, *, modality: str | None = None, type_name: str | None = None) -> list[int]:
    return mechanosensory_ids(neurons, side="R", modality=modality, type_name=type_name)
