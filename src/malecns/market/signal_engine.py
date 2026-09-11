"""Convert raw provider observations into normalized token signals."""

from __future__ import annotations

import json
import math
import os
import time
from dataclasses import dataclass
from dataclasses import replace
from typing import Any

from .graph_client import GraphClient
from .habitat_encoder import HabitatEncoder, PhysicalHabitatState
from .models import (
    FlowState,
    HoldersState,
    LiquidityState,
    LoreState,
    MarketState,
    RawTokenObservation,
    SecurityState,
    Signal,
    SocialState,
    TokenState,
)
from .providers import GraphProvider
from .universe import DexScreenerMarketDiscovery
from .features.pipeline import FinancialSensoryPipeline


@dataclass(frozen=True)
class MarketSnapshot:
    status: str
    observed_at_ms: int
    habitats: tuple[PhysicalHabitatState, ...]
    error: str | None = None
    source: str = "graph-uniswap"
    discovery: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source": self.source,
            "status": self.status,
            "observedAtMs": self.observed_at_ms,
            "habitats": [habitat.as_dict() for habitat in self.habitats],
            "rawMarketFieldsForwardedToFly": False,
        }
        if self.error:
            payload["error"] = self.error
        if self.discovery is not None:
            payload["discovery"] = self.discovery
        return payload


