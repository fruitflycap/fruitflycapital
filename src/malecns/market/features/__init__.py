"""Provider-neutral financial features, factors, safety, and sensory mapping."""

from .factors import FinancialFactorEngine, RuleBasedFinancialFactorModelV1
from .guard import InvestabilityGuard
from .models import FactorValue, FinancialState, InvestabilityResult, RuntimeFeature
from .normalization import FeatureNormalizer
from .pipeline import FinancialSensoryPipeline
from .sensory import MultidimensionalSensoryEncoder, SensoryEncoding

__all__ = [
    "FactorValue",
    "FeatureNormalizer",
    "FinancialFactorEngine",
    "FinancialSensoryPipeline",
    "FinancialState",
    "InvestabilityGuard",
    "InvestabilityResult",
    "RuleBasedFinancialFactorModelV1",
    "RuntimeFeature",
    "MultidimensionalSensoryEncoder",
    "SensoryEncoding",
]
