"""MaleCNS readout to the Flybody flight-controller boundary.

Flybody's two-level controller does not pass a single frequency scalar from
the high-level controller to the low-level policy.  It replaces the low-level
observation block named ``walker/ref_displacement`` and
``walker/ref_root_quat`` with a bounded steering vector.  For
``future_steps=0`` that block is seven values: three displacement values and
one relative quaternion.

This module keeps that boundary explicit.  It intentionally knows nothing
about habitats, markets, or target positions.  MaleCNS supplies only neural
readouts.  The native Flybody checkpoint can consume the steering reference
when the optional MuJoCo/TensorFlow worker is installed; the legacy scalar
fields remain in the response for the browser's current actuator bridge.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import cos, sin, sqrt
from typing import Any


FLYBODY_STEERING_COMMAND_DIM = 7
FLYBODY_STEERING_FUTURE_STEPS = 0
FLYBODY_CONTROL_TIMESTEP_SECONDS = 2e-4


@dataclass(frozen=True)
class FlyBodySteeringReference:
    """The seven-value steering block consumed by Flybody's LL policy.

    Flybody uses CGS-scale model units.  In the upstream fruit-fly tasks the
    reference trajectory and heights are expressed in centimetres, so the
    displacement here is explicitly ``cm``.  The quaternion is the relative
    root orientation in the fly-local frame, ordered ``w, x, y, z``.

    This V1 adapter emits one current reference (``future_steps=0``).  A
    low-level environment configured with future previews would require
    ``7 * (future_steps + 1)`` values and must not be fed this vector.
    """

    ref_displacement_cm: tuple[float, float, float]
    ref_root_quat_wxyz: tuple[float, float, float, float]
    future_steps: int = FLYBODY_STEERING_FUTURE_STEPS

    def __post_init__(self) -> None:
        if len(self.ref_displacement_cm) != 3:
            raise ValueError("Flybody displacement must contain exactly 3 values")
        if len(self.ref_root_quat_wxyz) != 4:
            raise ValueError("Flybody root quaternion must contain exactly 4 values")
        if self.future_steps != FLYBODY_STEERING_FUTURE_STEPS:
            raise ValueError(
                "NeuroSwarm V1 emits one current Flybody reference only; "
                "construct a separate repeated-reference adapter for future_steps > 0"
            )
        norm = sqrt(sum(float(value) ** 2 for value in self.ref_root_quat_wxyz))
        if abs(norm - 1.0) > 1e-6:
            raise ValueError(f"Flybody root quaternion must be unit length, got {norm}")

    @property
    def dimension(self) -> int:
        return FLYBODY_STEERING_COMMAND_DIM * (self.future_steps + 1)

    def as_vector(self) -> tuple[float, ...]:
        return self.ref_displacement_cm + self.ref_root_quat_wxyz

    def as_dict(self) -> dict[str, Any]:
        return {
            "vector": list(self.as_vector()),
            "dimension": self.dimension,
            "futureSteps": self.future_steps,
            "refDisplacementCm": list(self.ref_displacement_cm),
            "refRootQuatWxyz": list(self.ref_root_quat_wxyz),
            "displacementFrame": "flybody-egocentric",
            "quaternionFrame": "flybody-relative-root",
        }


@dataclass(frozen=True)
class LowLevelFlightCommand:
    """Bounded motor-level command, independent of world semantics."""

    forward_thrust: float
    vertical_thrust: float
    yaw: float
    pitch: float
    roll: float
    wingbeat_frequency_hz: float
    steering_reference: FlyBodySteeringReference

    def as_dict(self) -> dict[str, Any]:
        return {
            "forwardThrust": self.forward_thrust,
            "verticalThrust": self.vertical_thrust,
            "yawTorque": self.yaw,
            "pitchTorque": self.pitch,
            "rollTorque": self.roll,
            "wingbeatFrequencyHz": self.wingbeat_frequency_hz,
            "steeringReference7d": self.steering_reference.as_dict(),
        }


class MaleCNSFlightAdapter:
    """Adapt neural readouts to a bounded Flybody steering reference.

    ``thrust`` and ``yaw`` are normalized neural readouts from the decoder, not
    market-derived values.  Their conversion to Flybody centimetres/radians
    is an explicitly configurable V1 calibration, because MaleCNS annotations
    do not publish a seven-dimensional Flybody steering scale.

    The upstream WPG still generates wingbeats inside Flybody.  Until the
    optional trained checkpoint is installed in a MuJoCo worker, the legacy
    scalar fields provide the browser-compatible actuator bridge.  They are
    retained for compatibility and must not be mistaken for the upstream
    seven-dimensional high-level interface.
    """

    def __init__(
        self,
        *,
        base_cruise_thrust: float = 0.16,
        neural_thrust_gain: float = 0.68,
        base_wingbeat_hz: float = 218.0,
        max_forward_displacement_cm: float = 0.5,
        max_yaw_reference_radians: float = 0.35,
    ) -> None:
        self.base_cruise_thrust = _clip01(base_cruise_thrust)
        self.neural_thrust_gain = _clip01(neural_thrust_gain)
        self.base_wingbeat_hz = max(1.0, float(base_wingbeat_hz))
        self.max_forward_displacement_cm = max(0.0, float(max_forward_displacement_cm))
        self.max_yaw_reference_radians = max(0.0, float(max_yaw_reference_radians))

    def adapt(
        self,
        *,
        thrust: float,
        yaw: float,
        pitch: float,
        roll: float,
        active_rate_hz: float,
    ) -> LowLevelFlightCommand:
        """Return only motor-level output from bounded neural readouts."""

        neural_thrust = _clip01(thrust)
        neural_yaw = _clip_signed(yaw)
        neural_pitch = _clip_signed(pitch)
        neural_roll = _clip_signed(roll)
        has_neural_activity = max(float(active_rate_hz), neural_thrust, abs(neural_yaw), abs(neural_pitch), abs(neural_roll)) > 0.0
        cruise = self.base_cruise_thrust if has_neural_activity else 0.0
        steering_reference = self._steering_reference(
            thrust=neural_thrust,
            yaw=neural_yaw,
        )
        return LowLevelFlightCommand(
            forward_thrust=_clip01(cruise + neural_thrust * self.neural_thrust_gain),
            vertical_thrust=0.5,
            yaw=_clip_signed(neural_yaw * 0.6),
            pitch=_clip_signed(neural_pitch * 0.45),
            roll=_clip_signed(neural_roll * 0.45),
            wingbeat_frequency_hz=self.base_wingbeat_hz,
            steering_reference=steering_reference,
        )

    def _steering_reference(self, *, thrust: float, yaw: float) -> FlyBodySteeringReference:
        """Build the V1 current-reference block without world information.

        Flybody's reference trajectory uses +X as its forward direction and
        +Z as its heading/yaw axis.  Only the neural forward and bilateral yaw
        readouts are mapped in V1.  Vertical modulation, pitch, and roll are
        intentionally left at the neutral reference until a documented
        descending-neuron mapping is validated.
        """

        yaw_radians = yaw * self.max_yaw_reference_radians
        half_angle = yaw_radians / 2.0
        return FlyBodySteeringReference(
            ref_displacement_cm=(thrust * self.max_forward_displacement_cm, 0.0, 0.0),
            ref_root_quat_wxyz=(cos(half_angle), 0.0, 0.0, sin(half_angle)),
        )


def _clip01(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _clip_signed(value: float) -> float:
    return min(1.0, max(-1.0, float(value)))