class TokenSignalEngine:
    """Compute time-windowed, provider-neutral signals from raw observations."""

    def __init__(self, financial_pipeline: FinancialSensoryPipeline | None = None) -> None:
        # One pipeline instance keeps per-token historical baselines across
        # polls; it never shares neural state or market identity.
        self.financial_pipeline = financial_pipeline or FinancialSensoryPipeline.default()

    def build_state(
        self,
        observation: RawTokenObservation,
        *,
        previous_liquidity_usd: float | None = None,
    ) -> TokenState:
        now_s = observation.observed_at_ms / 1000.0
        token_side = _token_side(observation)
        windows = {
            "5m": _window(observation.swaps, now_s, 300),
            "15m": _window(observation.swaps, now_s, 900),
            "1h": _window(observation.swaps, now_s, 3600),
        }
        volume = {name: sum(swap.amount_usd for swap in swaps) for name, swaps in windows.items()}
        buys_5m = [swap for swap in windows["5m"] if _is_buy(swap, token_side)]
        sells_5m = [swap for swap in windows["5m"] if _is_sell(swap, token_side)]
        buy_usd = sum(swap.amount_usd for swap in buys_5m)
        sell_usd = sum(swap.amount_usd for swap in sells_5m)
        flow_imbalance = _signed_ratio(buy_usd, sell_usd)
        tx_velocity = _tx_velocity(windows["5m"])
        previous_window = _window(observation.swaps, now_s - 300, 300)
        tx_acceleration = tx_velocity - _tx_velocity(previous_window)
        liquidity_usd = _number(observation.pool.get("totalValueLockedUSD"))
        liquidity_delta = None if previous_liquidity_usd is None else liquidity_usd - previous_liquidity_usd
        ratio = volume["1h"] / liquidity_usd if liquidity_usd > 0 else 0.0
        price_in_pair = _price_in_pair(observation.pool, token_side)
        price_usd = _optional_number(observation.pool.get("priceUsd"))
        price_native = _optional_number(observation.pool.get("priceNative"))
        market_cap_usd = _optional_number(observation.pool.get("marketCapUsd", observation.pool.get("marketCap")))
        fdv_usd = _optional_number(observation.pool.get("fdvUsd", observation.pool.get("fdv")))
        pair_age_hours = _pair_age_hours(observation.pool, observation.observed_at_ms)
        cmc_id = _optional_int(observation.pool.get("cmcId"))
        cmc_slug = _optional_string(observation.pool.get("cmcSlug"))
        cmc_rank = _optional_int(observation.pool.get("cmcRank"))
        circulating_supply = _optional_number(observation.pool.get("circulatingSupply"))
        total_supply = _optional_number(observation.pool.get("totalSupply"))
        cmc_percent_change_7d = _optional_number(observation.pool.get("cmcPercentChange7d"))
        cmc_volume_change_24h = _optional_number(observation.pool.get("cmcVolumeChange24h"))
        market_cap_dominance = _optional_number(observation.pool.get("marketCapDominance"))
        liquidity_base = _optional_number(observation.pool.get("liquidityBase"))
        liquidity_quote = _optional_number(observation.pool.get("liquidityQuote"))
        market_cap_to_liquidity = _ratio(market_cap_usd, liquidity_usd)
        fdv_to_liquidity = _ratio(fdv_usd, liquidity_usd)
        volume_24h_usd = _optional_number(observation.pool.get("volume24hUsd"))
        volume_24h_to_market_cap = _ratio(volume_24h_usd, market_cap_usd)
        volume_24h_to_liquidity = _ratio(volume_24h_usd, liquidity_usd)
        confidence = 1.0 if observation.swaps or liquidity_usd > 0 else 0.0
        freshness = 1.0
        signals = (
            _signal("market.volume5mUsd", volume["5m"], _nonnegative_norm(volume["5m"], 10_000), 0.85, 0.0, confidence, freshness, observation),
            _signal("market.volume15mUsd", volume["15m"], _nonnegative_norm(volume["15m"], 25_000), 0.7, 0.0, confidence, freshness, observation),
            _signal("market.volume1hUsd", volume["1h"], _nonnegative_norm(volume["1h"], 100_000), 0.65, 0.0, confidence, freshness, observation),
            _signal("market.volume24hUsd", volume_24h_usd, _nonnegative_norm(volume_24h_usd or 0.0, 500_000), 0.55, 0.0, _available_confidence(volume_24h_usd), freshness, observation),
            _signal("flow.buyCount5m", len(buys_5m), _count_norm(len(buys_5m)), 0.7, 0.0, confidence, freshness, observation),
            _signal("flow.sellCount5m", len(sells_5m), _count_norm(len(sells_5m)), 0.7, 0.0, confidence, freshness, observation),
            # Buy/sell volume is magnitude. Direction is represented separately
            # by flow.imbalance, so these signals remain valence-neutral.
            _signal("flow.buyUsd5m", buy_usd, _nonnegative_norm(buy_usd, 10_000), 0.8, 0.0, confidence, freshness, observation),
            _signal("flow.sellUsd5m", sell_usd, _nonnegative_norm(sell_usd, 10_000), 0.8, 0.0, confidence, freshness, observation),
            _signal("flow.imbalance", flow_imbalance, (flow_imbalance + 1.0) / 2.0, 0.9, flow_imbalance, confidence, freshness, observation),
            _signal("flow.txVelocity5m", tx_velocity, _nonnegative_norm(tx_velocity, 10), 0.65, 0.0, confidence, freshness, observation),
            _signal("flow.txAcceleration", tx_acceleration, _signed_norm(tx_acceleration, 10), 0.55, tx_acceleration / 10, confidence, freshness, observation),
            _signal("liquidity.usd", liquidity_usd, _nonnegative_norm(liquidity_usd, 1_000_000), 0.8, 0.0, confidence, freshness, observation),
            _signal("liquidity.deltaUsd", liquidity_delta, _signed_norm(liquidity_delta or 0.0, 1_000_000), 0.6, (liquidity_delta or 0.0) / 1_000_000, confidence if liquidity_delta is not None else 0.0, freshness, observation),
            _signal("liquidity.volumeLiquidityRatio1h", ratio, _nonnegative_norm(ratio, 1), 0.65, 0.0, confidence, freshness, observation),
            _signal("market.priceUsd", price_usd, _nonnegative_norm(price_usd or 0.0, 1), 0.35, 0.0, _available_confidence(price_usd), freshness, observation),
            _signal("market.marketCapUsd", market_cap_usd, _nonnegative_norm(market_cap_usd or 0.0, 1_000_000), 0.75, 0.0, _available_confidence(market_cap_usd), freshness, observation),
            _signal("market.fdvUsd", fdv_usd, _nonnegative_norm(fdv_usd or 0.0, 1_000_000), 0.7, 0.0, _available_confidence(fdv_usd), freshness, observation),
            _signal("market.pairAgeHours", pair_age_hours, _nonnegative_norm(pair_age_hours or 0.0, 720), 0.55, 0.0, _available_confidence(pair_age_hours), freshness, observation),
            _signal("liquidity.marketCapToLiquidity", market_cap_to_liquidity, _nonnegative_norm(market_cap_to_liquidity or 0.0, 100), 0.85, 0.0, _available_confidence(market_cap_to_liquidity), freshness, observation),
            _signal("liquidity.fdvToLiquidity", fdv_to_liquidity, _nonnegative_norm(fdv_to_liquidity or 0.0, 100), 0.8, 0.0, _available_confidence(fdv_to_liquidity), freshness, observation),
            _signal("liquidity.volume24hToMarketCap", volume_24h_to_market_cap, _nonnegative_norm(volume_24h_to_market_cap or 0.0, 1), 0.65, 0.0, _available_confidence(volume_24h_to_market_cap), freshness, observation),
            _signal("liquidity.volume24hToLiquidity", volume_24h_to_liquidity, _nonnegative_norm(volume_24h_to_liquidity or 0.0, 10), 0.75, 0.0, _available_confidence(volume_24h_to_liquidity), freshness, observation),
            _signal("market.cmcRank", cmc_rank, _rank_norm(cmc_rank), 0.5, 0.0, _available_confidence(cmc_rank), freshness, observation),
            _signal("market.circulatingSupply", circulating_supply, _nonnegative_norm(circulating_supply or 0.0, 1_000_000_000), 0.35, 0.0, _available_confidence(circulating_supply), freshness, observation),
            _signal("market.cmcPercentChange7d", cmc_percent_change_7d, _signed_norm(cmc_percent_change_7d or 0.0, 100), 0.65, (cmc_percent_change_7d or 0.0) / 100, _available_confidence(cmc_percent_change_7d), freshness, observation),
            _signal("market.cmcVolumeChange24h", cmc_volume_change_24h, _signed_norm(cmc_volume_change_24h or 0.0, 100), 0.6, (cmc_volume_change_24h or 0.0) / 100, _available_confidence(cmc_volume_change_24h), freshness, observation),
            _signal("market.marketCapDominance", market_cap_dominance, _nonnegative_norm(market_cap_dominance or 0.0, 100), 0.3, 0.0, _available_confidence(market_cap_dominance), freshness, observation),
        )
        state = TokenState(
            id=observation.token_id,
            label=observation.label,
            token_address=observation.token_address,
            pool_id=observation.pool_id,
            observed_at_ms=observation.observed_at_ms,
            market=MarketState(
                price_in_pair=price_in_pair,
                price_usd=price_usd,
                price_native=price_native,
                market_cap_usd=market_cap_usd,
                fdv_usd=fdv_usd,
                pair_age_hours=pair_age_hours,
                cmc_id=cmc_id,
                cmc_slug=cmc_slug,
                cmc_rank=cmc_rank,
                circulating_supply=circulating_supply,
                total_supply=total_supply,
                cmc_percent_change_7d=cmc_percent_change_7d,
                cmc_volume_change_24h=cmc_volume_change_24h,
                market_cap_dominance=market_cap_dominance,
                volume_5m_usd=volume["5m"],
                volume_15m_usd=volume["15m"],
                volume_1h_usd=volume["1h"],
                volume_24h_usd=volume_24h_usd,
            ),
            flow=FlowState(
                buy_count_5m=len(buys_5m),
                sell_count_5m=len(sells_5m),
                buy_usd_5m=buy_usd,
                sell_usd_5m=sell_usd,
                flow_imbalance=flow_imbalance,
                tx_velocity_5m=tx_velocity,
                tx_acceleration=tx_acceleration,
            ),
            liquidity=LiquidityState(
                liquidity_usd=liquidity_usd,
                liquidity_delta_usd=liquidity_delta,
                volume_liquidity_ratio_1h=ratio,
                liquidity_base=liquidity_base,
                liquidity_quote=liquidity_quote,
                market_cap_to_liquidity=market_cap_to_liquidity,
                fdv_to_liquidity=fdv_to_liquidity,
                volume_24h_to_market_cap=volume_24h_to_market_cap,
                volume_24h_to_liquidity=volume_24h_to_liquidity,
            ),
            holders=HoldersState(),
            security=SecurityState(),
            social=SocialState(),
            lore=LoreState(),
            signals=signals,
            provenance=(
                {
                    "provider": observation.provider,
                    "poolId": observation.pool_id,
                    "tokenAddress": observation.token_address,
                    "chainId": observation.chain_id,
                    "dexId": observation.dex_id,
                    "pairAddress": observation.pair_address or observation.pool_id,
                    "observedAtMs": observation.observed_at_ms,
                },
            ),
            chain_id=observation.chain_id,
            dex_id=observation.dex_id,
            pair_address=observation.pair_address or observation.pool_id,
            dexscreener_url=_optional_string(observation.pool.get("dexscreenerUrl") or observation.pool.get("url")),
        )
        return replace(state, financial=self.financial_pipeline.evaluate(state))


