"""Deterministic target-weight allocation from temporal conviction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from malecns.swarm.consensus import HabitatConviction


@dataclass(frozen=True)
class PortfolioTarget:
    habitat_id: str
    target_weight: float
    conviction: float
    confidence: float
    rationale: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "habitatId": self.habitat_id,
            "targetWeight": round(self.target_weight, 6),
            "conviction": round(self.conviction, 6),
            "confidence": round(self.confidence, 6),
            "rationale": self.rationale,
        }


class PortfolioAllocator:
    """Convert qualified convictions into capped portfolio targets.

    The position cap and cash reserve are fund-policy assumptions, not claims
    about the fly nervous system. Allocation is target-only; it does not
    calculate a token price or broadcast a transaction.
    """

    def __init__(
        self,
        *,
        max_position_weight: float = 0.18,
        cash_reserve_weight: float = 0.10,
        min_conviction: float = 0.55,
    ) -> None:
        if max_position_weight <= 0 or cash_reserve_weight < 0 or max_position_weight > 1:
            raise ValueError("invalid allocation limits")
        if max_position_weight + cash_reserve_weight > 1:
            raise ValueError("position cap plus cash reserve cannot exceed 1")
        self.max_position_weight = float(max_position_weight)
        self.cash_reserve_weight = float(cash_reserve_weight)
        self.min_conviction = float(min_conviction)

    def allocate(self, convictions: Iterable[HabitatConviction]) -> tuple[PortfolioTarget, ...]:
        items = tuple(convictions)
        scores = {
            item.habitat_id: max(0.0, item.conviction - self.min_conviction) * item.confidence
            for item in items
            if item.qualified and item.conviction >= self.min_conviction
        }
        weights = _capped_proportional_weights(scores, 1.0 - self.cash_reserve_weight, self.max_position_weight)
        return tuple(
            PortfolioTarget(
                habitat_id=item.habitat_id,
                target_weight=weights.get(item.habitat_id, 0.0),
                conviction=item.conviction,
                confidence=item.confidence,
                rationale=("qualified temporal swarm behavior" if item.qualified else "not qualified; target remains zero"),
            )
            for item in sorted(items, key=lambda candidate: candidate.habitat_id)
        )


def _capped_proportional_weights(scores: dict[str, float], available: float, cap: float) -> dict[str, float]:
    result = {key: 0.0 for key in scores}
    remaining_keys = {key for key, score in scores.items() if score > 0}
    remaining = max(0.0, available)
    while remaining_keys and remaining > 1e-9:
        total_score = sum(scores[key] for key in remaining_keys)
        if total_score <= 0:
            break
        capped = set()
        for key in remaining_keys:
            proposed = remaining * scores[key] / total_score
            if proposed >= cap:
                result[key] = cap
                capped.add(key)
        if not capped:
            for key in remaining_keys:
                result[key] = remaining * scores[key] / total_score
            break
        remaining -= sum(result[key] for key in capped)
        remaining_keys -= capped
    return result
