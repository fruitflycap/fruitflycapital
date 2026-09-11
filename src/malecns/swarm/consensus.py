"""Temporal, evidence-bearing conversion of swarm behavior into conviction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .observer import HabitatSwarmSummary


@dataclass(frozen=True)
class HabitatConviction:
    habitat_id: str
    conviction: float
    confidence: float
    qualified: bool
    evidence: dict[str, float]

    def as_dict(self) -> dict[str, Any]:
        return {
            "habitatId": self.habitat_id,
            "conviction": round(self.conviction, 6),
            "confidence": round(self.confidence, 6),
            "qualified": self.qualified,
            "evidence": {key: round(value, 6) for key, value in self.evidence.items()},
        }


class TemporalConsensusEngine:
    """Use repeated and sustained behavior, not a one-frame headcount.

    The weights are explicitly project assumptions. They are not biological
    parameters and do not alter MaleCNS activity. They remain configurable so
    an experiment can report exactly which decision rule was used.
    """

    def __init__(
        self,
        *,
        min_observation_span_s: float = 10.0,
        min_visitors: int = 2,
        min_conviction: float = 0.55,
        weights: dict[str, float] | None = None,
    ) -> None:
        self.min_observation_span_s = max(0.0, float(min_observation_span_s))
        self.min_visitors = max(1, int(min_visitors))
        self.min_conviction = _clip(float(min_conviction))
        configured = weights or {
            "visitCoverage": 0.22,
            "sustainedDwell": 0.24,
            "repeatVisits": 0.18,
            "lowDeparture": 0.16,
            "persistence": 0.12,
            "congregation": 0.08,
        }
        total = sum(max(0.0, value) for value in configured.values()) or 1.0
        self.weights = {key: max(0.0, value) / total for key, value in configured.items()}

    def evaluate(self, summaries: Iterable[HabitatSwarmSummary]) -> tuple[HabitatConviction, ...]:
        result: list[HabitatConviction] = []
        for summary in summaries:
            expected = max(1, summary.expected_agents)
            evidence = {
                "visitCoverage": _clip(summary.visitor_count / expected),
                "sustainedDwell": _clip(summary.sustained_dwell_count / expected),
                "repeatVisits": _clip(summary.repeat_visit_rate),
                "lowDeparture": 1.0 - _clip(summary.departure_rate),
                "persistence": _clip(summary.persistence),
                "congregation": _clip(summary.local_congregation / max(1, expected - 1)),
            }
            conviction = _clip(sum(self.weights.get(key, 0.0) * value for key, value in evidence.items()))
            coverage_confidence = _clip(summary.observed_agents / expected)
            temporal_confidence = _clip(summary.observation_span_s / max(self.min_observation_span_s, 1e-9))
            confidence = coverage_confidence * temporal_confidence
            qualified = (
                summary.visitor_count >= self.min_visitors
                and summary.observation_span_s >= self.min_observation_span_s
                and conviction >= self.min_conviction
            )
            result.append(HabitatConviction(summary.habitat_id, conviction, confidence, qualified, evidence))
        return tuple(sorted(result, key=lambda item: item.habitat_id))


def _clip(value: float) -> float:
    return min(1.0, max(0.0, float(value)))
