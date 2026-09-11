from __future__ import annotations

import argparse
import json
from pathlib import Path

from malecns.market.features.models import FactorValue, FinancialState
from malecns.market.features.sensory import MultidimensionalSensoryEncoder


def audit() -> dict[str, object]:
    factors = tuple(
        FactorValue(name, value, 1.0, True, "quality", ())
        for name, value in (
            ("liquidity_quality", 0.8),
            ("market_quality", 0.6),
            ("activity", 0.7),
            ("risk_intensity", 0.2),
        )
    )
    financial = FinancialState("financial-state-v1", factors=factors)
    encoded = MultidimensionalSensoryEncoder.from_file().encode(financial)
    channel = encoded.trace["channelStrengths"]
    return {
        "version": "sensory-dominance-v1",
        "status": "theoretical_only",
        "factorContributions": encoded.trace["factorContributions"],
        "channelStrengths": channel,
        "dominantChannel": max(channel, key=channel.get),
        "cnsResponse": "unavailable_until_live_malecns_calibration",
        "saturationFrequency": "unavailable_until_empirical_sweep",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit sensory dominance before live CNS calibration")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = audit()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
