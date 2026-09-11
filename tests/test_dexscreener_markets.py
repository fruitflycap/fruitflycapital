from __future__ import annotations

from urllib.parse import urlparse

from malecns.market.coinmarketcap_client import CoinMarketCapClient
from malecns.market.dexscreener_client import DexScreenerClient
from malecns.market.universe import (
    DexScreenerUniverseProvider,
    MarketEligibility,
    MarketRoundManager,
    MarketSelector,
    DexScreenerMarketDiscovery,
    candidate_from_pair,
)


def _pair(address: str = "0xpair", *, token: str = "0xtoken", liquidity: float = 250_000) -> dict:
    return {
        "chainId": "ethereum",
        "dexId": "uniswap",
        "url": "https://dexscreener.com/ethereum/0xpair",
        "pairAddress": address,
        "baseToken": {"address": token, "name": "Example Token", "symbol": "EXM"},
        "quoteToken": {"address": "0xusdc", "name": "USD Coin", "symbol": "USDC"},
        "priceUsd": "1.25",
        "priceNative": "0.0004",
        "fdv": 2_000_000,
        "marketCap": 1_250_000,
        "txns": {"m5": {"buys": 4, "sells": 2}, "h1": {"buys": 40, "sells": 20}, "h24": {"buys": 400, "sells": 200}},
        "volume": {"m5": 1200, "h1": 25_000, "h24": 300_000},
        "priceChange": {"m5": 0.5, "h1": 3.2, "h24": 4.1},
        "liquidity": {"usd": liquidity, "base": 1000, "quote": 1000},
        "boosts": {"active": 2},
        "pairCreatedAt": 1_700_000_000_000,
        "info": {"imageUrl": "https://example.test/exm.png", "websites": [{"url": "https://example.test"}], "socials": [{"type": "twitter", "url": "https://x.test/exm"}]},
    }


def test_public_discovery_ignores_legacy_multi_chain_environment(monkeypatch):
    monkeypatch.setenv("NEUROSWARM_MARKET_DISCOVERY_ENABLED", "true")
    monkeypatch.setenv("NEUROSWARM_MARKET_CHAINS", "ethereum,base,robinhood")

    discovery = DexScreenerMarketDiscovery.from_env()

    assert discovery is not None
    assert discovery.universe_provider.chains == ("robinhood",)


def test_dexscreener_client_batches_token_lookup_at_thirty_addresses():
    requested: list[str] = []

    def fetch(url: str, _timeout: float):
        path = urlparse(url).path
        requested.append(path)
        return [_pair(address=f"0xpair{len(requested)}")]

    client = DexScreenerClient(fetcher=fetch)
    pairs = client.tokens("ethereum", [f"0xtoken{index}" for index in range(31)])

    assert len(pairs) == 2
    assert requested[0] == "/tokens/v1/ethereum/" + ",".join(f"0xtoken{index}" for index in range(30))
    assert requested[1] == "/tokens/v1/ethereum/0xtoken30"


def test_dexscreener_client_search_encodes_query():
    requested: list[str] = []

    def fetch(url: str, _timeout: float):
        requested.append(urlparse(url).path + "?" + urlparse(url).query)
        return {"pairs": []}

    client = DexScreenerClient(fetcher=fetch)
    assert client.search("USDG / ETH") == []
    assert requested == ["/latest/dex/search?q=USDG%20%2F%20ETH"]


def test_coinmarketcap_client_caches_classic_top_listings():
    calls = 0

    def fetch(url: str, _timeout: float, headers: dict[str, str]):
        nonlocal calls
        calls += 1
        assert url.endswith("/v3/cryptocurrency/listings/latest?start=1&limit=100&convert=USD")
        assert headers["X-CMC_PRO_API_KEY"] == "test-key"
        return {"data": [{"id": 1, "symbol": "BTC", "cmc_rank": 1}]}

    client = CoinMarketCapClient(api_key="test-key", fetcher=fetch)
    assert client.latest_listings() == client.latest_listings()
    assert calls == 1


