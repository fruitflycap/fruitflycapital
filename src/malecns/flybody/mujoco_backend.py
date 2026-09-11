"""Thin, non-learning MuJoCo wrapper around Flybody's canonical XML.

This module deliberately accepts Flybody's native actuator vector. It does not
invent a FlightCommand -> joint-control map; that mapping must be defined from
documented Flybody actuator semantics before this backend is used in an
experiment.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

DEFAULT_XML = (
    Path(__file__).resolve().parents[3]
    / "third_party"
    / "flybody"
    / "flybody"
    / "fruitfly"
    / "assets"
    / "fruitfly.xml"
)


@dataclass(frozen=True)
class FlybodyPose:
    """Free-body pose and velocities in the MuJoCo XML coordinate system."""

    position_cm: tuple[float, float, float]
    quaternion_wxyz: tuple[float, float, float, float]
    velocity_cm_s: tuple[float, float, float]
    angular_velocity_rad_s: tuple[float, float, float]
    wing_joint_positions_rad: dict[str, float]


class MuJoCoFlybody:
    """Load and step the canonical Flybody model if MuJoCo is installed."""

    def __init__(self, xml_path: str | Path = DEFAULT_XML):
        try:
            import mujoco  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError(
                "MuJoCo is not installed. Install the optional 'physics' extra "
                "to run the canonical Flybody physics backend."
            ) from exc
        self._mujoco = mujoco
        self.xml_path = Path(xml_path)
        if not self.xml_path.exists():
            raise FileNotFoundError(f"Flybody XML not found: {self.xml_path}")
        self.model = mujoco.MjModel.from_xml_path(str(self.xml_path))
        self.data = mujoco.MjData(self.model)

    @property
    def actuator_count(self) -> int:
        return int(self.model.nu)

    @property
    def timestep_seconds(self) -> float:
        return float(self.model.opt.timestep)

    def reset(self) -> None:
        self._mujoco.mj_resetData(self.model, self.data)

    def step(self, native_controls: Sequence[float]) -> FlybodyPose:
        if len(native_controls) != self.actuator_count:
            raise ValueError(
                f"Flybody expects {self.actuator_count} native controls, "
                f"received {len(native_controls)}; no implicit actuator mapping is applied."
            )
        self.data.ctrl[:] = native_controls
        self._mujoco.mj_step(self.model, self.data)
        return self.pose()

    def pose(self) -> FlybodyPose:
        # The first body in fruitfly.xml has a free joint, whose qpos/qvel are
        # position + wxyz quaternion and linear + angular velocity.
        qpos = self.data.qpos
        qvel = self.data.qvel
        wing_positions: dict[str, float] = {}
        for name in ("wing_yaw_left", "wing_roll_left", "wing_pitch_left", "wing_yaw_right", "wing_roll_right", "wing_pitch_right"):
            joint_id = self._mujoco.mj_name2id(self.model, self._mujoco.mjtObj.mjOBJ_JOINT, name)
            if joint_id >= 0:
                wing_positions[name] = float(self.data.qpos[self.model.jnt_qposadr[joint_id]])
        return FlybodyPose(
            position_cm=tuple(float(value) for value in qpos[0:3]),  # type: ignore[return-value]
            quaternion_wxyz=tuple(float(value) for value in qpos[3:7]),  # type: ignore[return-value]
            velocity_cm_s=tuple(float(value) for value in qvel[0:3]),  # type: ignore[return-value]
            angular_velocity_rad_s=tuple(float(value) for value in qvel[3:6]),  # type: ignore[return-value]
            wing_joint_positions_rad=wing_positions,
        )
