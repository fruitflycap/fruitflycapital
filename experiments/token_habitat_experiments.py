"""Audit the three synthetic token habitats through the embodied sensor contract.

This is intentionally a sensory/world experiment, not an autonomous behavior
claim. The browser currently has no live Brian2 rate provider, so the bodies
remain on the neutral decoded command. The outputs quantify what changes in
the physical habitat fields and the exact MaleCNS IDs stimulated in scenarios
A (OFF), B (DIFFERENT), and C (SWAPPED).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from malecns.brain.sensory_encoding import default_encoder


DT_SECONDS = 1.0 / 120.0
HABITAT_POSITIONS = np.array([[-0.67, -0.68], [0.64, -0.22], [0.58, 0.62]], dtype=float)
NEUTRAL = {"brightness": 0.16, "attractiveOdor": 0.0, "aversiveDanger": 0.0, "particleActivity": 0.0}
STATES = [
    {"id": "TOKEN-A", "label": "ACTIVE / HEALTHY", "activity": 0.88, "liquidityDepth": 0.92, "flowImbalance": 0.42, "volatility": 0.18, "socialActivity": 0.64, "risk": 0.08, "stableStructure": 0.92},
    {"id": "TOKEN-B", "label": "QUIET / STABLE", "activity": 0.18, "liquidityDepth": 0.86, "flowImbalance": 0.02, "volatility": 0.06, "socialActivity": 0.08, "risk": 0.06, "stableStructure": 0.96},
    {"id": "TOKEN-C", "label": "ACTIVE / DANGEROUS", "activity": 0.84, "liquidityDepth": 0.22, "flowImbalance": -0.25, "volatility": 0.90, "socialActivity": 0.72, "risk": 0.90, "stableStructure": 0.24},
]
FLY_POSITIONS = {"fly-a": np.array([-0.67, 0.48, -0.68]), "fly-b": np.array([0.64, 0.48, -0.22])}


def properties(state: dict[str, float | str]) -> dict[str, float]:
    activity = float(state["activity"])
    liquidity = float(state["liquidityDepth"])
    flow = float(state["flowImbalance"])
    volatility = float(state["volatility"])
    social = float(state["socialActivity"])
    risk = float(state["risk"])
    stable = float(state["stableStructure"])
    return {
        "brightness": min(1.0, 0.16 + activity * 0.42 + social * 0.18),
        "attractiveOdor": min(1.0, activity * 0.55 + liquidity * 0.25 + max(0.0, flow) * 0.2),
        "aversiveDanger": min(1.0, risk * 0.75 + volatility * 0.15 + (1.0 - stable) * 0.1),
        "particleActivity": min(1.0, activity * 0.7 + social * 0.2 + volatility * 0.1),
    }


def run(output_dir: Path, seed: int, duration_s: float) -> None:
    encoder = default_encoder()
    output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    scenario_names = {"off": "A_OFF", "different": "B_DIFFERENT", "swapped": "C_SWAPPED"}

    for scenario, experiment in scenario_names.items():
        position_order = HABITAT_POSITIONS[[1, 2, 0]] if scenario == "swapped" else HABITAT_POSITIONS
        state_order = [0, 1, 2]
        active_properties = [properties(state) for state in STATES] if scenario != "off" else [NEUTRAL.copy() for _ in STATES]
        for step in range(round(duration_s / DT_SECONDS)):
            time_s = step * DT_SECONDS
            for fly_id, position in FLY_POSITIONS.items():
                attractive = 0.0
                aversive = 0.0
                visual = []
                distances = []
                for habitat_position, habitat_properties in zip(position_order, active_properties):
                    horizontal_distance = float(np.linalg.norm(position[[0, 2]] - habitat_position))
                    distances.append(horizontal_distance)
                    sigma = 0.24
                    gaussian = np.exp(-(horizontal_distance**2 + position[1]**2) / (2.0 * sigma**2))
                    attractive += gaussian * habitat_properties["attractiveOdor"]
                    aversive += gaussian * habitat_properties["aversiveDanger"]
                    visual.append(habitat_properties["brightness"])
                closest = int(np.argmin(distances))
                sensor_frame = {
                    "leftEye": {"meanLuminance": visual[closest], "meanContrast": abs(visual[closest] - 0.12), "meanOpticFlow": 0.0},
                    "rightEye": {"meanLuminance": visual[closest], "meanContrast": abs(visual[closest] - 0.12), "meanOpticFlow": 0.0},
                    "odor": {"concentration": min(1.0, attractive), "leftAntenna": min(1.0, attractive), "rightAntenna": min(1.0, attractive), "aversiveConcentration": min(1.0, aversive), "temporalChange": 0.0},
                    "motion": {"translationalSpeed": 0.0, "gravityAlignment": 1.0},
                    "contact": {"ground": False, "obstacle": False, "wall": False},
                    "timestampMs": round(time_s * 1000),
                }
                stimulation = encoder.encode(sensor_frame)
                nonzero_entries = [entry for channel in ("visual", "olfactory", "mechanosensory") for entry in stimulation[channel] if entry["rateHz"] > 0]
                rows.append({
                    "experiment": experiment,
                    "scenario": scenario,
                    "fly_id": fly_id,
                    "timestamp_s": time_s,
                    "closest_habitat": STATES[state_order[closest]]["id"],
                    "attractive_odor": min(1.0, attractive),
                    "aversive_danger": min(1.0, aversive),
                    "nearest_horizontal_distance_m": distances[closest],
                    "near_any_habitat": min(distances) < 0.20,
                    "visual_luminance": visual[closest],
                    "encoded_body_ids": sorted(entry["bodyId"] for channel in ("visual", "olfactory", "mechanosensory") for entry in stimulation[channel]),
                    "stimulated_body_ids": sorted(entry["bodyId"] for entry in nonzero_entries),
                    "olfactory_stimulation_count": sum(entry["rateHz"] > 0 for entry in stimulation["olfactory"]),
                    "unimplemented": stimulation["unimplemented"],
                    "seed": seed,
                    "neural_provider": "none",
                    "motor_output": "neutral decoded command; no movement objective",
                })

    frame = pd.DataFrame(rows)
    frame.to_parquet(output_dir / "telemetry.parquet", index=False)
    frame.to_json(output_dir / "telemetry.json", orient="records", indent=2)
    frame[["experiment", "scenario", "fly_id", "timestamp_s", "nearest_horizontal_distance_m"]].to_csv(output_dir / "trajectory.csv", index=False)

    summaries: dict[str, object] = {}
    for (experiment, fly_id), group in frame.groupby(["experiment", "fly_id"]):
        near = group["near_any_habitat"].astype(bool)
        summaries[f"{experiment}/{fly_id}"] = {
            "time_near_any_habitat_s": float(near.sum() * DT_SECONDS),
            "entries_into_near_zone": int((near & ~near.shift(1, fill_value=False)).sum()),
            "exits_from_near_zone": int((~near & near.shift(1, fill_value=False)).sum()),
            "mean_attractive_odor": float(group["attractive_odor"].mean()),
            "mean_aversive_danger": float(group["aversive_danger"].mean()),
            "mean_visual_luminance": float(group["visual_luminance"].mean()),
            "unique_stimulated_body_ids": sorted({int(body_id) for ids in group["stimulated_body_ids"] for body_id in ids}),
            "olfactory_stimulation_count_mean": float(group["olfactory_stimulation_count"].mean()),
        }
    (output_dir / "summary.json").write_text(json.dumps(summaries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "experiment_config.json").write_text(json.dumps({"seed": seed, "duration_s": duration_s, "dt_seconds": DT_SECONDS, "scenarios": scenario_names, "token_states": STATES, "neural_provider": "none", "interpretation": "sensory audit only; no autonomous behavior claim"}, indent=2) + "\n", encoding="utf-8")

    means = frame.groupby("experiment")[["attractive_odor", "aversive_danger", "visual_luminance"]].mean()
    means.plot.bar(rot=0, figsize=(9, 4), color=["#58d5ff", "#ff7185", "#f5ce63"])
    plt.ylabel("normalized sensory value")
    plt.title("Synthetic token habitats: embodied sensory exposure")
    plt.tight_layout()
    plt.savefig(output_dir / "sensory_exposure.png", dpi=140)
    plt.close()
    (output_dir / "REPORT.md").write_text(render_report(summaries, seed, duration_s), encoding="utf-8")


def render_report(summaries: dict[str, object], seed: int, duration_s: float) -> str:
    return f"""# Token habitat experiment report

