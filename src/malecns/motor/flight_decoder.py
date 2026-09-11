"""Spike-rate to abstract flight-command decoding.

The decoder does not inspect the world and does not contain target-following
rules. It only reads recent MaleCNS rates for selected annotated populations.
The rate reference and command signs are explicit interpretation assumptions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from ..loader import normalize_neurons, read_feather
from .flight_registry import flight_population_ids
from .flight_adapter import LowLevelFlightCommand, MaleCNSFlightAdapter


@dataclass(frozen=True)
class FlightCommand:
    thrust: float
    yaw: float
    pitch: float
    roll: float

    def as_dict(self) -> dict[str, float]:
        return {"thrust": self.thrust, "yaw": self.yaw, "pitch": self.pitch, "roll": self.roll}

    def as_actuators(self) -> dict[str, float]:
        # The browser physics owns the force conversion. Vertical thrust stays
        # at its explicit hover-neutral value because no vertical flight DN
        # mapping is asserted by this decoder.
        return {
            "forwardThrust": self.thrust,
            "verticalThrust": 0.5,
            "yawTorque": self.yaw,
            "pitchTorque": self.pitch,
            "rollTorque": self.roll,
        }


@dataclass(frozen=True)
class FlightDecodeResult:
    command: FlightCommand
    descending_rates_hz: dict[str, float]
    spike_counts: dict[str, int]
    low_level_command: LowLevelFlightCommand

    def as_dict(self) -> dict[str, Any]:
        return {
            "flightCommand": self.command.as_dict(),
            "maleCnsCommand": self.command.as_dict(),
            "steeringReference7d": self.low_level_command.steering_reference.as_dict(),
            "lowLevelFlightCommand": self.low_level_command.as_dict(),
            "descendingRates": self.descending_rates_hz,
            "spikeCounts": self.spike_counts,
        }

    def as_actuators(self) -> dict[str, float]:
        """Return the command consumed by the browser/MuJoCo body."""
        return self.low_level_command.as_dict()


class FlightMotorDecoder:
    """Decode firing rates from exact MaleCNS IDs into normalized commands."""

    def __init__(self, populations: Mapping[str, list[int]], *, reference_rate_hz: float = 20.0) -> None:
        self.populations = {name: tuple(int(body_id) for body_id in ids) for name, ids in populations.items()}
        self.reference_rate_hz = float(reference_rate_hz)
        if self.reference_rate_hz <= 0:
            raise ValueError("reference_rate_hz must be positive")

    @classmethod
    def from_malecns_annotations(cls, path: str | Path) -> "FlightMotorDecoder":
        neurons = normalize_neurons(read_feather(path))
        return cls(flight_population_ids(neurons))

    def decode(self, firing_rates: Mapping[int, float] | pd.DataFrame, spike_counts: Mapping[int, int] | None = None) -> FlightDecodeResult:
        rates = self._rate_map(firing_rates)
        counts = {str(int(body_id)): int(count) for body_id, count in (spike_counts or {}).items()}

        left = self._mean(rates, self.populations.get("turn_left_readout", ()))
        right = self._mean(rates, self.populations.get("turn_right_readout", ()))
        saccade_left = self._mean(rates, self.populations.get("saccade_left", ()))
        saccade_right = self._mean(rates, self.populations.get("saccade_right", ()))
        wing = self._mean(rates, self.populations.get("wing_amplitude", ()))
        saccade = self._mean(rates, self.populations.get("saccade", ()))
        takeoff = self._mean(rates, self.populations.get("escape_takeoff", ()))
        landing = self._mean(rates, self.populations.get("landing", ()))
        forward = self._mean(rates, self.populations.get("forward_readout", ()))

        # DNa01/DNa02 are the existing bilateral turn readout candidates in
        # this project. Positive yaw is the right-side-minus-left-side sign;
        # this sign convention is OUR_ASSUMPTION, not a new neural edge.
        yaw = _clip((saccade_right - saccade_left) / self.reference_rate_hz)
        # DNg02 is a wing-amplitude candidate; DNp09/DNp28 are the documented
        # forward readout candidates. They are neural intent, not direct force.
        thrust = _clip(max(wing, takeoff, forward) / self.reference_rate_hz, 0.0, 1.0)
        # No exact MaleCNS one-to-one pitch/roll or stop command is asserted.
        neural_command = FlightCommand(thrust=thrust, yaw=yaw, pitch=0.0, roll=0.0)
        low_level_command = MaleCNSFlightAdapter().adapt(
            thrust=neural_command.thrust,
            yaw=neural_command.yaw,
            pitch=neural_command.pitch,
            roll=neural_command.roll,
            active_rate_hz=max(rates.values(), default=0.0),
        )
        result = FlightDecodeResult(
            command=neural_command,
            descending_rates_hz={
                "turn_left": left,
                "turn_right": right,
                "saccade_left": saccade_left,
                "saccade_right": saccade_right,
                "wing_amplitude": wing,
                "forward": forward,
                "saccade": saccade,
                "escape_takeoff": takeoff,
                "landing": landing,
            },
            spike_counts=counts,
            low_level_command=low_level_command,
        )
        return result

    def _rate_map(self, firing_rates: Mapping[int, float] | pd.DataFrame) -> dict[int, float]:
        if isinstance(firing_rates, pd.DataFrame):
            if "body_id" not in firing_rates.columns or "firing_rate_hz" not in firing_rates.columns:
                raise ValueError("firing_rates DataFrame requires body_id and firing_rate_hz columns")
            return {int(row.body_id): float(row.firing_rate_hz) for row in firing_rates.itertuples()}
        return {int(body_id): float(rate) for body_id, rate in firing_rates.items()}

    @staticmethod
    def _mean(rates: Mapping[int, float], body_ids: tuple[int, ...]) -> float:
        if not body_ids:
            return 0.0
        return sum(max(0.0, rates.get(body_id, 0.0)) for body_id in body_ids) / len(body_ids)


def _clip(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return min(upper, max(lower, float(value)))
