from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..models import TokenState
from .guard import InvestabilityGuard
from .models import FactorValue, FinancialState, RuntimeFeature
from .normalization import FeatureNormalizer
from .registry import default_feature_registry


class FinancialFactorModel:
    def evaluate(self, features: tuple[RuntimeFeature, ...]) -> tuple[FactorValue, ...]:
        raise NotImplementedError


@dataclass(frozen=True)
class RuleBasedFinancialFactorModelV1(FinancialFactorModel):
    definitions: Mapping[str, Mapping[str, Any]]
    raw_feature_cap: float = 0.30

    @classmethod
    def from_file(cls, path: str | Path | None = None) -> "RuleBasedFinancialFactorModelV1":
        payload = _load_json(path, "financial_factors.v1.json")
        return cls(payload.get("factors", {}))

    def evaluate(self, features: tuple[RuntimeFeature, ...]) -> tuple[FactorValue, ...]:
        by_id = {feature.feature_id: feature for feature in features}
        result: list[FactorValue] = []
        for factor_id, definition in self.definitions.items():
            weights = definition.get("features", {}) if isinstance(definition, Mapping) else {}
            contributions: list[dict[str, Any]] = []
            weighted = 0.0
            total_weight = 0.0
            confidence = 0.0
            for feature_id, raw_weight in weights.items():
                feature = by_id.get(str(feature_id))
                if feature is None or feature.confidence <= 0:
                    continue
                weight = float(raw_weight)
                total_weight += weight
                uncapped_contribution = feature.normalized_value * weight
                contribution = max(-self.raw_feature_cap, min(self.raw_feature_cap, uncapped_contribution))
                weighted += contribution
                confidence += feature.confidence * weight
                contributions.append({
                    "featureId": feature_id,
                    "weight": weight,
                    "normalizedValue": feature.normalized_value,
                    "contribution": contribution,
                    "uncappedContribution": uncapped_contribution,
                    "capped": contribution != uncapped_contribution,
                })
            value_type = str(definition.get("valueType", "quality"))
            available = total_weight > 0
            value = weighted / total_weight if available else 0.0
            if value_type == "signed":
                value = value * 2.0 - 1.0
            result.append(FactorValue(factor_id, _clip_signed_or_unit(value, value_type), confidence / total_weight if available else 0.0, available, value_type, tuple(contributions)))
        return tuple(result)


@dataclass
class FinancialFactorEngine:
    model: FinancialFactorModel | None = None
    guard: InvestabilityGuard = InvestabilityGuard()
    normalizer: FeatureNormalizer = FeatureNormalizer()
    history_by_token: dict[str, dict[str, list[float]]] | None = None

    def __post_init__(self) -> None:
        if self.model is None:
            self.model = RuleBasedFinancialFactorModelV1.from_file()
        if self.history_by_token is None:
            self.history_by_token = {}

    def build_features(self, state: TokenState, *, now_ms: int | None = None) -> tuple[RuntimeFeature, ...]:
        raw = _raw_features(state)
        current_ms = state.observed_at_ms if now_ms is None else int(now_ms)
        if state.observed_at_ms > current_ms + 1_000:
            # A future observation is never allowed into a historical feature
            # baseline or factor calculation.
            return ()
        freshness = _freshness(current_ms - state.observed_at_ms)
        has_observed_data = bool(state.provenance) and any(value not in (None, 0, 0.0) for value in raw.values())
        history = self.history_by_token.setdefault(state.id, {})
        registry = default_feature_registry()
        features: list[RuntimeFeature] = []
        for feature_id, value in raw.items():
            definition = registry.get(feature_id)
            if definition is None or value is None:
                continue
            prior = history.setdefault(feature_id, [])
            normalized = self.normalizer.normalize(
                float(value), definition.normalization_method, history=prior,
                scale=_scale_for(feature_id),
            )
            prior.append(float(value))
            # Keep a bounded history and never include the current value in its
            # own baseline calculation.
            del prior[:-64]
            features.append(RuntimeFeature(feature_id, value, normalized, 1.0 if has_observed_data else 0.0, freshness, "derived-token-state", state.observed_at_ms, tuple(state.provenance)))
        return tuple(features)

    def evaluate(self, state: TokenState, *, now_ms: int | None = None) -> FinancialState:
        features = self.build_features(state, now_ms=now_ms)
        factors = self.model.evaluate(features) if self.model is not None else ()
        return FinancialState(
            version="financial-state-v1",
            features=features,
            factors=factors,
            investability=self.guard.evaluate(state),
            provenance=state.provenance,
        )


