from __future__ import annotations

import argparse
import json
from pathlib import Path


CHANNELS = ("resource", "motion", "odorA", "odorB", "light", "chaos")


def run_sweep() -> dict[str, object]:
    """Describe a reproducible sweep; live CNS measurements are not invented."""

    return {
        "version": "sensory-calibration-v1",
        "status": "placeholder_until_live_malecns",
        "measured": False,
        "channels": {
            channel: {
                "minimumDetectable": None,
                "usefulRange": None,
                "strongResponse": None,
                "saturation": None,
                "sweep": [round(index / 20, 2) for index in range(21)],
            }
            for channel in CHANNELS
        },
        "recordedOutputs": ["totalSpikes", "sensorySpikes", "downstreamActivity", "descendingActivity", "decodedCommand"],
        "note": "Run against the live MaleCNS runtime before filling operating ranges; this file does not claim biological measurements.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the sensory sweep calibration template")
    parser.add_argument("--output", type=Path, default=Path("config/sensory_calibration.v1.json"))
    args = parser.parse_args()
    payload = run_sweep()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
