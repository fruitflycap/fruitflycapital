from __future__ import annotations

import json

from malecns.market.models import MarketCandidate, MarketIdentity
from malecns.market.supabase_cache import SupabaseConfig, SupabaseMarketCache
from malecns.market.universe import MarketRound, MarketUniverse


class _Response:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def _candidate() -> MarketCandidate:
    return MarketCandidate(
        identity=MarketIdentity("ethereum", "uniswap", "0xpair"),
        base_token_address="0xtoken",
        base_token_symbol="FLY",
        base_token_name="Fruit Fly",
        quote_token_address="0xwusdc",
        quote_token_symbol="USDC",
        represented_token_address="0xtoken",
        liquidity_usd=250_000,
        volume_5m_usd=1_000,
        volume_1h_usd=10_000,
        volume_24h_usd=100_000,
        buys_5m=3,
        sells_5m=1,
        buys_1h=10,
        sells_1h=4,
        price_change_5m=1.2,
        price_change_1h=2.3,
        price_change_24h=4.5,
        pair_created_at_ms=1_000,
        image_url="https://example.test/fly.png",
        websites=({"url": "https://example.test"},),
        socials=({"type": "x", "url": "https://example.test/x"},),
        source="dexscreener",
        provenance=({"provider": "dexscreener"},),
    )


def test_supabase_cache_persists_candidate_metadata_and_round():
    candidate = _candidate()
    round_state = MarketRound(2, 10_000, 20_000, (candidate,))
    universe = MarketUniverse((candidate,), (), 10_000)
    requests = []

    def fake_fetch(request, timeout):
        requests.append(request)
        if request.method == "GET":
            row = {
                "round_id": "10000",
                "round_number": 2,
                "started_at_ms": 10_000,
                "expires_at_ms": 20_000,
                "core_markets": [candidate.as_dict()],
                "recent_markets": [],
                "markets": [candidate.as_dict()],
            }
            return _Response(json.dumps([row]).encode())
        return _Response(b"")

    cache = SupabaseMarketCache(
        SupabaseConfig("https://project.supabase.co", "service", "service"),
        fetch=fake_fetch,
    )
    cache.save(universe, round_state)
    loaded = cache.load_active(11_000)

    assert loaded is not None
    loaded_universe, loaded_round = loaded
    assert loaded_universe.all_candidates[0].base_token_name == "Fruit Fly"
    assert loaded_universe.all_candidates[0].image_url.endswith("fly.png")
    assert loaded_round.markets[0].market_id == candidate.market_id
    assert len(requests) == 3
    assert requests[0].headers["Authorization"] == "Bearer service"
    assert requests[-1].headers["Authorization"] == "Bearer service"