Seed: `{seed}`  
Duration per scenario: `{duration_s}` s  
Scenarios: `A_OFF`, `B_DIFFERENT`, `C_SWAPPED`

This run audits the embodied sensory fields only. The browser-side MaleCNS
adapter has no live Brian2 rate provider, so it supplies a neutral decoded
motor command and no movement behavior is claimed. `time_near`, entries, and
exits are therefore static-position baselines; they become behavioral metrics
once a validated neural provider is attached.

The OFF condition removes synthetic attractive odor, danger, and particle
activity and leaves only the neutral visual baseline. DIFFERENT places the
three synthetic states at their default sites.
SWAPPED rotates the state/site assignment. Token state names are mock labels,
not live market data or real token identity.

The exact MaleCNS IDs stimulated by the current visual/olfactory encoder are
preserved in `summary.json` and `telemetry.parquet`. Aversive danger is shown
as a world/debug field but is explicitly listed as unimplemented in the
MaleCNS sensory adapter; it is not silently mapped to a receptor population.
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="results/token_habitats")
    parser.add_argument("--seed", type=int, default=20260909)
    parser.add_argument("--duration-s", type=float, default=10.0)
    args = parser.parse_args()
    run(Path(args.output_dir), args.seed, args.duration_s)
    print(f"wrote token habitat sensory audit to {args.output_dir}")


if __name__ == "__main__":
    main()