class MarketSignalEngine:
    """Poll configured providers, build TokenState, then encode habitats."""

    def __init__(
        self,
        provider: GraphProvider | None,
        habitats: list[dict[str, Any]],
        *,
        poll_seconds: float = 15.0,
        discovery: DexScreenerMarketDiscovery | None = None,
    ) -> None:
        self.provider = provider
        self.habitat_configs = habitats
        self.poll_seconds = poll_seconds
        self.discovery = discovery
        self.signal_engine = TokenSignalEngine()
        self.habitat_encoder = HabitatEncoder(encoding_mode=os.getenv("NEUROSWARM_ENCODING_MODE", "financial-sensory-v1"))
        self._last_poll = 0.0
        self._cached: dict[str, Any] | None = None
        self._previous_liquidity: dict[str, float] = {}

    @classmethod
    def from_env(cls) -> "MarketSignalEngine | None":
        client = GraphClient.from_env()
        raw_habitats = os.getenv("NEUROSWARM_MARKET_HABITATS", "").strip()
        discovery = DexScreenerMarketDiscovery.from_env(graph_client=client)
        if client is None and discovery is None:
            return None
        habitats: list[dict[str, Any]] = []
        if raw_habitats:
            try:
                parsed_habitats = json.loads(raw_habitats)
            except json.JSONDecodeError as exc:
                raise ValueError("NEUROSWARM_MARKET_HABITATS must be valid JSON") from exc
            if not isinstance(parsed_habitats, list) or not all(isinstance(item, dict) for item in parsed_habitats):
                raise ValueError("NEUROSWARM_MARKET_HABITATS must be a JSON list of objects")
            habitats = [item for item in parsed_habitats if _is_robinhood_config(item)]
        if client is None and not habitats:
            return cls(None, [], poll_seconds=float(os.getenv("NEUROSWARM_MARKET_POLL_SECONDS", "15")), discovery=discovery)
        return cls(
            GraphProvider(
                client,
                lookback_seconds=int(os.getenv("NEUROSWARM_MARKET_LOOKBACK_SECONDS", "3600")),
                swap_limit=int(os.getenv("NEUROSWARM_MARKET_SWAP_LIMIT", "1000")),
            ) if client is not None else None,
            habitats,
            poll_seconds=float(os.getenv("NEUROSWARM_MARKET_POLL_SECONDS", "15")),
            discovery=discovery,
        )

    def snapshot_if_due(self, *, force: bool = False) -> dict[str, Any]:
        now = time.monotonic()
        if not force and self._cached is not None and now - self._last_poll < self.poll_seconds:
            return self._cached
        try:
            discovery_payload: dict[str, Any] | None = None
            configs = self.habitat_configs
            source = "graph-uniswap"
            if self.discovery is not None:
                world_configs = self.discovery.world_habitat_configs(force=force)
                discovered_configs = self.discovery.graph_habitat_configs(force=force)
                # Keep manually configured habitats as an explicit fallback;
                # discovery must not erase a working local setup just because
                # its provider has temporarily returned no candidates.
                configs = [
                    config for config in (world_configs or discovered_configs or self.habitat_configs)
                    if _is_robinhood_config(config)
                ]
                discovery_payload = self.discovery.as_dict()
                source = "dexscreener+the-graph" if self.provider is not None else "dexscreener"
            if self.provider is None and self.discovery is not None:
                habitats = tuple(self.habitat_encoder.encode_lightweight(config) for config in configs)
                snapshot = MarketSnapshot("ok" if habitats else "empty", int(time.time() * 1000), habitats, source=source, discovery=discovery_payload)
            elif self.provider is None:
                snapshot = MarketSnapshot("discovery_only", int(time.time() * 1000), tuple(), source=source, discovery=discovery_payload)
            elif self.discovery is not None and configs:
                # Deep Graph observation is deliberately bounded. Every other
                # physically present market still receives a live lightweight
                # habitat state derived from the cached DexScreener row.
                observed: dict[str, PhysicalHabitatState] = {}
                for config in discovered_configs:
                    try:
                        observed[str(config.get("id", ""))] = self._read_habitat(config)
                    except Exception:
                        observed[str(config.get("id", ""))] = self.habitat_encoder.encode_lightweight(config)
                habitats = tuple(
                    observed.get(str(config.get("id", "")), self.habitat_encoder.encode_lightweight(config))
                    for config in configs
                )
                snapshot = MarketSnapshot("ok" if habitats else "empty", int(time.time() * 1000), habitats, source=source, discovery=discovery_payload)
            else:
                habitats = tuple(self._read_habitat(config) for config in configs)
                status = "ok" if configs else "empty"
                snapshot = MarketSnapshot(status, int(time.time() * 1000), habitats, source=source, discovery=discovery_payload)
        except Exception as exc:
            snapshot = MarketSnapshot("error", int(time.time() * 1000), tuple(), str(exc), source="dexscreener+the-graph" if self.discovery else "graph-uniswap")
        self._last_poll = now
        self._cached = snapshot.as_dict()
        return self._cached

    def _read_habitat(self, config: dict[str, Any]) -> PhysicalHabitatState:
        if self.provider is None:
            raise RuntimeError("no deep market observation provider is configured")
        observation = self.provider.observe(config)
        previous_key = f"{observation.chain_id}:{observation.pool_id}"
        previous = self._previous_liquidity.get(previous_key)
        state = self.signal_engine.build_state(observation, previous_liquidity_usd=previous)
        self._previous_liquidity[previous_key] = state.liquidity.liquidity_usd
        return self.habitat_encoder.encode(state)


