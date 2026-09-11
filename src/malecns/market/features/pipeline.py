from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..models import TokenState
from .factors import FinancialFactorEngine
from .models import FinancialState


@dataclass
class FinancialSensoryPipeline:
    """Financial state builder kept separate from provider and CNS code."""

    factor_engine: FinancialFactorEngine

    @classmethod
    def default(cls) -> "FinancialSensoryPipeline":
        return cls(FinancialFactorEngine())

    def evaluate(self, state: TokenState) -> FinancialState:
        return self.factor_engine.evaluate(state)

    def ablate(self, state: TokenState, excluded_factors: set[str]) -> FinancialState:
        result = self.evaluate(state)
        factors = tuple(item for item in result.factors if item.factor_id not in excluded_factors)
        return FinancialState(result.version, result.features, factors, result.investability, result.provenance, result.sensory_trace)

    def trace(self, state: TokenState) -> dict[str, Any]:
        return self.evaluate(state).as_dict()
