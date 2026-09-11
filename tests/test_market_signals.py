from __future__ import annotations

from dataclasses import replace

import pytest

from malecns.market.habitat_encoder import HabitatEncoder
from malecns.market.models import RawSwapObservation, SecurityState
from malecns.market.features.guard import InvestabilityGuard
from malecns.market.features.factors import FinancialFactorEngine
from malecns.market.providers import GraphProvider
from malecns.market.signal_engine import TokenSignalEngine


TOKEN0 = "0xaaa"
TOKEN1 = "0xbbb"


def _observation(token_address: str = TOKEN0):
    now = 10_000
    pool = {
        "id": "0xpool",
        "token0": {"id": TOKEN0, "symbol": "AAA"},
        "token1": {"id": TOKEN1, "symbol": "USDC"},
        "token0Price": "2.0",
        "token1Price": "0.5",
        "totalValueLockedUSD": "500000",
    }
    swaps = (
        RawSwapObservation("buy", now - 60, -10, 5, 100, TOKEN0, TOKEN1, "tx-buy"),
        RawSwapObservation("sell", now - 120, 10, -5, 200, TOKEN0, TOKEN1, "tx-sell"),
        RawSwapObservation("previous", now - 360, -1, 1, 50, TOKEN0, TOKEN1, "tx-previous"),
        RawSwapObservation("fifteen-a", now - 660, -2, 1, 300, TOKEN0, TOKEN1, "tx-15-a"),
        RawSwapObservation("fifteen-b", now - 700, 2, -1, 400, TOKEN0, TOKEN1, "tx-15-b"),
        RawSwapObservation("hour", now - 1900, -3, 1, 500, TOKEN0, TOKEN1, "tx-hour"),
    )
    from malecns.market.models import RawTokenObservation

    return RawTokenObservation("the-graph", "TOKEN", token_address, "0xpool", "TOKEN", now * 1000, pool, swaps)


def test_graph_provider_returns_raw_observations_and_requires_token_identity():
    class FakeGraph:
        def __init__(self):
            self.request = None

        def pool_state(self, pool_id):
            return _observation().pool

        def recent_swaps(self, pool_id, *, first, since_timestamp):
            self.request = (pool_id, first, since_timestamp)
            return []

    graph = FakeGraph()
    provider = GraphProvider(graph, lookback_seconds=3600, swap_limit=1000)
    observation = provider.observe(
        {"id": "TOKEN", "label": "TOKEN", "poolId": "0xPOOL", "tokenAddress": TOKEN0},
        now_s=10_000,
    )
    assert observation.provider == "the-graph"
    assert graph.request == ("0xpool", 1000, 6400)
    with pytest.raises(ValueError, match="tokenAddress"):
        provider.observe({"id": "TOKEN", "poolId": "0xPOOL"}, now_s=10_000)


def test_signal_engine_uses_5m_15m_and_1h_windows():
    state = TokenSignalEngine().build_state(_observation())

    assert state.market.volume_5m_usd == 300
    assert state.market.volume_15m_usd == 1_050
    assert state.market.volume_1h_usd == 1_550
    assert state.flow.buy_count_5m == 1
    assert state.flow.sell_count_5m == 1
    assert state.flow.buy_usd_5m == 100
    assert state.flow.sell_usd_5m == 200
    assert state.flow.flow_imbalance == pytest.approx(-1 / 3)
    assert state.flow.tx_velocity_5m == pytest.approx(0.4)
    assert state.flow.tx_acceleration == pytest.approx(0.2)
    assert state.liquidity.liquidity_usd == 500_000
    assert state.liquidity.liquidity_delta_usd is None
    assert state.liquidity.volume_liquidity_ratio_1h == pytest.approx(1_550 / 500_000)
    assert {signal.name for signal in state.signals} >= {
        "market.volume5mUsd",
        "market.volume15mUsd",
        "market.volume1hUsd",
        "flow.buyCount5m",
        "flow.sellCount5m",
        "flow.buyUsd5m",
        "flow.sellUsd5m",
        "flow.imbalance",
        "flow.txVelocity5m",
        "flow.txAcceleration",
        "liquidity.usd",
        "liquidity.deltaUsd",
        "liquidity.volumeLiquidityRatio1h",
    }


def test_buy_sell_is_relative_to_represented_token_not_always_amount0():
    token0_state = TokenSignalEngine().build_state(_observation(TOKEN0))
    token1_state = TokenSignalEngine().build_state(_observation(TOKEN1))

    assert token0_state.flow.buy_usd_5m == 100
    assert token0_state.flow.sell_usd_5m == 200
    assert token1_state.flow.buy_usd_5m == 200
    assert token1_state.flow.sell_usd_5m == 100


def test_liquidity_delta_is_computed_from_previous_snapshot():
    state = TokenSignalEngine().build_state(_observation(), previous_liquidity_usd=450_000)
    assert state.liquidity.liquidity_delta_usd == 50_000
    delta_signal = next(signal for signal in state.signals if signal.name == "liquidity.deltaUsd")
    assert delta_signal.value == 50_000
    assert delta_signal.confidence == 1.0