def _window(swaps: tuple[Any, ...] | list[Any], end_s: float, duration_s: int) -> list[Any]:
    start_s = end_s - duration_s
    return [swap for swap in swaps if start_s <= swap.timestamp_s <= end_s]


def _is_robinhood_config(config: dict[str, Any]) -> bool:
    return str(config.get("chainId", "")).strip().lower() == "robinhood"


def _token_side(observation: RawTokenObservation) -> str:
    token0 = str(observation.pool.get("token0", {}).get("id", "")).lower()
    if observation.token_address == token0:
        return "token0"
    token1 = str(observation.pool.get("token1", {}).get("id", "")).lower()
    if observation.token_address == token1:
        return "token1"
    raise ValueError(f"tokenAddress {observation.token_address} is not present in pool {observation.pool_id}")


def _is_buy(swap: Any, token_side: str) -> bool:
    # Uniswap V3 Swap amounts are pool balance deltas: negative means the pool
    # sent that token out, so the trader bought the represented token.
    return (swap.amount0 if token_side == "token0" else swap.amount1) < 0


def _is_sell(swap: Any, token_side: str) -> bool:
    return (swap.amount0 if token_side == "token0" else swap.amount1) > 0


def _tx_velocity(swaps: list[Any]) -> float:
    return len({swap.transaction_id or swap.swap_id for swap in swaps}) / 5.0


