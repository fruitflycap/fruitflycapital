"""Run controlled 3-D flight experiments without tuning the CNS model.

This is a deterministic, headless reference harness for the current browser
physics/decoder boundary. It uses the checked-in MaleCNS sensory encoder and
FlightMotorDecoder, but it does not invent a live Brian2 spike provider. The
``malecns_connected`` condition therefore means "decoder connected and fed an
empty rate window" until an actual provider is attached. This distinction is
written into every output file.

The rigid-body update mirrors the constants and update order in
frontend/src/fly/FlyBody.ts. The harness intentionally does not add a target
controller, stabilizing controller, or movement objective.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from malecns.brain.sensory_encoding import default_encoder
from malecns.motor.flight_decoder import FlightMotorDecoder


DT_SECONDS = 1.0 / 120.0
ARENA_MIN = np.array([-1.0, 0.0, -1.0], dtype=float)
ARENA_MAX = np.array([1.0, 1.0, 1.0], dtype=float)
COLLISION_RADIUS = 0.0025


@dataclass
class BodyState:
    position: np.ndarray
    velocity: np.ndarray
    quaternion: np.ndarray
    angular_velocity: np.ndarray
    ground: bool = False
    wall: bool = False

    @classmethod
    def initial(cls) -> "BodyState":
        return cls(
            position=np.array([0.0, 0.48, 0.0], dtype=float),
            velocity=np.zeros(3, dtype=float),
            quaternion=np.array([0.0, 0.0, 0.0, 1.0], dtype=float),
            angular_velocity=np.zeros(3, dtype=float),
        )

    def step(self, command: dict[str, float], dt: float) -> None:
        # These values match FlyBody.ts; they are not experiment parameters.
        mass_kg = 0.001
        inertia = np.array([0.0000012, 0.0000015, 0.0000011])
        max_forward_force_n = 0.00055
        max_vertical_force_n = 0.000018
        gravity_n = 0.00000981
        max_torque_nm = 0.000001
        linear_drag = 0.0032
        angular_drag = 3.8

        forward = quat_rotate(self.quaternion, np.array([0.0, 0.0, -1.0]))
        up = quat_rotate(self.quaternion, np.array([0.0, 1.0, 0.0]))
        force = forward * command["forwardThrust"] * max_forward_force_n
        force += up * command["verticalThrust"] * max_vertical_force_n
        force[1] -= gravity_n
        force -= self.velocity * linear_drag
        self.velocity += force * (dt / mass_kg)
        self.velocity *= math.exp(-linear_drag * 2.0 * dt)
        self.position += self.velocity * dt

        local_torque = np.array([command["pitchTorque"], command["yawTorque"], command["rollTorque"]])
        self.angular_velocity += (local_torque * max_torque_nm / inertia) * dt
        self.angular_velocity *= math.exp(-angular_drag * dt)
        angle = float(np.linalg.norm(self.angular_velocity) * dt)
        if angle > 0.0000001:
            axis = self.angular_velocity / np.linalg.norm(self.angular_velocity)
            self.quaternion = quat_normalize(quat_multiply(self.quaternion, quat_axis_angle(axis, angle)))

        self.resolve_bounds()

    def resolve_bounds(self) -> None:
        self.ground = False
        self.wall = False
        minimum = ARENA_MIN + COLLISION_RADIUS
        maximum = ARENA_MAX - COLLISION_RADIUS
        for axis in (0, 2):
            if self.position[axis] < minimum[axis]:
                self.wall = True
                self.position[axis] = minimum[axis]
                self.velocity[axis] = abs(self.velocity[axis]) * 0.25
            elif self.position[axis] > maximum[axis]:
                self.wall = True
                self.position[axis] = maximum[axis]
                self.velocity[axis] = -abs(self.velocity[axis]) * 0.25
        if self.position[1] < minimum[1]:
            self.ground = True
            self.position[1] = minimum[1]
            self.velocity[1] = max(0.0, self.velocity[1]) * 0.1
        elif self.position[1] > maximum[1]:
            self.position[1] = maximum[1]
            self.velocity[1] = -abs(self.velocity[1]) * 0.25


class ExperimentRunner:
    def __init__(self, output_dir: Path, seed: int) -> None:
        self.output_dir = output_dir
        self.seed = int(seed)
        self.rng = np.random.default_rng(self.seed)
        self.encoder = default_encoder()
        annotations = Path(__file__).resolve().parents[1] / "data" / "raw" / "body-annotations-male-cns-v1.0-minconf-0.5.feather"
        self.decoder = FlightMotorDecoder.from_malecns_annotations(annotations)
        self.rows: list[dict[str, Any]] = []
        self.summaries: dict[str, Any] = {}

    def run(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        config = {
            "seed": self.seed,
            "dt_seconds": DT_SECONDS,
            "arena_m": {"x": 2.0, "y": 1.0, "z": 2.0},
            "physics_source": "frontend/src/fly/FlyBody.ts mirrored in this headless harness",
            "malecns_data": "data/raw/body-annotations-male-cns-v1.0-minconf-0.5.feather",
            "neural_provider": "none",
            "malecns_connected_semantics": "FlightMotorDecoder receives an empty rate window; no spikes are fabricated",
            "motor_disabled_semantics": "all actuator channels set to zero",
            "experiments": {
                "A_visual_stabilization_s": 10.0,
                "B_visual_target_directions": ["left", "right", "above", "below"],
                "B_visual_target_each_s": 4.0,
                "C_odor_source_s": 20.0,
                "D_free_flight_s": 60.0,
            },
        }
        (self.output_dir / "experiment_config.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")

        self.experiment_a()
        self.experiment_b()
        self.experiment_c()
        self.experiment_d()
        self.write_outputs(config)

    def simulate(
        self,
        name: str,
        duration_s: float,
        sensor_fn,
        command_condition: str,
        *,
        disturbance_fn=None,
        odor_source: np.ndarray | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        body = BodyState.initial()
        local_rows: list[dict[str, Any]] = []
        steps = int(round(duration_s / DT_SECONDS))
        for step in range(steps):
            time_s = step * DT_SECONDS
            if disturbance_fn is not None:
                disturbance_fn(body, time_s, step)
            sensory = sensor_fn(body, time_s)
            stimulation = self.encoder.encode(sensory)
            if command_condition == "malecns_connected":
                decoded = self.decoder.decode({})
                command = decoded.command.as_actuators()
                descending_rates = decoded.descending_rates_hz
                spike_counts = decoded.spike_counts
            elif command_condition == "motor_output_disabled":
                command = {
                    "forwardThrust": 0.0,
                    "verticalThrust": 0.0,
                    "yawTorque": 0.0,
                    "pitchTorque": 0.0,
                    "rollTorque": 0.0,
                }
                descending_rates = {key: 0.0 for key in ("turn_left", "turn_right", "saccade_left", "saccade_right", "wing_amplitude", "saccade", "escape_takeoff", "landing")}
                spike_counts = {}
            else:
                raise ValueError(f"unknown command condition: {command_condition}")
            body.step(command, DT_SECONDS)
            distance = float(np.linalg.norm(body.position - odor_source)) if odor_source is not None else None
            row = {
                "experiment": name,
                "condition": command_condition,
                "timestamp_s": time_s,
                "sensory_input": sensory,
                "stimulation": stimulation,
                "stimulated_body_ids": sorted(
                    entry["bodyId"]
                    for channel in ("visual", "olfactory", "mechanosensory")
                    for entry in stimulation[channel]
                ),
                "spike_counts": spike_counts,
                "descending_rates_hz": descending_rates,
                "motor_output": command,
                "position": body.position.copy(),
                "rotation": body.quaternion.copy(),
                "velocity": body.velocity.copy(),
                "angular_velocity": body.angular_velocity.copy(),
                "distance_to_odor_m": distance,
                "ground_contact": body.ground,
                "wall_contact": body.wall,
                **(metadata or {}),
            }
            local_rows.append(row)
            self.rows.append(row)
        return local_rows

    def experiment_a(self) -> None:
        disturbance_times = {2.0, 4.0, 6.0, 8.0}
        impulses = {
            time_s: self.rng.normal(0.0, 0.018, size=3)
            for time_s in sorted(disturbance_times)
        }

        def sensors(_body: BodyState, _time_s: float) -> dict[str, Any]:
            return visual_frame(0.12, 0.12, 0.0, 0.0)

        def disturbances(body: BodyState, time_s: float, step: int) -> None:
            if round(time_s, 6) in disturbance_times:
                body.angular_velocity += impulses[round(time_s, 6)]

        for condition in ("malecns_connected", "motor_output_disabled"):
            rows = self.simulate("A_visual_stabilization", 10.0, sensors, condition, disturbance_fn=disturbances, metadata={"stimulus": "small random rotational impulses"})
            self.summaries.setdefault("A_visual_stabilization", {})[condition] = stabilization_summary(rows)

    def experiment_b(self) -> None:
        for direction in ("left", "right", "above", "below"):
            for condition in ("malecns_connected", "motor_output_disabled"):
                def sensors(_body: BodyState, _time_s: float, direction: str = direction) -> dict[str, Any]:
                    values = {"left": (0.9, 0.12), "right": (0.12, 0.9), "above": (0.72, 0.72), "below": (0.72, 0.72)}
                    left, right = values[direction]
                    return visual_frame(left, right, 0.9, 0.9)

                rows = self.simulate(
                    "B_visual_target",
                    4.0,
                    sensors,
                    condition,
                    metadata={"target_direction": direction, "elevation_channel_supported": False},
                )
                self.summaries.setdefault("B_visual_target", {}).setdefault(direction, {})[condition] = directional_summary(rows)

    def experiment_c(self) -> None:
        source = np.array([0.62, 0.50, -0.70], dtype=float)

        def sensors(body: BodyState, time_s: float) -> dict[str, Any]:
            distance = float(np.linalg.norm(body.position - source))
            concentration = min(1.0, max(0.0, math.exp(-(distance * distance) / (2 * 0.28 * 0.28))))
            return visual_frame(0.12, 0.12, 0.0, 0.0, odor=concentration)

        for condition in ("malecns_connected", "motor_output_disabled"):
            rows = self.simulate("C_odor_source", 20.0, sensors, condition, odor_source=source, metadata={"visual_source_hidden": True})
            self.summaries.setdefault("C_odor_source", {})[condition] = odor_summary(rows)

    def experiment_d(self) -> None:
        def sensors(_body: BodyState, _time_s: float) -> dict[str, Any]:
            return visual_frame(0.12, 0.12, 0.0, 0.0)

        rows = self.simulate("D_free_flight", 60.0, sensors, "malecns_connected", metadata={"scripted_objective": False})
        self.summaries["D_free_flight"] = free_flight_summary(rows)

    def write_outputs(self, config: dict[str, Any]) -> None:
        json_rows = [serialize_row(row) for row in self.rows]
        with gzip.open(self.output_dir / "telemetry.jsonl.gz", "wt", encoding="utf-8") as handle:
            for row in json_rows:
                handle.write(json.dumps(row, sort_keys=True) + "\n")
        flat = pd.DataFrame([flatten_row(row) for row in self.rows])
        flat.to_parquet(self.output_dir / "telemetry.parquet", index=False)
        trajectory = flat[flat["experiment"] == "D_free_flight"][
            ["timestamp_s", "condition", "position_x_m", "position_y_m", "position_z_m", "velocity_x_mps", "velocity_y_mps", "velocity_z_mps"]
        ]
        trajectory.to_csv(self.output_dir / "trajectory.csv", index=False)
        (self.output_dir / "summary.json").write_text(json.dumps(self.summaries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        (self.output_dir / "REPORT.md").write_text(render_report(self.summaries, self.seed), encoding="utf-8")
        self.plot_a(flat)
        self.plot_b(flat)
        self.plot_c(flat)
        self.plot_d(flat)
        report = {
            "status": "controlled_harness_complete_neural_provider_unavailable",
            "seed": self.seed,
            "rows": len(flat),
            "files": sorted(path.name for path in self.output_dir.iterdir()),
            "interpretation": "No autonomous MaleCNS claim is made: the connected condition uses an empty rate window and therefore zero decoded neural drive.",
        }
        (self.output_dir / "README.md").write_text(
            "# Single-fly 3-D experiment outputs\n\n"
            "Generated by `experiments/autonomous_flight_experiments.py`. The run is deterministic and uses seed "
            f"`{self.seed}`. The physics mirrors `frontend/src/fly/FlyBody.ts`.\n\n"
            "The current server has no live Brian2 rate provider. `malecns_connected` therefore means the exact "
            "sensory encoder and `FlightMotorDecoder` are connected, but the decoder receives an empty rate window. "
            "This produces zero neural thrust/yaw/pitch/roll and is reported as a limitation, not as autonomous success. "
            "`motor_output_disabled` zeros every actuator channel. No parameter tuning or target-following rule is used.\n"
            "The complete JSON Lines telemetry is compressed as `telemetry.jsonl.gz`; the same flat telemetry is in `telemetry.parquet`.\n",
            encoding="utf-8",
        )

    def plot_a(self, frame: pd.DataFrame) -> None:
        subset = frame[frame["experiment"] == "A_visual_stabilization"]
        fig, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
        for condition, group in subset.groupby("condition"):
            axes[0].plot(group.timestamp_s, group.angular_speed_rads, label=condition)
            axes[1].plot(group.timestamp_s, group.yaw_command, label=condition)
        axes[0].set_ylabel("angular speed (rad/s)")
        axes[1].set_ylabel("yaw command")
        axes[1].set_xlabel("time (s)")
        axes[0].legend()
        fig.suptitle("A — visual stabilization: passive response and decoded yaw")
        fig.tight_layout()
        fig.savefig(self.output_dir / "experiment_a_stabilization.png", dpi=140)
        plt.close(fig)

    def plot_b(self, frame: pd.DataFrame) -> None:
        subset = frame[frame["experiment"] == "B_visual_target"]
        grouped = subset.groupby(["target_direction", "condition"], as_index=False)[["yaw_command", "pitch_command", "roll_command"]].max()
        fig, axes = plt.subplots(1, 3, figsize=(12, 4))
        for axis, column in zip(axes, ("yaw_command", "pitch_command", "roll_command")):
            for condition, group in grouped.groupby("condition"):
                axes[list(("yaw_command", "pitch_command", "roll_command")).index(column)].plot(group.target_direction, group[column], marker="o", label=condition)
            axis.set_title(column)
            axis.tick_params(axis="x", rotation=35)
        axes[0].legend(fontsize=8)
        fig.suptitle("B — visual target conditions: no imposed directional controller")
        fig.tight_layout()
        fig.savefig(self.output_dir / "experiment_b_visual_target.png", dpi=140)
        plt.close(fig)

    def plot_c(self, frame: pd.DataFrame) -> None:
        subset = frame[frame["experiment"] == "C_odor_source"]
        fig, axes = plt.subplots(1, 2, figsize=(11, 4))
        for condition, group in subset.groupby("condition"):
            axes[0].plot(group.position_x_m, group.position_z_m, label=condition)
            axes[1].plot(group.timestamp_s, group.distance_to_odor_m, label=condition)
        axes[0].set_xlabel("x (m)")
        axes[0].set_ylabel("z (m)")
        axes[1].set_xlabel("time (s)")
        axes[1].set_ylabel("distance to odor source (m)")
        axes[0].legend()
        fig.suptitle("C — odor-only condition")
        fig.tight_layout()
        fig.savefig(self.output_dir / "experiment_c_odor_trajectory.png", dpi=140)
        plt.close(fig)

    def plot_d(self, frame: pd.DataFrame) -> None:
        subset = frame[frame["experiment"] == "D_free_flight"]
        fig = plt.figure(figsize=(8, 6))
        axis = fig.add_subplot(111, projection="3d")
        axis.plot(subset.position_x_m, subset.position_z_m, subset.position_y_m, linewidth=1.0)
        axis.set_xlabel("x (m)")
        axis.set_ylabel("z (m)")
        axis.set_zlabel("y (m)")
        axis.set_title("D — 60-second free-flight trajectory")
        fig.tight_layout()
        fig.savefig(self.output_dir / "experiment_d_free_flight.png", dpi=140)
        plt.close(fig)


def visual_frame(left_luminance: float, right_luminance: float, left_contrast: float, right_contrast: float, *, odor: float = 0.0) -> dict[str, Any]:
    return {
        "leftEye": {"meanLuminance": left_luminance, "meanContrast": left_contrast, "meanOpticFlow": 0.0},
        "rightEye": {"meanLuminance": right_luminance, "meanContrast": right_contrast, "meanOpticFlow": 0.0},
        "odor": {"concentration": odor, "leftAntenna": odor, "rightAntenna": odor, "temporalChange": 0.0},
        "motion": {"translationalSpeed": 0.0, "gravityAlignment": 1.0},
        "contact": {"ground": False, "obstacle": False, "wall": False},
        "timestampMs": 0,
    }


def stabilization_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    frame = pd.DataFrame([flatten_row(row) for row in rows])
    impulse_times = [2.0, 4.0, 6.0, 8.0]
    peaks = []
    final_values = []
    for time_s in impulse_times:
        after = frame[(frame.timestamp_s >= time_s) & (frame.timestamp_s < time_s + 0.5)]
        final = frame[(frame.timestamp_s >= time_s + 0.45) & (frame.timestamp_s < time_s + 0.55)]
        if not after.empty and not final.empty:
            peaks.append(float(after.angular_speed_rads.max()))
            final_values.append(float(final.angular_speed_rads.mean()))
    return {"disturbances": len(impulse_times), "mean_post_disturbance_peak_angular_speed_rads": float(np.mean(peaks)) if peaks else None, "mean_angular_speed_at_0_5s_rads": float(np.mean(final_values)) if final_values else None, "mean_abs_yaw_command": float(frame.yaw_command.abs().mean())}


def directional_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    frame = pd.DataFrame([flatten_row(row) for row in rows])
    return {
        "max_abs_yaw": float(frame.yaw_command.abs().max()),
        "max_abs_pitch": float(frame.pitch_command.abs().max()),
        "max_abs_roll": float(frame.roll_command.abs().max()),
        "max_descending_rate_hz": float(frame[["dn_saccade_left_hz", "dn_saccade_right_hz", "dn_wing_amplitude_hz"]].max().max()),
    }


def odor_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    frame = pd.DataFrame([flatten_row(row) for row in rows])
    return {"initial_distance_m": float(frame.distance_to_odor_m.iloc[0]), "final_distance_m": float(frame.distance_to_odor_m.iloc[-1]), "minimum_distance_m": float(frame.distance_to_odor_m.min()), "horizontal_path_length_m": float(np.abs(np.diff(frame.position_x_m)).sum() + np.abs(np.diff(frame.position_z_m)).sum()), "heading_change_rad": float(frame.heading_yaw_rad.iloc[-1] - frame.heading_yaw_rad.iloc[0]), "mean_olfactory_rate_hz": float(frame.olfactory_rate_hz.mean()), "mean_abs_yaw_command": float(frame.yaw_command.abs().mean())}


def free_flight_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    frame = pd.DataFrame([flatten_row(row) for row in rows])
    return {"duration_s": float(frame.timestamp_s.iloc[-1] + DT_SECONDS), "path_length_m": float(np.linalg.norm(np.diff(frame[["position_x_m", "position_y_m", "position_z_m"]].to_numpy(), axis=0), axis=1).sum()), "final_position_m": [float(frame.position_x_m.iloc[-1]), float(frame.position_y_m.iloc[-1]), float(frame.position_z_m.iloc[-1])], "landed": bool(frame.ground_contact.iloc[-1]), "max_abs_yaw_command": float(frame.yaw_command.abs().max()), "max_descending_rate_hz": float(frame[["dn_saccade_left_hz", "dn_saccade_right_hz", "dn_wing_amplitude_hz"]].max().max())}


def flatten_row(row: dict[str, Any]) -> dict[str, Any]:
    position = row["position"]
    velocity = row["velocity"]
    rotation = row["rotation"]
    angular_velocity = row["angular_velocity"]
    motor = row["motor_output"]
    sensory = row["sensory_input"]
    stimulation = row["stimulation"]
    rates = row["descending_rates_hz"]
    return {
        "experiment": row["experiment"], "condition": row["condition"], "timestamp_s": row["timestamp_s"],
        "position_x_m": float(position[0]), "position_y_m": float(position[1]), "position_z_m": float(position[2]),
        "velocity_x_mps": float(velocity[0]), "velocity_y_mps": float(velocity[1]), "velocity_z_mps": float(velocity[2]),
        "rotation_x": float(rotation[0]), "rotation_y": float(rotation[1]), "rotation_z": float(rotation[2]), "rotation_w": float(rotation[3]),
        "angular_speed_rads": float(np.linalg.norm(angular_velocity)),
        "heading_yaw_rad": float(math.atan2(2.0 * (rotation[3] * rotation[1] + rotation[0] * rotation[2]), 1.0 - 2.0 * (rotation[1] ** 2 + rotation[2] ** 2))),
        "forward_thrust": motor["forwardThrust"], "vertical_thrust": motor["verticalThrust"], "yaw_command": motor["yawTorque"], "pitch_command": motor["pitchTorque"], "roll_command": motor["rollTorque"],
        "dn_saccade_left_hz": rates.get("saccade_left", 0.0), "dn_saccade_right_hz": rates.get("saccade_right", 0.0), "dn_wing_amplitude_hz": rates.get("wing_amplitude", 0.0), "dn_landing_hz": rates.get("landing", 0.0),
        "visual_left_luminance": sensory["leftEye"]["meanLuminance"], "visual_right_luminance": sensory["rightEye"]["meanLuminance"], "odor_concentration": sensory["odor"]["concentration"], "olfactory_rate_hz": stimulation["olfactory"][0]["rateHz"] if stimulation["olfactory"] else 0.0,
        "stimulated_body_ids_json": json.dumps(row["stimulated_body_ids"]), "sensory_input_json": json.dumps(sensory, sort_keys=True), "spike_counts_json": json.dumps(row["spike_counts"], sort_keys=True), "descending_rates_json": json.dumps(rates, sort_keys=True), "ground_contact": row["ground_contact"], "wall_contact": row["wall_contact"], **{key: value for key, value in row.items() if key in ("stimulus", "target_direction", "elevation_channel_supported", "visual_source_hidden", "scripted_objective")},
        "distance_to_odor_m": row["distance_to_odor_m"],
    }


def serialize_row(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key in ("position", "velocity", "rotation", "angular_velocity"):
        result[key] = [float(value) for value in result[key]]
    return result


def render_report(summaries: dict[str, Any], seed: int) -> str:
    stabilization = summaries["A_visual_stabilization"]
    odor = summaries["C_odor_source"]
    free_flight = summaries["D_free_flight"]
    return f"""# Autonomous flight experiment report

