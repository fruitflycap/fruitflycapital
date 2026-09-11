"""Run a reproducible one-fly live MaleCNS sensorimotor smoke test.

This experiment reports the actual cached Brian2 activity for neutral,
lateralized visual, and odor-only frames. It does not tune parameters or turn
the result into a target-following rule.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from malecns.brain.realtime import LiveMaleCNSRuntime
from malecns.brain.sensory_encoding import default_encoder


def _case_frame(name: str) -> dict[str, Any]:
    if name == "neutral":
        return {"leftEye": {"meanLuminance": 0.0}, "rightEye": {"meanLuminance": 0.0}, "odor": {"concentration": 0.0}}
    if name == "visual_left":
        return {"leftEye": {"meanLuminance": 1.0}, "rightEye": {"meanLuminance": 0.0}, "odor": {"concentration": 0.0}}
    if name == "visual_right":
        return {"leftEye": {"meanLuminance": 0.0}, "rightEye": {"meanLuminance": 1.0}, "odor": {"concentration": 0.0}}
    if name == "odor_only":
        return {"leftEye": {"meanLuminance": 0.0}, "rightEye": {"meanLuminance": 0.0}, "odor": {"concentration": 1.0}}
    raise ValueError(f"Unknown smoke-test case: {name}")


def run_case(cache_dir: Path, encoder: Any, name: str, seed: int, windows: int, window_ms: float) -> dict[str, Any]:
    runtime = LiveMaleCNSRuntime(cache_dir, seed=seed, window_ms=window_ms)
    stimulation = encoder.encode(_case_frame(name))
    steps = [runtime.step(stimulation) for _ in range(windows)]
    last = steps[-1]
    return {
        "case": name,
        "windows": windows,
        "window_ms": window_ms,
        "stimulated_body_counts": {
            key: len(value) for key, value in stimulation.items() if isinstance(value, list)
        },
        "total_spikes": sum(sum(step.spike_counts.values()) for step in steps),
        "last_window_spiking_body_count": len(last.spike_counts),
        "last_window_descending_rates_hz": last.decoded.descending_rates_hz,
        "last_window_flight_command": last.decoded.command.as_dict(),
        "last_window_spike_body_count": len(last.spike_rates),
        "unimplemented": stimulation["unimplemented"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/runtime/malecns-realtime-3hop"))
    parser.add_argument("--output", type=Path, default=Path("results/live_malecns_smoke.json"))
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--windows", type=int, default=4)
    parser.add_argument("--window-ms", type=float, default=50.0)
    args = parser.parse_args()
    if args.windows <= 0:
        raise ValueError("--windows must be positive")
    encoder = default_encoder()
    report = {
        "graph": "official MaleCNS v1.0 weighted Feather",
        "cache_manifest": json.loads((args.cache_dir / "manifest.json").read_text(encoding="utf-8")),
        "seed": args.seed,
        "cases": [run_case(args.cache_dir, encoder, name, args.seed, args.windows, args.window_ms) for name in (
            "neutral", "visual_left", "visual_right", "odor_only"
        )],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for case in report["cases"]:
        print(
            f"{case['case']}: spikes={case['total_spikes']} "
            f"DN={case['last_window_descending_rates_hz']} "
            f"command={case['last_window_flight_command']}"
        )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
