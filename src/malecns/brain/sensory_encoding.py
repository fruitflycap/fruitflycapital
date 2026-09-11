"""Conservative sensory-to-MaleCNS population encoding.

This module consumes sensory observables only. It never accepts or emits a
target/source coordinate. Body IDs come from the checked-in mapping generated
from the official MaleCNS annotation table.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class StimulationEntry:
    body_id: int
    rate_hz: float
    population: str

    def as_dict(self) -> dict[str, Any]:
        return {"bodyId": self.body_id, "rateHz": round(self.rate_hz, 6), "population": self.population}


class MaleCNSSensoryEncoder:
    """Map perceptual summaries to documented MaleCNS input populations.

    ``max_rate_hz`` is an explicit OUR_ASSUMPTION rate encoder. The structural
    IDs and side assignments are MALECNS_DATA; no CNS edges are added here.
    """

    def __init__(self, rows: Iterable[dict[str, str]], *, max_rate_hz: float = 150.0) -> None:
        self.max_rate_hz = max_rate_hz
        rows = list(rows)
        self.visual_left = self._ids(rows, "visual_R8d", "L")
        self.visual_right = self._ids(rows, "visual_R8d", "R")
        # Keep the bilateral ORN/JO identities separate. A single averaged
        # odor rate made every fly receive the same olfactory drive, so the
        # CNS could not express a left/right turn from an odor gradient.
        self.olfactory_left = self._ids(rows, "olfactory_ORN_DA1", "L")
        self.olfactory_right = self._ids(rows, "olfactory_ORN_DA1", "R")
        self.mechanosensory_left = self._ids(rows, "mechanosensory_auditory_JO-B1_b", "L")
        self.mechanosensory_right = self._ids(rows, "mechanosensory_auditory_JO-B1_b", "R")

    @classmethod
    def from_csv(cls, path: str | Path) -> "MaleCNSSensoryEncoder":
        with Path(path).open(newline="", encoding="utf-8") as handle:
            return cls(list(csv.DictReader(handle)))

    def encode(self, sensors: dict[str, Any]) -> dict[str, Any]:
        left_eye = _mapping(sensors.get("leftEye"))
        right_eye = _mapping(sensors.get("rightEye"))
        odor = _mapping(sensors.get("odor"))
        visual = self._entries(self.visual_left, _visual_rate(left_eye, self.max_rate_hz), "R8d")
        visual += self._entries(self.visual_right, _visual_rate(right_eye, self.max_rate_hz), "R8d")
        concentration = _number(odor.get("concentration"))
        left_odor = _number(odor.get("leftAntenna"), concentration)
        right_odor = _number(odor.get("rightAntenna"), concentration)
        olfactory = self._entries(self.olfactory_left, _bounded_rate(left_odor, self.max_rate_hz), "ORN_DA1")
        olfactory += self._entries(self.olfactory_right, _bounded_rate(right_odor, self.max_rate_hz), "ORN_DA1")
        # JO-B1_b is the documented mechanosensory population available in
        # the mapping. We use it for measured optic-flow/body-motion/contact
        # drive; this is an explicit rate-encoder assumption, not a claim that
        # the annotation names a complete flight controller.
        motion = _mapping(sensors.get("motion"))
        contact = _mapping(sensors.get("contact"))
        flow_left = _number(left_eye.get("meanOpticFlow"))
        flow_right = _number(right_eye.get("meanOpticFlow"))
        body_speed = _number(motion.get("translationalSpeed"))
        angular_speed = abs(_number(_mapping(motion.get("angularVelocity")).get("y")))
        contact_drive = 1.0 if any(bool(contact.get(name)) for name in ("ground", "obstacle", "wall")) else 0.0
        mech_left_rate = _bounded_rate(max(flow_left, body_speed * 4.0, angular_speed * 0.1, contact_drive), self.max_rate_hz)
        mech_right_rate = _bounded_rate(max(flow_right, body_speed * 4.0, angular_speed * 0.1, contact_drive), self.max_rate_hz)
        mechanosensory = self._entries(self.mechanosensory_left, mech_left_rate, "JO-B1_b")
        mechanosensory += self._entries(self.mechanosensory_right, mech_right_rate, "JO-B1_b")
        return {
            "visual": [entry.as_dict() for entry in visual],
            "olfactory": [entry.as_dict() for entry in olfactory],
            "mechanosensory": [entry.as_dict() for entry in mechanosensory],
            "unimplemented": [
                "aversive_odor_to_maleCNS",
                "wind_to_maleCNS_mechanosensory",
                "gravity_to_maleCNS_mechanosensory",
            ],
        }

    def _ids(self, rows: Iterable[dict[str, str]], population: str, side: str | None) -> list[int]:
        selected = []
        for row in rows:
            if row.get("population") != population:
                continue
            if side is not None and row.get("side_for_registry") != side:
                continue
            selected.append(int(row["bodyId"]))
        return sorted(selected)

    def _entries(self, body_ids: Iterable[int], rate_hz: float, population: str) -> list[StimulationEntry]:
        return [StimulationEntry(body_id, rate_hz, population) for body_id in body_ids]


def default_encoder() -> MaleCNSSensoryEncoder:
    mapping = Path(__file__).resolve().parents[3] / "data" / "mappings" / "malecns_sensory_motor_ids.csv"
    return MaleCNSSensoryEncoder.from_csv(mapping)


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: Any, fallback: float = 0.0) -> float:
    return float(value) if isinstance(value, (int, float)) else float(fallback)


def _visual_rate(eye: dict[str, Any], max_rate_hz: float) -> float:
    # Brightness remains the primary visual drive. Optic flow is additive but
    # bounded so motion cannot erase the left/right luminance distinction.
    luminance = _number(eye.get("meanLuminance"))
    optic_flow = _number(eye.get("meanOpticFlow"))
    return _bounded_rate(min(1.0, luminance + optic_flow * 0.35), max_rate_hz)


def _bounded_rate(value: float, max_rate_hz: float = 150.0) -> float:
    return min(max_rate_hz, max(0.0, value * max_rate_hz))