def _raw_features(state: TokenState) -> dict[str, float | None]:
    flow = state.flow
    total_count = flow.buy_count_5m + flow.sell_count_5m
    count_imbalance = (flow.buy_count_5m - flow.sell_count_5m) / total_count if total_count else 0.0
    liquidity_delta = state.liquidity.liquidity_delta_usd
    liquidity = state.liquidity.liquidity_usd
    market_cap_to_liquidity = state.liquidity.market_cap_to_liquidity
    fdv_to_liquidity = state.liquidity.fdv_to_liquidity
    volume_24h_to_market_cap = state.liquidity.volume_24h_to_market_cap
    volume_24h_to_liquidity = state.liquidity.volume_24h_to_liquidity
    return {
        "market.volume5m": state.market.volume_5m_usd,
        "market.volume15m": state.market.volume_15m_usd,
        "market.volume1h": state.market.volume_1h_usd,
        "market.volume24h": state.market.volume_24h_usd,
        "market.marketCap": state.market.market_cap_usd,
        "market.fdv": state.market.fdv_usd,
        "market.priceUsd": state.market.price_usd,
        "market.pairAgeHours": state.market.pair_age_hours,
        "market.cmcRank": state.market.cmc_rank,
        "market.circulatingSupply": state.market.circulating_supply,
        "market.cmcPercentChange7d": state.market.cmc_percent_change_7d,
        "market.cmcVolumeChange24h": state.market.cmc_volume_change_24h,
        "market.marketCapDominance": state.market.market_cap_dominance,
        "flow.buyCount5m": flow.buy_count_5m,
        "flow.sellCount5m": flow.sell_count_5m,
        "flow.buyUsd5m": flow.buy_usd_5m,
        "flow.sellUsd5m": flow.sell_usd_5m,
        "flow.imbalance": flow.flow_imbalance,
        "flow.txVelocity": flow.tx_velocity_5m,
        "flow.acceleration": flow.tx_acceleration,
        "flow.buySellCountImbalance": count_imbalance,
        "flow.accelerationMagnitude": abs(flow.tx_acceleration),
        "liquidity.absolute": liquidity,
        "liquidity.relative": None if liquidity_delta is None else liquidity_delta / max(liquidity - liquidity_delta, 1.0),
        "liquidity.stability": None if liquidity_delta is None else 1.0 - min(1.0, abs(liquidity_delta) / max(liquidity, 1.0)),
        "liquidity.volumeRatio": state.liquidity.volume_liquidity_ratio_1h,
        "liquidity.marketCapToLiquidity": market_cap_to_liquidity,
        "liquidity.fdvToLiquidity": fdv_to_liquidity,
        "liquidity.volume24hToMarketCap": volume_24h_to_market_cap,
        "liquidity.volume24hToLiquidity": volume_24h_to_liquidity,
        # Higher valuation per unit of executable LP means less immediate
        # depth relative to the value being represented. Keep this transform
        # bounded and explicit instead of hiding it in a sensory formula.
        "valuation.marketCapLiquidityQuality": _inverse_ratio_quality(market_cap_to_liquidity, 10.0),
        "valuation.fdvLiquidityQuality": _inverse_ratio_quality(fdv_to_liquidity, 10.0),
        "valuation.volumeToMarketCap": volume_24h_to_market_cap,
        "valuation.volumeToLiquidity": volume_24h_to_liquidity,
        "risk.liquidityStress": max(0.0, 1.0 - min(1.0, liquidity / 100_000.0)),
        "risk.flowInstability": abs(flow.flow_imbalance),
        "risk.volatility": abs(flow.tx_acceleration) / max(abs(flow.tx_velocity_5m), 1.0),
        "activity.volumeShock": state.market.volume_5m_usd / max(state.market.volume_1h_usd / 12.0, 1.0),
        "activity.txAcceleration": flow.tx_acceleration,
    }


def _scale_for(feature_id: str) -> float:
    if "liquidity" in feature_id and feature_id.endswith("absolute"):
        return 100_000.0
    if "volume1h" in feature_id:
        return 100_000.0
    if "marketCap" in feature_id or feature_id.endswith(".fdv"):
        return 1_000_000.0
    if feature_id.endswith("pairAgeHours"):
        return 720.0
    if feature_id.endswith("cmcRank"):
        return 100.0
    if feature_id.endswith("PercentChange7d") or feature_id.endswith("VolumeChange24h"):
        return 100.0
    if feature_id.endswith("Dominance"):
        return 100.0
    if "volume15m" in feature_id:
        return 25_000.0
    if "volume" in feature_id or "Usd" in feature_id:
        return 10_000.0
    if "Velocity" in feature_id or "acceleration" in feature_id:
        return 10.0
    return 1.0


def _inverse_ratio_quality(value: float | None, midpoint: float) -> float | None:
    if value is None or value < 0:
        return None
    return 1.0 / (1.0 + value / max(midpoint, 1e-9))


def _clip_signed_or_unit(value: float, value_type: str) -> float:
    if value_type == "signed":
        return min(1.0, max(-1.0, value))
    return min(1.0, max(0.0, value))


def _freshness(age_ms: int) -> float:
    """Five-minute half-life for sensory context; never extrapolates forward."""

    if age_ms <= 0:
        return 1.0
    return max(0.0, min(1.0, math.exp(-float(age_ms) / 300_000.0)))


def _load_json(path: str | Path | None, filename: str) -> dict[str, Any]:
    candidates = [Path(path)] if path else [Path.cwd() / "config" / filename, Path(__file__).resolve().parents[4] / "config" / filename]
    for candidate in candidates:
        if candidate.exists():
            return json.loads(candidate.read_text())
    raise FileNotFoundError(f"configuration file not found: {filename}")