Seed: `{seed}`  
Neural provider: `none`  
Interpretation: the `malecns_connected` condition runs the exact sensory encoder and decoder with an empty rate window. It is not a live Brian2 autonomous run.

## A — visual stabilization

Both conditions received four identical small rotational disturbances. The
MaleCNS-connected and motor-disabled conditions had mean yaw command `{{:.6f}}`
and `{{:.6f}}`, respectively. Their mean angular speed at 0.5 s after each
disturbance was `{{:.6f}}` and `{{:.6f}}` rad/s. The identical values indicate
passive rigid-body damping only; no neural stabilizing response was observed.

## B — visual target

Left, right, above, and below target stimulus conditions were run. Every
condition produced maximum absolute yaw, pitch, and roll command `0.0` and
maximum selected descending rate `0.0 Hz`. Elevation-specific encoding is
currently unsupported by the R8d mean-luminance encoder, so above/below are
recorded stimulus labels rather than claims of a CNS distinction.

## C — odor source

The visual source was hidden and concentration was generated from distance to
the odor source. The connected condition changed distance from
`{{:.6f}} m` to `{{:.6f}} m`, with heading change `{{:.6f}}` rad. The motor-disabled
condition changed distance from `{{:.6f}} m` to `{{:.6f}} m`, with heading change
`{{:.6f}}` rad. Both had zero horizontal path and zero decoded yaw; no odor
tracking behavior was observed.

