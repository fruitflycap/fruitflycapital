"""Exact MaleCNS flight-related descending populations.

These are candidate readouts, not newly created motor labels. Functional
roles are evidence annotations from the flight literature and remain separate
from the official MaleCNS structural labels.
"""

from __future__ import annotations

from typing import Any, Iterable


FLIGHT_WING_AMPLITUDE = ("DNg02",)
FLIGHT_SACCADE = ("DNa15", "DNb01", "DNp03")
FLIGHT_ESCAPE_TAKEOFF = ("DNp01",)
FLIGHT_EVASIVE_TURN = ("DNp06",)
FLIGHT_LANDING = ("DNp07", "DNp10")


def _frame(neurons: Any) -> Any:
    return getattr(neurons, "dataframe", neurons)


def _ids(frame: Any, types: Iterable[str], side: str | None = None) -> list[int]:
    descending = frame["superclass"].astype("string").isin(["descending_neuron", "descending_neuron_tbc"])
    type_names = frame.get("mancType", frame["type"]).astype("string")
    mask = descending & type_names.isin(list(types))
    if side is not None:
        mask &= frame["side"].astype("string").eq(side)
    return sorted(frame.loc[mask, "body_id"].astype("int64").tolist())


def flight_population_ids(neurons: Any) -> dict[str, list[int]]:
    frame = _frame(neurons)
    return {
        "wing_amplitude": _ids(frame, FLIGHT_WING_AMPLITUDE),
        "saccade": _ids(frame, FLIGHT_SACCADE),
        "saccade_left": _ids(frame, FLIGHT_SACCADE, "L"),
        "saccade_right": _ids(frame, FLIGHT_SACCADE, "R"),
        "escape_takeoff": _ids(frame, FLIGHT_ESCAPE_TAKEOFF),
        "evasive_turn": _ids(frame, FLIGHT_EVASIVE_TURN),
        "landing": _ids(frame, FLIGHT_LANDING),
        "turn_left_readout": _ids(frame, ("DNa01", "DNa02"), "L"),
        "turn_right_readout": _ids(frame, ("DNa01", "DNa02"), "R"),
        "forward_readout": _ids(frame, ("DNp09", "DNp28")),
    }


def flight_population_types() -> dict[str, tuple[str, ...]]:
    return {
        "wing_amplitude": FLIGHT_WING_AMPLITUDE,
        "saccade": FLIGHT_SACCADE,
        "saccade_left": FLIGHT_SACCADE,
        "saccade_right": FLIGHT_SACCADE,
        "escape_takeoff": FLIGHT_ESCAPE_TAKEOFF,
        "evasive_turn": FLIGHT_EVASIVE_TURN,
        "landing": FLIGHT_LANDING,
        "turn_left_readout": ("DNa01", "DNa02"),
        "turn_right_readout": ("DNa01", "DNa02"),
        "forward_readout": ("DNp09", "DNp28"),
    }
