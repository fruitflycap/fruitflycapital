from __future__ import annotations

from dataclasses import dataclass

from ..models import TokenState
from .pipeline import FinancialSensoryPipeline


@dataclass(frozen=True)
class FactorAblation:
    """Offline factor ablation interface; it does not evaluate profitability."""

    pipeline: FinancialSensoryPipeline

    def evaluate(self, state: TokenState, excluded_factors: set[str] | None = None) -> dict[str, object]:
        result = self.pipeline.ablate(state, excluded_factors or set())
        return {
            "excludedFactors": sorted(excluded_factors or set()),
            "financialState": result.as_dict(),
            "outcomeEvaluation": "not_implemented",
        }
