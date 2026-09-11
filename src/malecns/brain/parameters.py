"""Versioned parameters for the Shiu-method MaleCNS reference model."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class LIFParameters:
    """Plain-number parameters; Brian2 units are applied at model creation.

    Values copied from the published reference implementation are marked
    ``PUBLISHED_SHIU`` in ``docs/MODEL_ASSUMPTIONS.md``. ``dt_ms`` is explicit
    here because the original code relied on Brian2's defaultclock timestep.
    """

    v_0_mV: float = -52.0
    v_reset_mV: float = -52.0
    v_threshold_mV: float = -45.0
    membrane_time_ms: float = 20.0
    synaptic_time_ms: float = 5.0
    refractory_ms: float = 2.2
    delay_ms: float = 1.8
    synapse_scale_mV: float = 0.275
    poisson_default_hz: float = 150.0
    poisson_second_hz: float = 0.0
    poisson_scale: float = 250.0
    dt_ms: float = 0.1
    parameter_version: str = "shiu-male-cns-v1"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "LIFParameters":
        values = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(**values)
