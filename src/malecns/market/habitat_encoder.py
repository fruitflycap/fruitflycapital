"""Translate provider-neutral token signals into physical habitat fields."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .features.factors import FinancialFactorEngine
from .features.sensory import MultidimensionalSensoryEncoder
from .models import FlowState, LiquidityState, MarketState, Signal, TokenState


@dataclass(frozen=True)
class PhysicalHabitatState:
    id: str
    label: str
    physical_radius_m: float
    resource_pile_radius_m: float
    visual_motion_intensity: float
    brightness: float
    particle_activity: float
    chaos: float
    attractive_odor: float
    aversive_danger: float
    image_url: str | None = None
    semantic_type: str = "market"
    signals: tuple[Signal, ...] = ()
    provenance: tuple[dict[str, Any], ...] = ()
    financial_trace: dict[str, Any] | None = None
    token_address: str | None = None
    pool_id: str | None = None
    chain_id: str | None = None
    dex_id: str | None = None
    pair_address: str | None = None
    dexscreener_url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "imageUrl": self.image_url,
            "physicalRadiusM": self.physical_radius_m,
            "resourcePileRadiusM": self.resource_pile_radius_m,
            "visualMotionIntensity": self.visual_motion_intensity,
            "brightness": self.brightness,
            "particleActivity": self.particle_activity,
            "chaos": self.chaos,
            "attractiveOdor": self.attractive_odor,
            "aversiveDanger": self.aversive_danger,
            "semanticType": self.semantic_type,
            "signals": [signal.as_dict() for signal in self.signals],
            "provenance": list(self.provenance),
            "financialTrace": self.financial_trace,
            "tokenAddress": self.token_address,
            "poolId": self.pool_id,
            "chainId": self.chain_id,
            "dexId": self.dex_id,
            "pairAddress": self.pair_address,
            "dexscreenerUrl": self.dexscreener_url,
        }


class HabitatEncoder:
    """Map explicit signals to environmental proxies, never directly to motion."""

    def __init__(self, encoding_mode: str = "financial-sensory-v1") -> None:
        if encoding_mode not in {"legacy", "financial-sensory-v1"}:
            raise ValueError("encoding_mode must be legacy or financial-sensory-v1")
        self.encoding_mode = encoding_mode
        self._factor_engine = FinancialFactorEngine()
        self._sensory_encoder = MultidimensionalSensoryEncoder.from_file()

    def encode(self, state: TokenState, signals: Iterable[Signal] | None = None) -> PhysicalHabitatState:
        signal_list = tuple(signals if signals is not None else state.signals)
        if self.encoding_mode == "financial-sensory-v1":
            financial = state.financial or self._factor_engine.evaluate(state)
            sensory = self._sensory_encoder.encode(financial)
            return PhysicalHabitatState(
                id=state.id,
                label=state.label,
                image_url=state.image_url,
                physical_radius_m=0.09 + sensory.resource * 0.13,
                resource_pile_radius_m=0.045 + sensory.resource * 0.045,
                visual_motion_intensity=sensory.motion,
                brightness=0.16 + sensory.light * 0.5,
                particle_activity=min(1.0, sensory.motion * 0.72 + sensory.resource * 0.28),
                chaos=sensory.chaos,
                attractive_odor=sensory.odor_a,
                aversive_danger=sensory.odor_b,
                semantic_type=_semantic_type(sensory.motion, sensory.resource, sensory.chaos),
                signals=signal_list,
                provenance=(*state.provenance, {"provider": "dexscreener", "imageUrl": state.image_url}) if state.image_url else state.provenance,
                financial_trace=sensory.trace,
                token_address=state.token_address,
                pool_id=state.pool_id,
                chain_id=state.chain_id,
                dex_id=state.dex_id,
                pair_address=state.pair_address or state.pool_id,
                dexscreener_url=_dexscreener_url(state),
            )
        activity = _signal(signal_list, "market.volume5mUsd")
        tx_velocity = _signal(signal_list, "flow.txVelocity5m")
        liquidity = _signal(signal_list, "liquidity.usd")
        flow = _signal(signal_list, "flow.imbalance")
        risk = _clip(0.55 * (1.0 - liquidity.normalized) + 0.45 * abs(flow.valence))
        activity_level = _clip(0.65 * activity.normalized + 0.35 * tx_velocity.normalized)
        semantic_type = _semantic_type(activity_level, liquidity.normalized, risk)
        return PhysicalHabitatState(
            id=state.id,
            label=state.label,
            physical_radius_m=0.09 + liquidity.normalized * 0.13,
            resource_pile_radius_m=0.045 + activity_level * 0.045,
            visual_motion_intensity=_clip(activity_level * 0.8 + abs(flow.valence) * 0.2),
            brightness=_clip(0.16 + activity_level * 0.5),
            particle_activity=_clip(activity_level * 0.72 + tx_velocity.normalized * 0.28),
            chaos=risk,
            attractive_odor=_clip(0.65 * activity_level + 0.2 * liquidity.normalized + 0.15 * max(0.0, flow.valence)),
            aversive_danger=risk,
            semantic_type=semantic_type,
            signals=signal_list,
            provenance=state.provenance,
        )

    def encode_lightweight(self, config: dict[str, Any]) -> PhysicalHabitatState:
        """Encode DexScreener identity/metrics without a deep Graph query.

        This keeps every physically present market alive in the world while a
        smaller deep-observer tier receives swap-level observations.
        """
        if self.encoding_mode == "financial-sensory-v1":
            buys = int(config.get("buys5m") or 0)
            sells = int(config.get("sells5m") or 0)
            total = buys + sells
            buy_usd = float(config.get("buyUsd5m") or 0.0)
            sell_usd = float(config.get("sellUsd5m") or 0.0)
            imbalance = (buy_usd - sell_usd) / (buy_usd + sell_usd) if buy_usd + sell_usd else ((buys - sells) / total if total else 0.0)
            liquidity_usd = float(config.get("liquidityUsd") or 0.0)
            volume_24h_usd = _optional_float(config.get("volume24hUsd"))
            market_cap_usd = _optional_float(config.get("marketCapUsd"))
            fdv_usd = _optional_float(config.get("fdvUsd"))
            market_cap_to_liquidity = _optional_float(config.get("marketCapToLiquidity"))
            fdv_to_liquidity = _optional_float(config.get("fdvToLiquidity"))
            volume_24h_to_market_cap = _optional_float(config.get("volume24hToMarketCap"))
            volume_24h_to_liquidity = _optional_float(config.get("volume24hToLiquidity"))
            if market_cap_to_liquidity is None and market_cap_usd is not None and liquidity_usd > 0:
                market_cap_to_liquidity = market_cap_usd / liquidity_usd
            if fdv_to_liquidity is None and fdv_usd is not None and liquidity_usd > 0:
                fdv_to_liquidity = fdv_usd / liquidity_usd
            if volume_24h_to_market_cap is None and volume_24h_usd is not None and market_cap_usd and market_cap_usd > 0:
                volume_24h_to_market_cap = volume_24h_usd / market_cap_usd
            if volume_24h_to_liquidity is None and volume_24h_usd is not None and liquidity_usd > 0:
                volume_24h_to_liquidity = volume_24h_usd / liquidity_usd
            observed_at_ms = int(config.get("observedAtMs") or 0)
            provider = "dexscreener"
            provenance = ({"provider": provider, "marketId": config.get("id"), "lightweight": True},)
            state = TokenState(
                id=str(config.get("id", "")),
                label=str(config.get("label", config.get("id", ""))),
                token_address=str(config.get("tokenAddress", "")),
                pool_id=str(config.get("poolId", config.get("id", ""))),
                observed_at_ms=observed_at_ms,
                image_url=_optional_string(config.get("imageUrl")),
                market=MarketState(
                    price_usd=_optional_float(config.get("priceUsd")),
                    price_native=_optional_float(config.get("priceNative")),
                    market_cap_usd=market_cap_usd,
                    fdv_usd=fdv_usd,
                    pair_age_hours=_optional_float(config.get("pairAgeHours")),
                    cmc_id=_optional_int(config.get("cmcId")),
                    cmc_slug=str(config.get("cmcSlug")) if config.get("cmcSlug") else None,
                    cmc_rank=_optional_int(config.get("cmcRank")),
                    circulating_supply=_optional_float(config.get("circulatingSupply")),
                    total_supply=_optional_float(config.get("totalSupply")),
                    cmc_percent_change_7d=_optional_float(config.get("cmcPercentChange7d")),
                    cmc_volume_change_24h=_optional_float(config.get("cmcVolumeChange24h")),
                    market_cap_dominance=_optional_float(config.get("marketCapDominance")),
                    volume_5m_usd=float(config.get("volume5mUsd") or 0.0),
                    volume_24h_usd=volume_24h_usd,
                    volume_1h_usd=float(config.get("volume1hUsd") or 0.0),
                ),
                flow=FlowState(
                    buy_count_5m=buys,
                    sell_count_5m=sells,
                    buy_usd_5m=buy_usd,
                    sell_usd_5m=sell_usd,
                    flow_imbalance=imbalance,
                    tx_velocity_5m=total / 5.0,
                ),
                liquidity=LiquidityState(
                    liquidity_usd=liquidity_usd,
                    liquidity_base=_optional_float(config.get("liquidityBase")),
                    liquidity_quote=_optional_float(config.get("liquidityQuote")),
                    market_cap_to_liquidity=market_cap_to_liquidity,
                    fdv_to_liquidity=fdv_to_liquidity,
                    volume_24h_to_market_cap=volume_24h_to_market_cap,
                    volume_24h_to_liquidity=volume_24h_to_liquidity,
                ),
                signals=tuple(
                    _lightweight_signal(name, value, observed_at_ms, provider)
                    for name, value in (
                        ("market.priceUsd", _optional_float(config.get("priceUsd"))),
                        ("market.marketCapUsd", market_cap_usd),
                        ("market.fdvUsd", fdv_usd),
                        ("market.pairAgeHours", _optional_float(config.get("pairAgeHours"))),
                        ("market.volume5mUsd", _optional_float(config.get("volume5mUsd"))),
                        ("market.volume1hUsd", _optional_float(config.get("volume1hUsd"))),
                        ("market.volume24hUsd", volume_24h_usd),
                        ("flow.buyCount5m", float(buys)),
                        ("flow.sellCount5m", float(sells)),
                        ("flow.buyUsd5m", buy_usd),
                        ("flow.sellUsd5m", sell_usd),
                        ("flow.imbalance", imbalance),
                        ("flow.txVelocity5m", total / 5.0),
                        ("liquidity.usd", liquidity_usd),
                        ("liquidity.marketCapToLiquidity", market_cap_to_liquidity),
                        ("liquidity.fdvToLiquidity", fdv_to_liquidity),
                        ("liquidity.volume24hToMarketCap", volume_24h_to_market_cap),
                        ("liquidity.volume24hToLiquidity", volume_24h_to_liquidity),
                        ("market.cmcRank", _optional_float(config.get("cmcRank"))),
                        ("market.circulatingSupply", _optional_float(config.get("circulatingSupply"))),
                        ("market.cmcPercentChange7d", _optional_float(config.get("cmcPercentChange7d"))),
                        ("market.cmcVolumeChange24h", _optional_float(config.get("cmcVolumeChange24h"))),
                        ("market.marketCapDominance", _optional_float(config.get("marketCapDominance"))),
                    ) if value is not None
                ),
                provenance=provenance,
                chain_id=str(config.get("chainId", "ethereum")),
                dex_id=str(config.get("dexId", "unknown")),
                pair_address=str(config.get("pairAddress", config.get("poolId", ""))),
                dexscreener_url=_optional_string(config.get("dexscreenerUrl")),
            )
            return self.encode(state)
        activity = _clip(float(config.get("volume5mUsd") or 0.0) / 10_000.0)
        transactions = float((config.get("buys5m") or 0) + (config.get("sells5m") or 0))
        tx_velocity = _clip(transactions / 10.0)
        liquidity = _clip(float(config.get("liquidityUsd") or 0.0) / 1_000_000.0)
        total = float((config.get("buys5m") or 0) + (config.get("sells5m") or 0))
        flow = 0.0 if total <= 0 else (float(config.get("buys5m") or 0) - float(config.get("sells5m") or 0)) / total
        risk = _clip(0.55 * (1.0 - liquidity) + 0.45 * abs(flow))
        activity_level = _clip(0.65 * activity + 0.35 * tx_velocity)
        return PhysicalHabitatState(
            id=str(config.get("id", "")),
            label=str(config.get("label", config.get("id", ""))),
            image_url=_optional_string(config.get("imageUrl")),
            physical_radius_m=0.09 + liquidity * 0.13,
            resource_pile_radius_m=0.045 + activity_level * 0.045,
            visual_motion_intensity=_clip(activity_level * 0.8 + abs(flow) * 0.2),
            brightness=_clip(0.16 + activity_level * 0.5),
            particle_activity=_clip(activity_level * 0.72 + tx_velocity * 0.28),
            chaos=risk,
            attractive_odor=_clip(0.65 * activity_level + 0.2 * liquidity + 0.15 * max(0.0, flow)),
            aversive_danger=risk,
            semantic_type=_semantic_type(activity_level, liquidity, risk),
            provenance=({
                "provider": "dexscreener",
                "marketId": config.get("id"),
                "imageUrl": config.get("imageUrl"),
                "marketName": config.get("marketName"),
                "lightweight": True,
            },),
            token_address=_optional_string(config.get("tokenAddress")),
            pool_id=_optional_string(config.get("poolId")),
            chain_id=_optional_string(config.get("chainId")) or "ethereum",
            dex_id=_optional_string(config.get("dexId")) or "unknown",
            pair_address=_optional_string(config.get("pairAddress")) or _optional_string(config.get("poolId")),
            dexscreener_url=_optional_string(config.get("dexscreenerUrl")) or _dexscreener_url_from_values(
                config.get("chainId"), config.get("pairAddress") or config.get("poolId")
            ),
        )


def _signal(signals: tuple[Signal, ...], name: str) -> Signal:
    for signal in signals:
        if signal.name == name:
            return signal
    return Signal(name, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "unavailable", 0)


def _clip(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _semantic_type(activity: float, liquidity: float, risk: float) -> str:
    """Choose a visual metaphor from encoded signals, not a fly command."""
    if risk >= 0.62:
        return "rot"
    if activity < 0.28:
        return "trash"
    if liquidity >= 0.62:
        return "food"
    return "market"


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dexscreener_url(state: TokenState) -> str | None:
    if state.dexscreener_url:
        return state.dexscreener_url
    return _dexscreener_url_from_values(state.chain_id, state.pair_address or state.pool_id)


def _dexscreener_url_from_values(chain_id: Any, pair_address: Any) -> str | None:
    chain = _optional_string(chain_id)
    pair = _optional_string(pair_address)
    if not chain or not pair:
        return None
    return f"https://dexscreener.com/{chain}/{pair}"


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _lightweight_signal(name: str, value: float, observed_at_ms: int, source: str) -> Signal:
    # Discovery facts are exposed for inspection. They are not direct motor
    # commands and do not encode a bullish recommendation.
    normalized = min(1.0, max(0.0, value / (1.0 + abs(value))))
    return Signal(name, value, normalized, 0.5, 0.0, 1.0, 1.0, source, observed_at_ms)