def _price_in_pair(pool: dict[str, Any], token_side: str) -> float | None:
    value = pool.get("token0Price" if token_side == "token0" else "token1Price")
    number = _number(value)
    return number if number > 0 else None


def _pair_age_hours(pool: dict[str, Any], observed_at_ms: int) -> float | None:
    created = _optional_number(pool.get("pairCreatedAt"))
    if created is None or created <= 0:
        return None
    created_ms = created if created >= 1_000_000_000_000 else created * 1000
    return max(0.0, (observed_at_ms - created_ms) / 3_600_000.0)


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _available_confidence(value: float | None) -> float:
    return 1.0 if value is not None else 0.0


def _signal(
    name: str,
    value: Any,
    normalized: float,
    importance: float,
    valence: float,
    confidence: float,
    freshness: float,
    observation: RawTokenObservation,
) -> Signal:
    return Signal(
        name=name,
        value=value,
        normalized=_clip(normalized),
        importance=_clip(importance),
        valence=_clip_signed(valence),
        confidence=_clip(confidence),
        freshness=_clip(freshness),
        source=observation.provider,
        observed_at_ms=observation.observed_at_ms,
    )


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _rank_norm(value: int | None) -> float:
    if value is None or value <= 0:
        return 0.0
    return 1.0 / (1.0 + (value - 1) / 25.0)


def _nonnegative_norm(value: float, scale: float) -> float:
    return math.tanh(max(0.0, float(value)) / max(scale, 1e-9))


def _count_norm(value: int) -> float:
    return _nonnegative_norm(value, 10)


def _signed_ratio(positive: float, negative: float) -> float:
    total = positive + negative
    return (positive - negative) / total if total else 0.0


def _signed_norm(value: float, scale: float) -> float:
    return (math.tanh(float(value) / max(scale, 1e-9)) + 1.0) / 2.0


def _clip(value: float) -> float:
    return min(1.0, max(0.0, float(value)))


def _clip_signed(value: float) -> float:
    return min(1.0, max(-1.0, float(value)))
