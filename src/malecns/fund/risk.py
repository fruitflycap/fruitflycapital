"""Risk gate between target weights and any future custody/execution adapter."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .allocation import PortfolioTarget


@dataclass(frozen=True)
class RiskResult:
    habitat_id: str
    allowed: bool
    reason: str
    target_weight: float

    def as_dict(self) -> dict[str, Any]:
        return {
            "habitatId": self.habitat_id,
            "allowed": self.allowed,
            "reason": self.reason,
            "targetWeight": round(self.target_weight, 6),
        }


class RiskGuard:
    """Apply explicit portfolio constraints without signing or sending txs."""

    def __init__(
        self,
        *,
        max_total_exposure: float = 0.90,
        max_position_weight: float = 0.18,
        min_confidence: float = 0.50,
        require_human_signature: bool = True,
    ) -> None:
        self.max_total_exposure = float(max_total_exposure)
        self.max_position_weight = float(max_position_weight)
        self.min_confidence = float(min_confidence)
        self.require_human_signature = require_human_signature

    def evaluate(self, targets: Iterable[PortfolioTarget]) -> tuple[RiskResult, ...]:
        ordered = tuple(sorted(targets, key=lambda item: item.habitat_id))
        total = sum(max(0.0, target.target_weight) for target in ordered)
        results: list[RiskResult] = []
        for target in ordered:
            reason = "approved for proposal-only review"
            allowed = True
            if target.target_weight > self.max_position_weight + 1e-9:
                allowed = False
                reason = "position cap exceeded"
            elif total > self.max_total_exposure + 1e-9:
                allowed = False
                reason = "total exposure cap exceeded"
            elif target.target_weight > 0 and target.confidence < self.min_confidence:
                allowed = False
                reason = "temporal evidence confidence below threshold"
            elif target.target_weight <= 0:
                reason = "no qualified target weight"
            results.append(RiskResult(target.habitat_id, allowed, reason, target.target_weight))
        return tuple(results)