def test_habitat_encoder_receives_signals_and_preserves_provenance():
    state = TokenSignalEngine().build_state(_observation())
    habitat = HabitatEncoder().encode(state)
    assert habitat.id == "TOKEN"
    assert habitat.as_dict()["chainId"] == "ethereum"
    assert habitat.as_dict()["pairAddress"] == "0xpool"
    assert habitat.as_dict()["dexscreenerUrl"] == "https://dexscreener.com/ethereum/0xpool"
    assert habitat.signals == state.signals
    assert habitat.provenance[0]["provider"] == "the-graph"
    assert 0 <= habitat.brightness <= 1
    assert 0 <= habitat.attractive_odor <= 1


def test_signal_wire_format_uses_frontend_timestamp_name():
    state = TokenSignalEngine().build_state(_observation())
    signal = state.signals[0]
    payload = state.as_dict()
    assert signal.as_dict()["observedAtMs"] == 10_000_000
    assert "observed_at_ms" not in signal.as_dict()
    assert payload["tokenAddress"] == TOKEN0
    assert payload["market"]["volume5mUsd"] == 300
    assert payload["flow"]["buyCount5m"] == 1
    assert payload["liquidity"]["liquidityUsd"] == 500_000
    assert payload["signals"][0]["observedAtMs"] == 10_000_000


def test_financial_state_contains_interpretable_factors_and_provenance():
    state = TokenSignalEngine().build_state(_observation())

    assert state.financial is not None
    factors = {factor.factor_id: factor for factor in state.financial.factors}
    assert factors["liquidity_quality"].available
    assert factors["flow"].available
    assert not factors["security_quality"].available
    assert state.financial.features[0].provenance[0]["provider"] == "the-graph"
    assert all(-1 <= factor.value <= 1 for factor in state.financial.factors)


def test_investability_guard_rejects_honeypot_and_low_liquidity_but_not_unknown_security():
    state = TokenSignalEngine().build_state(_observation())
    result = InvestabilityGuard(min_executable_liquidity_usd=600_000).evaluate(state)
    assert not result.eligible
    assert "liquidity below executable threshold" in result.reasons

    honeypot = replace(state, security=SecurityState(status="available", honeypot=True, sellable=False))
    result = InvestabilityGuard(min_executable_liquidity_usd=1).evaluate(honeypot)
    assert not result.eligible
    assert "confirmed honeypot" in result.reasons
    assert "token is not sellable" in result.reasons

    unknown = InvestabilityGuard(min_executable_liquidity_usd=1).evaluate(state)
    assert unknown.eligible
    assert unknown.severity == "unknown"


def test_financial_sensory_mapping_is_bounded_and_traceable():
    state = TokenSignalEngine().build_state(_observation())
    habitat = HabitatEncoder().encode(state)

    assert habitat.financial_trace is not None
    assert habitat.financial_trace["version"] == "sensory-mapping-v1"
    assert habitat.attractive_odor == pytest.approx(habitat.financial_trace["channelStrengths"]["odorA"])
    assert habitat.aversive_danger == pytest.approx(habitat.financial_trace["channelStrengths"]["odorB"])
    for value in (habitat.visual_motion_intensity, habitat.brightness, habitat.attractive_odor, habitat.aversive_danger, habitat.chaos):
        assert 0 <= value <= 1


def test_optional_valuation_and_depth_metrics_stay_nullable_and_traceable():
    observation = _observation()
    enriched_pool = {
        **observation.pool,
        "priceUsd": "1.25",
        "marketCapUsd": "1250000",
        "fdvUsd": "2000000",
        "volume24hUsd": "300000",
        "pairCreatedAt": 9_999_000,
        "liquidityBase": "1000",
        "liquidityQuote": "1000",
    }
    state = TokenSignalEngine().build_state(replace(observation, pool=enriched_pool))

    assert state.market.market_cap_usd == 1_250_000
    assert state.market.fdv_usd == 2_000_000
    assert state.liquidity.market_cap_to_liquidity == pytest.approx(2.5)
    assert state.liquidity.fdv_to_liquidity == pytest.approx(4.0)
    assert state.liquidity.volume_24h_to_market_cap == pytest.approx(0.24)
    assert state.liquidity.volume_24h_to_liquidity == pytest.approx(0.6)
    assert {feature.feature_id for feature in state.financial.features} >= {
        "market.marketCap",
        "market.fdv",
        "liquidity.marketCapToLiquidity",
        "liquidity.fdvToLiquidity",
        "liquidity.volume24hToMarketCap",
    }


def test_feature_freshness_decays_and_future_observations_are_rejected():
    state = TokenSignalEngine().build_state(_observation())
    engine = FinancialFactorEngine()
    stale = engine.evaluate(state, now_ms=state.observed_at_ms + 300_000)
    assert stale.features[0].freshness == pytest.approx(1 / 2.718281828, rel=1e-3)

    future = engine.evaluate(state, now_ms=state.observed_at_ms - 1_001)
    assert future.features == ()


def test_lightweight_market_habitat_uses_the_same_financial_mapping():
    habitat = HabitatEncoder().encode_lightweight({
        "id": "base:0xpair",
        "label": "BASE",
        "tokenAddress": "0xtoken",
        "poolId": "0xpair",
        "pairAddress": "0xpair",
        "chainId": "base",
        "dexId": "aerodrome",
        "liquidityUsd": 250_000,
        "volume5mUsd": 20_000,
        "volume1hUsd": 100_000,
        "buys5m": 12,
        "sells5m": 4,
    })
    assert habitat.financial_trace is not None
    assert habitat.financial_trace["version"] == "sensory-mapping-v1"
    assert habitat.provenance[0]["provider"] == "dexscreener"