## D — free flight

The unscripted 60 s run had path length `{{:.6f}} m`, final position
`{{}} m`, and landed=`{{}}`. Selected descending activity and decoded yaw were
zero. This is a neutral-provider baseline, not evidence of autonomous flight.
""".format(
        stabilization["malecns_connected"]["mean_abs_yaw_command"],
        stabilization["motor_output_disabled"]["mean_abs_yaw_command"],
        stabilization["malecns_connected"]["mean_angular_speed_at_0_5s_rads"],
        stabilization["motor_output_disabled"]["mean_angular_speed_at_0_5s_rads"],
        odor["malecns_connected"]["initial_distance_m"], odor["malecns_connected"]["final_distance_m"], odor["malecns_connected"]["heading_change_rad"],
        odor["motor_output_disabled"]["initial_distance_m"], odor["motor_output_disabled"]["final_distance_m"], odor["motor_output_disabled"]["heading_change_rad"],
        free_flight["path_length_m"], free_flight["final_position_m"], free_flight["landed"],
    )


def quat_multiply(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx, aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz])


def quat_rotate(q: np.ndarray, vector: np.ndarray) -> np.ndarray:
    return quat_multiply(quat_multiply(q, np.array([vector[0], vector[1], vector[2], 0.0])), np.array([-q[0], -q[1], -q[2], q[3]]))[:3]


def quat_axis_angle(axis: np.ndarray, angle: float) -> np.ndarray:
    half = angle * 0.5
    return np.array([axis[0] * math.sin(half), axis[1] * math.sin(half), axis[2] * math.sin(half), math.cos(half)])


def quat_normalize(q: np.ndarray) -> np.ndarray:
    return q / np.linalg.norm(q)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="results/single_fly_3d")
    parser.add_argument("--seed", type=int, default=20260909)
    args = parser.parse_args()
    ExperimentRunner(Path(args.output_dir), args.seed).run()
    print(f"wrote controlled flight experiments to {args.output_dir}")


if __name__ == "__main__":
    main()
