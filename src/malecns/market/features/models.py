from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class RuntimeFeature:
    feature_id: str
    raw_value: Any
    normalized_value: float
    confidence: float
    freshness: float
    source: str
    observed_at_ms: int
    provenance: tuple[Mapping[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "featureId": self.feature_id,
            "rawValue": self.raw_value,
            "normalizedValue": self.normalized_value,
            "confidence": self.confidence,
            "freshness": self.freshness,
            "source": self.source,
            "observedAtMs": self.observed_at_ms,
            "provenance": [dict(item) for item in self.provenance],
        }


@dataclass(frozen=True)
class FactorValue:
    factor_id: str
    value: float
    confidence: float
    available: bool
    value_type: str
    contributions: tuple[Mapping[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "factorId": self.factor_id,
            "value": self.value,
            "confidence": self.confidence,
            "available": self.available,
            "valueType": self.value_type,
            "contributions": [dict(item) for item in self.contributions],
        }


@dataclass(frozen=True)
class InvestabilityResult:
    eligible: bool
    severity: str
    reasons: tuple[str, ...] = ()
    facts: tuple[Mapping[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "severity": self.severity,
            "reasons": list(self.reasons),
            "facts": [dict(item) for item in self.facts],
        }


@dataclass(frozen=True)
class FinancialState:
    version: str
    features: tuple[RuntimeFeature, ...] = ()
    factors: tuple[FactorValue, ...] = ()
    investability: InvestabilityResult | None = None
    provenance: tuple[Mapping[str, Any], ...] = ()
    sensory_trace: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "features": [feature.as_dict() for feature in self.features],
            "factors": [factor.as_dict() for factor in self.factors],
            "investability": self.investability.as_dict() if self.investability else None,
            "provenance": [dict(item) for item in self.provenance],
            "sensoryTrace": dict(self.sensory_trace),
        }