def test_coinmarketcap_exact_platform_address_seeds_dexscreener_resolution():
    pair = {**_pair(token="0xcmc-token"), "marketCap": None}

    def dex_fetch(url: str, _timeout: float):
        path = urlparse(url).path
        if path == "/token-profiles/latest/v1" or path == "/token-profiles/recent-updates/v1":
            return []
        if path.startswith("/tokens/v1/"):
            assert "0xcmc-token" in path
            return [pair]
        raise AssertionError(path)

    def cmc_fetch(_url: str, _timeout: float, _headers: dict[str, str]):
        return {
            "data": [{
                "id": 123,
                "slug": "example-token",
                "cmc_rank": 42,
                "circulating_supply": 1_000_000,
                "platform": {"slug": "ethereum", "token_address": "0xcmc-token"},
                "quote": {"USD": {
                    "price": 1.5,
                    "market_cap": 2_000_000,
                    "percent_change_7d": 12.0,
                    "volume_change_24h": 8.0,
                    "market_cap_dominance": 0.2,
                }},
            }],
        }

    provider = DexScreenerUniverseProvider(
        DexScreenerClient(fetcher=dex_fetch),
        chains=("ethereum",),
        cmc_client=CoinMarketCapClient(api_key="test-key", fetcher=cmc_fetch),
        cmc_chains=("ethereum",),
    )
    universe = provider.refresh(now_ms=1_700_010_000_000)

    candidate = universe.core_markets[0]
    assert candidate.cmc_rank == 42
    assert candidate.market_cap_usd == 2_000_000
    assert candidate.cmc_percent_change_7d == 12
    assert candidate.provenance[-1]["provider"] == "coinmarketcap"


def test_coinmarketcap_context_can_be_restricted_to_robinhood():
    from malecns.market.universe import _cmc_context

    context = _cmc_context([
        {"id": 1, "platform": {"slug": "ethereum", "token_address": "0xeth"}},
        {"id": 2, "platform": {"slug": "base", "token_address": "0xbase"}},
        {"id": 3, "platform": {"slug": "robinhood", "token_address": "0xrh"}},
        {"id": 4, "symbol": "NATIVE", "platform": None},
    ], {"robinhood"})

    assert set(context) == {("robinhood", "0xrh")}


def test_candidate_normalizes_pair_identity_and_preserves_provider_fields():
    candidate = candidate_from_pair(_pair(), observed_at_ms=1_700_010_000_000)

    assert candidate is not None
    assert candidate.market_id == "ethereum:0xpair"
    assert candidate.token_id == "ethereum:0xtoken"
    assert candidate.identity.dex_id == "uniswap"
    assert candidate.liquidity_usd == 250_000
    assert candidate.volume_24h_usd == 300_000
    assert candidate.buys_1h == 40
    assert candidate.price_change_1h == 3.2
    assert candidate.price_usd == 1.25
    assert candidate.fdv_usd == 2_000_000
    assert candidate.market_cap_usd == 1_250_000
    assert candidate.market_cap_to_liquidity == 5
    assert candidate.fdv_to_liquidity == 8
    assert candidate.volume_24h_to_market_cap == 0.24
    assert candidate.volume_24h_to_liquidity == 1.2
    assert candidate.txns_24h == 600
    assert candidate.boosts_active == 2
    assert candidate.as_dict()["marketCapToLiquidity"] == 5
    assert candidate.image_url == "https://example.test/exm.png"
    assert candidate.as_dict()["marketId"] == "ethereum:0xpair"


