from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import FinancialState


@dataclass(frozen=True)
class SensoryEncoding:
    resource: float
    motion: float
    odor_a: float
    odor_b: float
    light: float
    chaos: float
    trace: dict[str, Any]


@dataclass(frozen=True)
class MultidimensionalSensoryEncoder:
    mapping: dict[str, Any]

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "MultidimensionalSensoryEncoder":
        candidates = [Path(path)] if path else [Path.cwd() / "config" / "sensory_mapping.v1.json", Path(__file__).resolve().parents[4] / "config" / "sensory_mapping.v1.json"]
        for candidate in candidates:
            if candidate.exists():
                return cls(json.loads(candidate.read_text()))
        raise FileNotFoundError("configuration file not found: sensory_mapping.v1.json")

    def encode(self, financial: FinancialState) -> SensoryEncoding:
        channels = {name: 0.0 for name in ("resource", "motion", "odorA", "odorB", "light", "chaos")}
        factor_trace: dict[str, dict[str, float]] = {}
        matrix = self.mapping.get("factorMatrix", {})
        factor_cap = float(self.mapping.get("contributionCaps", {}).get("factor", 0.38))
        for factor in financial.factors:
            if not factor.available or factor.confidence <= 0:
                continue
            signed_value = factor.value
            contributions: dict[str, float] = {}
            for channel, coefficient in (matrix.get(factor.factor_id, {}) or {}).items():
                raw = float(coefficient) * signed_value * factor.confidence
                contribution = max(-factor_cap, min(factor_cap, raw))
                channels[channel] = channels.get(channel, 0.0) + contribution
                contributions[channel] = contribution
            factor_trace[factor.factor_id] = contributions

        caps = self.mapping.get("channels", {})
        bounded: dict[str, float] = {}
        for channel, value in channels.items():
            cap = float((caps.get(channel) or {}).get("cap", 1.0))
            gain = float((caps.get(channel) or {}).get("gain", 1.0))
            bounded[channel] = _clip((value * gain + (0.22 if channel in {"resource", "light"} else 0.0)) / max(cap, 1e-9))
        return SensoryEncoding(
            bounded["resource"], bounded["motion"], bounded["odorA"], bounded["odorB"], bounded["light"], bounded["chaos"],
            {"version": self.mapping.get("version", "unknown"), "factorContributions": factor_trace, "channelStrengths": bounded},
        )


def _clip(value: float) -> float:
    return min(1.0, max(0.0, float(value)))