def test_universe_uses_profiles_as_seed_universe_and_filters_dex():
    pair = _pair()

    def fetch(url: str, _timeout: float):
        path = urlparse(url).path
        if path == "/token-profiles/latest/v1":
            return [{"chainId": "ethereum", "tokenAddress": "0xtoken"}]
        if path == "/token-profiles/recent-updates/v1":
            return []
        if path.startswith("/tokens/v1/"):
            return [pair]
        raise AssertionError(path)

    provider = DexScreenerUniverseProvider(
        DexScreenerClient(fetcher=fetch),
        chains=("ethereum",),
        dex_ids=("uniswap",),
        core_target=100,
        recent_target=20,
    )
    universe = provider.refresh(now_ms=1_700_010_000_000)

    assert len(universe.core_markets) == 1
    assert universe.core_markets[0].market_id == "ethereum:0xpair"
    assert universe.recent_markets == ()
    assert universe.as_dict()["candidateCount"] == 1


def test_universe_adds_chain_filtered_search_results_to_world_directory():
    pair = {**_pair("0xsearch-pair", token="0xsearch-token"), "chainId": "robinhood", "dexId": "uniswap-v4"}

    def fetch(url: str, _timeout: float):
        path = urlparse(url).path
        if path == "/token-profiles/latest/v1" or path == "/token-profiles/recent-updates/v1":
            return []
        if path == "/latest/dex/search":
            return {"pairs": [pair]}
        raise AssertionError(path)

    provider = DexScreenerUniverseProvider(
        DexScreenerClient(fetcher=fetch),
        chains=("robinhood",),
        search_queries=("WETH",),
    )
    universe = provider.refresh(now_ms=1_700_010_000_000)

    assert [item.market_id for item in universe.core_markets] == ["robinhood:0xsearch-pair"]


def test_universe_accepts_native_base_venue_when_dex_filter_is_empty():
    pair = {**_pair(), "chainId": "base", "dexId": "aerodrome"}

    def fetch(url: str, _timeout: float):
        path = urlparse(url).path
        if path == "/token-profiles/latest/v1":
            return [{"chainId": "base", "tokenAddress": "0xtoken"}]
        if path == "/token-profiles/recent-updates/v1":
            return []
        if path.startswith("/tokens/v1/"):
            return [pair]
        raise AssertionError(path)

    provider = DexScreenerUniverseProvider(
        DexScreenerClient(fetcher=fetch),
        chains=("base", "robinhood"),
        dex_ids=(),
    )
    universe = provider.refresh(now_ms=1_700_010_000_000)

    assert len(universe.core_markets) == 1
    assert universe.core_markets[0].identity.chain_id == "base"
    assert universe.core_markets[0].identity.dex_id == "aerodrome"


def test_graph_pool_bootstrap_keeps_ethereum_identity_when_base_is_enabled():
    requested: list[str] = []

    def fetch(url: str, _timeout: float):
        path = urlparse(url).path
        requested.append(path)
        if path.startswith("/latest/dex/pairs/"):
            return {"pairs": [_pair("0xgraph-pair")]}
        if path == "/token-profiles/latest/v1" or path == "/token-profiles/recent-updates/v1":
            return []
        raise AssertionError(path)

    provider = DexScreenerUniverseProvider(
        DexScreenerClient(fetcher=fetch),
        chains=("ethereum", "base", "robinhood"),
        pool_bootstrap=lambda **_: [{"id": "0xgraph-pool"}],
    )
    universe = provider.refresh(now_ms=1_700_010_000_000)

    assert universe.core_markets[0].market_id == "ethereum:0xgraph-pair"
    assert "/latest/dex/pairs/ethereum/0xgraph-pool" in requested


def test_selector_filters_quality_and_round_manager_locks_selected_markets():
    good = candidate_from_pair(_pair("0xgood", liquidity=250_000), observed_at_ms=1_700_010_000_000)
    young = candidate_from_pair(
        {
            **_pair("0xyoung", token="0xyoung-token"),
            "pairCreatedAt": 1_700_009_500_000,
        },
        observed_at_ms=1_700_010_000_000,
    )
    assert good is not None and young is not None
    from malecns.market.universe import MarketUniverse

    universe = MarketUniverse((good,), (young,), 1_700_010_000_000)
    selector = MarketSelector(
        MarketEligibility(min_liquidity_usd=100_000, min_volume_24h_usd=100_000, min_pair_age_seconds=3_600),
        active_count=1,
    )
    manager = MarketRoundManager(selector, round_seconds=600)
    first = manager.active_round(universe, now_ms=1_700_010_000_000)
    same = manager.active_round(universe, now_ms=1_700_010_100_000)
    next_round = manager.active_round(universe, now_ms=1_700_010_600_001)

    assert {item.market_id for item in first.markets} == {"ethereum:0xgood", "ethereum:0xyoung"}
    assert [item.market_id for item in first.deep_markets] == ["ethereum:0xgood"]
    assert same.round_number == first.round_number
    assert next_round.round_number != first.round_number
    assert next_round.markets[0].market_id == "ethereum:0xgood"

    selected = selector.select(universe, now_ms=1_700_010_000_000)[0]
    assert selected.discovery_score > 0
    assert "discoveryScore" not in selected.candidate.as_dict()


def test_round_separates_physical_world_capacity_from_deep_observers():
    first = candidate_from_pair(_pair("0xone", token="0xone-token"), observed_at_ms=1_700_010_000_000)
    second = candidate_from_pair(_pair("0xtwo", token="0xtwo-token", liquidity=150_000), observed_at_ms=1_700_010_000_000)
    assert first is not None and second is not None
    from malecns.market.universe import MarketUniverse

    universe = MarketUniverse((first, second), (), 1_700_010_000_000)
    selector = MarketSelector(
        MarketEligibility(min_liquidity_usd=100_000, min_volume_24h_usd=100_000, min_pair_age_seconds=3_600),
        active_count=1,
        world_capacity=2,
    )
    round_state = MarketRoundManager(selector, round_seconds=600).active_round(universe, now_ms=1_700_010_000_000)

    assert len(round_state.markets) == 2
    assert len(round_state.deep_markets) == 1
    assert round_state.deep_markets[0].market_id in {item.market_id for item in round_state.markets}


def test_discovery_replays_partial_cached_round_during_provider_rate_limit():
    from malecns.market.universe import MarketRound, MarketUniverse

    candidate = candidate_from_pair(_pair("0xcached", token="0xcached-token"), observed_at_ms=1_700_010_000_000)
    assert candidate is not None
    universe = MarketUniverse((candidate,), (), 1_700_010_000_000)
    cached_round = MarketRound(
        round_number=4,
        started_at_ms=1_700_010_000_000,
        expires_at_ms=1_700_010_600_000,
        markets=(candidate,),
        deep_markets=(),
    )

    class Cache:
        def load_active(self, _now_ms):
            return universe, cached_round

    provider = DexScreenerUniverseProvider(
        DexScreenerClient(fetcher=lambda *_: (_ for _ in ()).throw(AssertionError("refresh should not run"))),
        chains=("ethereum",),
    )
    discovery = DexScreenerMarketDiscovery(
        provider,
        MarketRoundManager(MarketSelector(world_capacity=100)),
        cache=Cache(),
    )

    round_state = discovery.active_round(now_ms=1_700_010_100_000)

    assert [item.market_id for item in round_state.markets] == ["ethereum:0xcached"]


def test_world_directory_keeps_tracked_low_liquidity_markets_outside_deep_shortlist():
    low_quality = candidate_from_pair(_pair("0xlow", liquidity=10), observed_at_ms=1_700_010_000_000)
    assert low_quality is not None
    from malecns.market.universe import MarketUniverse

    universe = MarketUniverse((low_quality,), (), 1_700_010_000_000)
    selector = MarketSelector(
        MarketEligibility(min_liquidity_usd=100_000, min_volume_24h_usd=100_000, min_pair_age_seconds=3_600),
        active_count=1,
        world_capacity=100,
    )
    round_state = MarketRoundManager(selector).active_round(universe, now_ms=1_700_010_000_000)

    assert round_state.deep_markets == ()
    assert [item.market_id for item in round_state.markets] == ["ethereum:0xlow"]
