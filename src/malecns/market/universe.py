"""DexScreener market discovery, eligibility, and locked arena rounds.

Discovery answers only: "which markets are available to put in the arena?"
It does not answer whether a market is attractive, safe, profitable, or where
a fly should move. The selected candidates are later observed by a deeper
provider such as The Graph and converted into physical habitat signals.
"""

from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any, Iterable, Mapping

from .dexscreener_client import DexScreenerClient
from .coinmarketcap_client import CoinMarketCapClient
from .models import MarketCandidate, MarketIdentity


@dataclass(frozen=True)
class MarketUniverse:
    core_markets: tuple[MarketCandidate, ...]
    recent_markets: tuple[MarketCandidate, ...]
    refreshed_at_ms: int

    @property
    def all_candidates(self) -> tuple[MarketCandidate, ...]:
        seen: set[str] = set()
        result: list[MarketCandidate] = []
        for candidate in (*self.core_markets, *self.recent_markets):
            if candidate.market_id in seen:
                continue
            seen.add(candidate.market_id)
            result.append(candidate)
        return tuple(result)

    def as_dict(self) -> dict[str, Any]:
        return {
            "coreCount": len(self.core_markets),
            "recentCount": len(self.recent_markets),
            "candidateCount": len(self.all_candidates),
            "refreshedAtMs": self.refreshed_at_ms,
            "coreMarkets": [candidate.as_dict() for candidate in self.core_markets],
            "recentMarkets": [candidate.as_dict() for candidate in self.recent_markets],
        }


@dataclass
class DexScreenerUniverseProvider:
    """Build a bounded market universe from documented DexScreener feeds."""

    client: DexScreenerClient
    # Keep Ethereum for continuity, while including the chains used by the
    # deployed demo. An empty dex_ids tuple means all DEXs on those chains.
    chains: tuple[str, ...] = ("robinhood",)
    dex_ids: tuple[str, ...] = ()
    core_target: int = 100
    recent_target: int = 20
    profile_limit: int = 60
    seed_tokens: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    pool_bootstrap: Callable[..., list[dict[str, Any]]] | None = None
    cmc_client: CoinMarketCapClient | None = None
    cmc_limit: int = 100
    # Search is an additive directory feed. Keep it opt-in for direct callers
    # and tests; the environment-backed production provider supplies the
    # Robinhood quote/asset queries below.
    search_queries: tuple[str, ...] = ()
    # CMC's ranked listings are global. Keep that enrichment scoped to the
    # chain we actually want to seed from CMC instead of importing unrelated
    # networks from the same table. This is intentionally separate from
    # `chains`, which still controls DexScreener/profile discovery.
    cmc_chains: tuple[str, ...] = ("robinhood",)
    last_bootstrap_error: str | None = field(default=None, init=False)
    last_cmc_error: str | None = field(default=None, init=False)
    last_cmc_count: int = field(default=0, init=False)

    def refresh(self, *, now_ms: int | None = None, force: bool = False) -> MarketUniverse:
        observed_at_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        allowed_chains = {_norm(value) for value in self.chains if str(value).strip()}
        allowed_dexes = {_norm(value) for value in self.dex_ids if str(value).strip()}

        latest_profiles = self.client.latest_token_profiles(force=force)
        recent_profiles = self.client.recent_token_profiles(force=force)
        core_addresses = _profile_addresses(latest_profiles, allowed_chains, self.profile_limit)
        recent_addresses = _profile_addresses(recent_profiles, allowed_chains, self.profile_limit)
        for chain_id, addresses in self.seed_tokens.items():
            chain = _norm(chain_id)
            if chain in allowed_chains:
                core_addresses.setdefault(chain, []).extend(addresses)

        cmc_context: dict[tuple[str, str], Mapping[str, Any]] = {}
        self.last_cmc_error = None
        self.last_cmc_count = 0
        if self.cmc_client is not None:
            try:
                cmc_listings = self.cmc_client.latest_listings(limit=self.cmc_limit, force=force)
                cmc_allowed_chains = {
                    _norm(value) for value in self.cmc_chains if str(value).strip()
                } & allowed_chains
                cmc_context = _cmc_context(cmc_listings, cmc_allowed_chains)
                # Report the accepted CMC rows, not the global response size,
                # so telemetry/UI cannot imply that other networks entered the
                # Robinhood market universe.
                self.last_cmc_count = len(cmc_context)
                for (chain, address) in cmc_context:
                    core_addresses.setdefault(chain, []).append(address)
            except Exception as exc:
                # CMC broad-market ranking is additive. A temporary CMC
                # failure must not take down DexScreener/Graph discovery.
                self.last_cmc_error = str(exc)

        profile_class: dict[tuple[str, str], str] = {}
        for chain, addresses in core_addresses.items():
            for address in addresses:
                profile_class[(chain, _norm(address))] = "core"
        for chain, address in cmc_context:
            profile_class[(chain, address)] = "core"
        for chain, addresses in recent_addresses.items():
            for address in addresses:
                profile_class.setdefault((chain, _norm(address)), "recent")

        core_pairs: dict[str, MarketCandidate] = {}
        recent_pairs: dict[str, MarketCandidate] = {}

        # DexScreener's profile feeds are intentionally not treated as an
        # exhaustive Ethereum pool index. When a configured Graph observer can
        # enumerate pools, use it only to discover pair addresses, then ask
        # DexScreener for the normalized pair metadata.
        self.last_bootstrap_error = None
        if self.pool_bootstrap is not None:
            try:
                bootstrap_pools = self.pool_bootstrap(first=max(1, min(self.core_target, 100)))
            except Exception as exc:
                bootstrap_pools = []
                self.last_bootstrap_error = str(exc)
            # The configured Graph bootstrap is currently an Ethereum
            # Uniswap-style pool index. Do not let the alphabetical order of
            # the enabled chains relabel those pool IDs as Base or Robinhood.
            default_chain = "ethereum" if "ethereum" in allowed_chains else next(iter(sorted(allowed_chains)), "ethereum")
            for pool in bootstrap_pools:
                if not isinstance(pool, Mapping):
                    continue
                chain_id = _norm(pool.get("chainId") or default_chain)
                pair_address = _optional_norm(pool.get("pairAddress") or pool.get("id"))
                if chain_id not in allowed_chains or not pair_address:
                    continue
                try:
                    dex_pairs = self.client.pair(chain_id, pair_address, force=force)
                except Exception as exc:
                    self.last_bootstrap_error = str(exc)
                    continue
                for pair in dex_pairs:
                    candidate = candidate_from_pair(pair, observed_at_ms=observed_at_ms, cmc_context=cmc_context)
                    if candidate is None or (allowed_dexes and _norm(candidate.identity.dex_id) not in allowed_dexes):
                        continue
                    current = core_pairs.get(candidate.market_id)
                    if current is None or _candidate_quality(candidate) > _candidate_quality(current):
                        core_pairs[candidate.market_id] = candidate

        for chain_id in sorted(allowed_chains):
            addresses = _unique_addresses(
                [*core_addresses.get(chain_id, ()), *recent_addresses.get(chain_id, ())]
            )
            if not addresses:
                continue
            for pair in self.client.tokens(chain_id, addresses, force=force):
                candidate = candidate_from_pair(
                    pair,
                    profile_class=profile_class,
                    observed_at_ms=observed_at_ms,
                    cmc_context=cmc_context,
                )
                if candidate is None or (allowed_dexes and _norm(candidate.identity.dex_id) not in allowed_dexes):
                    continue
                target = core_pairs if _candidate_class(candidate, profile_class) == "core" else recent_pairs
                current = target.get(candidate.market_id)
                if current is None or _candidate_quality(candidate) > _candidate_quality(current):
                    target[candidate.market_id] = candidate

        # Profile feeds are intentionally small and do not enumerate every
        # active pair. Search common quote/asset names to widen the public
        # directory, then retain only exact pairs on the allowed chain(s).
        # Search results are discovery inputs only; they do not influence fly
        # movement or make a token execution-eligible.
        for query in _unique_strings(self.search_queries):
            try:
                search_pairs = self.client.search(query, force=force)
            except Exception:
                continue
            for pair in search_pairs:
                if _norm(pair.get("chainId")) not in allowed_chains:
                    continue
                candidate = candidate_from_pair(
                    pair,
                    profile_class=profile_class,
                    observed_at_ms=observed_at_ms,
                    cmc_context=cmc_context,
                )
                if candidate is None or (allowed_dexes and _norm(candidate.identity.dex_id) not in allowed_dexes):
                    continue
                current = core_pairs.get(candidate.market_id)
                if current is None or _candidate_quality(candidate) > _candidate_quality(current):
                    core_pairs[candidate.market_id] = candidate

        core = tuple(sorted(core_pairs.values(), key=_universe_sort_key)[: max(0, self.core_target)])
        recent = tuple(sorted(recent_pairs.values(), key=_universe_sort_key)[: max(0, self.recent_target)])
        return MarketUniverse(core, recent, observed_at_ms)


@dataclass(frozen=True)
class MarketEligibility:
    """Quality and scope checks used before selecting active arena markets."""

    chains: tuple[str, ...] = ("ethereum", "base", "robinhood")
    dex_ids: tuple[str, ...] = ()
    min_liquidity_usd: float = 100_000.0
    min_volume_24h_usd: float = 100_000.0
    min_pair_age_seconds: int = 3_600

    def accepts(self, candidate: MarketCandidate, *, now_ms: int | None = None) -> bool:
        current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        if _norm(candidate.identity.chain_id) not in {_norm(value) for value in self.chains}:
            return False
        # DEX filtering is optional so Base and Robinhood can use their native
        # venues without being silently removed by an Ethereum-only list.
        if self.dex_ids and _norm(candidate.identity.dex_id) not in {_norm(value) for value in self.dex_ids}:
            return False
        if not candidate.identity.pair_address or not candidate.represented_token_address:
            return False
        if candidate.liquidity_usd < self.min_liquidity_usd:
            return False
        if (candidate.volume_24h_usd or 0.0) < self.min_volume_24h_usd:
            return False
        if candidate.pair_created_at_ms is None:
            return False
        age_seconds = max(0.0, (current_ms - candidate.pair_created_at_ms) / 1000.0)
        return age_seconds >= self.min_pair_age_seconds

    def accepts_for_world(self, candidate: MarketCandidate, *, now_ms: int | None = None) -> bool:
        """Keep tracked markets visible without calling them investable.

        World inclusion still requires a real chain/pair/token identity, but
        deliberately does not apply liquidity, volume, or pair-age thresholds.
        Those thresholds belong to deep analysis and the execution guard, not
        to the city directory. A new/illiquid habitat can be visible while
        remaining ineligible for execution.
        """
        if _norm(candidate.identity.chain_id) not in {_norm(value) for value in self.chains}:
            return False
        if self.dex_ids and _norm(candidate.identity.dex_id) not in {_norm(value) for value in self.dex_ids}:
            return False
        if not candidate.identity.pair_address or not candidate.represented_token_address:
            return False
        return True


@dataclass(frozen=True)
class SelectedMarket:
    """Internal selection result; its score never enters TokenState or sensors."""

    candidate: MarketCandidate
    discovery_score: float


@dataclass
class MarketSelector:
    eligibility: MarketEligibility = field(default_factory=MarketEligibility)
    # Kept as active_count for compatibility with existing callers; it is the
    # number of markets sent to a deep observer, not the physical world size.
    active_count: int = 12
    world_capacity: int = 100

    def eligible(self, universe: MarketUniverse, *, now_ms: int | None = None) -> tuple[MarketCandidate, ...]:
        current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        candidates = [candidate for candidate in universe.all_candidates if self.eligibility.accepts(candidate, now_ms=current_ms)]
        # One representative pair per chain-aware token identity prevents the
        # arena from filling with several pools for the same token.
        by_token: dict[str, MarketCandidate] = {}
        for candidate in candidates:
            previous = by_token.get(candidate.token_id)
            if previous is None or _candidate_quality(candidate) > _candidate_quality(previous):
                by_token[candidate.token_id] = candidate
        return tuple(sorted(by_token.values(), key=lambda item: item.market_id))

    def select(self, universe: MarketUniverse, *, now_ms: int | None = None) -> tuple[SelectedMarket, ...]:
        return self._ranked(universe, now_ms=now_ms)[: max(0, self.active_count)]

    def select_world(self, universe: MarketUniverse, *, now_ms: int | None = None) -> tuple[MarketCandidate, ...]:
        # The physical city is a market directory, not an execution shortlist.
        # Keep chain/DEX/identity and minimum age checks, but do not hide a
        # tracked market merely because its liquidity or volume is below the
        # stricter deep-observer/execution thresholds.
        current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        scored = [
            SelectedMarket(candidate, _discovery_score(candidate))
            for candidate in self.world_eligible(universe, now_ms=current_ms)
        ]
        scored.sort(key=lambda item: (-item.discovery_score, item.candidate.market_id))
        return tuple(item.candidate for item in scored[: max(0, self.world_capacity)])

    def world_eligible(self, universe: MarketUniverse, *, now_ms: int | None = None) -> tuple[MarketCandidate, ...]:
        current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        candidates = [
            candidate for candidate in universe.all_candidates
            if self.eligibility.accepts_for_world(candidate, now_ms=current_ms)
        ]
        by_token: dict[str, MarketCandidate] = {}
        for candidate in candidates:
            previous = by_token.get(candidate.token_id)
            if previous is None or _candidate_quality(candidate) > _candidate_quality(previous):
                by_token[candidate.token_id] = candidate
        return tuple(sorted(by_token.values(), key=lambda item: item.market_id))

    def _ranked(self, universe: MarketUniverse, *, now_ms: int | None = None) -> list[SelectedMarket]:
        current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        scored = [
            SelectedMarket(candidate, _discovery_score(candidate))
            for candidate in self.eligible(universe, now_ms=current_ms)
        ]
        scored.sort(key=lambda item: (-item.discovery_score, item.candidate.market_id))
        return scored


@dataclass(frozen=True)
class MarketRound:
    round_number: int
    started_at_ms: int
    expires_at_ms: int
    markets: tuple[MarketCandidate, ...]
    deep_markets: tuple[MarketCandidate, ...] = ()

    def is_active(self, now_ms: int) -> bool:
        return int(now_ms) < self.expires_at_ms

    def as_dict(self) -> dict[str, Any]:
        return {
            "round": self.round_number,
            "startedAtMs": self.started_at_ms,
            "expiresAtMs": self.expires_at_ms,
            "markets": [market.as_dict() for market in self.markets],
            "deepMarkets": [market.as_dict() for market in self.deep_markets],
        }


@dataclass
class MarketRoundManager:
    selector: MarketSelector
    round_seconds: int = 600
    _current: MarketRound | None = field(default=None, init=False, repr=False)
    _round_counter: int = field(default=0, init=False, repr=False)

    def active_round(self, universe: MarketUniverse, *, now_ms: int | None = None, force: bool = False) -> MarketRound:
        current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        if not force and self._current is not None and self._current.is_active(current_ms):
            return self._current
        deep_selected = self.selector.select(universe, now_ms=current_ms)
        world_selected = self.selector.select_world(universe, now_ms=current_ms)
        self._round_counter += 1
        duration_ms = max(1, int(self.round_seconds)) * 1000
        self._current = MarketRound(
            round_number=self._round_counter,
            started_at_ms=current_ms,
            expires_at_ms=current_ms + duration_ms,
            markets=tuple(world_selected),
            deep_markets=tuple(item.candidate for item in deep_selected),
        )
        return self._current


@dataclass
class DexScreenerMarketDiscovery:
    """Cached universe + locked selection facade used by the market engine."""

    universe_provider: DexScreenerUniverseProvider
    rounds: MarketRoundManager
    refresh_seconds: float = 300.0
    cache: Any | None = None
    _universe: MarketUniverse | None = field(default=None, init=False, repr=False)
    _last_refresh_monotonic: float = field(default=0.0, init=False, repr=False)
    _last_cached_round_started_ms: int | None = field(default=None, init=False, repr=False)
    last_error: str | None = field(default=None, init=False)

    @classmethod
    def from_env(cls, *, graph_client: Any | None = None) -> "DexScreenerMarketDiscovery | None":
        enabled = os.getenv("NEUROSWARM_MARKET_DISCOVERY_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
        if not enabled:
            return None
        # This public experience is Robinhood-only. Keep the environment key
        # for compatibility, but do not let an older deployment value such as
        # `ethereum,base,robinhood` widen the live market universe again.
        chains = ("robinhood",)
        configured_dex_ids = os.getenv("NEUROSWARM_MARKET_DEX_IDS", "").strip()
        dex_ids = _csv(configured_dex_ids) if configured_dex_ids else ()
        seeds = _seed_tokens(os.getenv("NEUROSWARM_MARKET_DISCOVERY_TOKEN_ADDRESSES", ""), chains[0])
        client = DexScreenerClient(
            base_url=os.getenv("DEXSCREENER_API_BASE_URL", "https://api.dexscreener.com").strip() or "https://api.dexscreener.com",
            timeout_seconds=float(os.getenv("DEXSCREENER_TIMEOUT_SECONDS", "10")),
            cache_ttl_seconds=float(os.getenv("DEXSCREENER_CACHE_TTL_SECONDS", "60")),
        )
        eligibility = MarketEligibility(
            chains=chains,
            dex_ids=dex_ids,
            min_liquidity_usd=float(os.getenv("NEUROSWARM_MARKET_MIN_LIQUIDITY_USD", "100000")),
            min_volume_24h_usd=float(os.getenv("NEUROSWARM_MARKET_MIN_VOLUME_24H_USD", "100000")),
            min_pair_age_seconds=int(os.getenv("NEUROSWARM_MARKET_MIN_PAIR_AGE_SECONDS", "3600")),
        )
        provider = DexScreenerUniverseProvider(
            client,
            chains=chains,
            dex_ids=dex_ids,
            core_target=int(os.getenv("NEUROSWARM_MARKET_CORE_TARGET", "150")),
            recent_target=int(os.getenv("NEUROSWARM_MARKET_RECENT_TARGET", "50")),
            profile_limit=int(os.getenv("NEUROSWARM_MARKET_PROFILE_LIMIT", "100")),
            seed_tokens=seeds,
            pool_bootstrap=graph_client.top_pools if graph_client is not None else None,
            cmc_client=CoinMarketCapClient.from_env(),
            cmc_limit=int(os.getenv("CMC_LISTINGS_LIMIT", "100")),
            cmc_chains=_csv(os.getenv("CMC_ALLOWED_CHAINS", "robinhood")) or ("robinhood",),
            search_queries=_csv(os.getenv(
                "NEUROSWARM_MARKET_SEARCH_QUERIES",
                "WETH,ETH,USDG,USDC,USDT,NVDA,AAPL,cbBTC,SPCX,ROBINHOOD,ROBIN,FLY,COIN,STOCK,SWAP,AI,BTC,WBTC,A,B,C,D,E,F,G,H,I,J,K,L,M,N,O,P,Q,R,S,T,U,V,W,X,Y,Z",
            )),
        )
        selector = MarketSelector(
            eligibility,
            active_count=int(os.getenv("NEUROSWARM_MARKET_DEEP_OBSERVER_COUNT", "12")),
            world_capacity=int(os.getenv("NEUROSWARM_MARKET_WORLD_CAPACITY", "150")),
        )
        from .supabase_cache import SupabaseMarketCache

        return cls(
            provider,
            MarketRoundManager(selector, round_seconds=int(os.getenv("NEUROSWARM_MARKET_ROUND_SECONDS", "600"))),
            refresh_seconds=float(os.getenv("NEUROSWARM_MARKET_CACHE_TTL_SECONDS", os.getenv("NEUROSWARM_MARKET_DISCOVERY_REFRESH_SECONDS", "300"))),
            cache=SupabaseMarketCache.from_env(),
        )

    def active_round(self, *, now_ms: int | None = None, force: bool = False) -> MarketRound:
        current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        now_monotonic = time.monotonic()
        if force or self._universe is None or now_monotonic - self._last_refresh_monotonic >= self.refresh_seconds:
            cached_is_stale = False
            if not force and self._universe is None and self.cache is not None:
                try:
                    cached = self.cache.load_active(current_ms)
                except Exception as exc:
                    cached = None
                    self.last_error = f"cache read: {exc}"
                if cached is None:
                    load_latest = getattr(self.cache, "load_latest", None)
                    if callable(load_latest):
                        try:
                            cached = load_latest(
                                current_ms,
                                max_age_ms=int(float(os.getenv("NEUROSWARM_MARKET_STALE_CACHE_MAX_SECONDS", "86400")) * 1000),
                            )
                            cached_is_stale = cached is not None
                        except Exception as exc:
                            self.last_error = f"stale cache read: {exc}"
                if cached is not None:
                    self._universe, cached_round = cached
                    # A cached round may be smaller than the current city
                    # capacity because it was written by an earlier deploy,
                    # a provider response was partial, or DexScreener is
                    # temporarily rate-limiting refreshes. A valid non-empty
                    # round is still preferable to an empty scene; the next
                    # successful refresh can grow it to the new capacity.
                    if not cached_round.markets:
                        self._universe = None
                    elif any(
                        _norm(market.identity.chain_id) not in {
                            _norm(value) for value in self.universe_provider.chains
                        }
                        for market in cached_round.markets
                    ):
                        # Never replay a snapshot that contains markets from a
                        # chain no longer allowed by the current deployment.
                        self._universe = None
                    else:
                        self.rounds._current = cached_round
                        self.rounds._round_counter = max(self.rounds._round_counter, cached_round.round_number)
                        self._last_refresh_monotonic = now_monotonic
                        self._last_cached_round_started_ms = cached_round.started_at_ms
                        # A round written before the broad search directory
                        # was enabled can be valid but underfilled. Refresh
                        # it once on startup so deployments do not stay at an
                        # old 39/40-place snapshot until the round expires.
                        # The cached round remains installed as the fallback
                        # if the provider is unavailable.
                        needs_directory_expansion = bool(self.universe_provider.search_queries) and len(cached_round.markets) < self.rounds.selector.world_capacity
                        if needs_directory_expansion:
                            self.last_error = "refreshing underfilled cached market round"
                        else:
                            if cached_is_stale:
                                self.last_error = "serving stale cached market round"
                            return cached_round
            try:
                self._universe = self.universe_provider.refresh(now_ms=current_ms, force=force)
                self._last_refresh_monotonic = now_monotonic
                self.last_error = self.universe_provider.last_bootstrap_error
            except Exception as exc:
                self.last_error = str(exc)
                if self._universe is None:
                    raise
        round_state = self.rounds.active_round(self._universe, now_ms=current_ms, force=force)
        if self.cache is not None and round_state.started_at_ms != self._last_cached_round_started_ms:
            try:
                self.cache.save(self._universe, round_state)
                self._last_cached_round_started_ms = round_state.started_at_ms
            except Exception as exc:
                # Persistence must never take the live market feed down.
                self.last_error = f"cache write: {exc}"
        return round_state

    def graph_habitat_configs(self, *, now_ms: int | None = None, force: bool = False) -> list[dict[str, Any]]:
        """Convert selected candidates to the existing GraphProvider contract."""

        return [
            self._config_for(candidate)
            for candidate in self.active_round(now_ms=now_ms, force=force).deep_markets
            if _norm(candidate.identity.chain_id) == "ethereum"
            and _norm(candidate.identity.dex_id) in {"uniswap", "uniswap-v3"}
        ]

    def world_habitat_configs(self, *, now_ms: int | None = None, force: bool = False) -> list[dict[str, Any]]:
        """Convert every physically present market to a lightweight config."""

        return [self._config_for(candidate) for candidate in self.active_round(now_ms=now_ms, force=force).markets]

    @staticmethod
    def _config_for(candidate: MarketCandidate) -> dict[str, Any]:
        label = candidate.base_token_symbol or candidate.base_token_name or candidate.market_id
        if candidate.base_token_name and candidate.base_token_symbol and candidate.base_token_name.lower() != candidate.base_token_symbol.lower():
            label = f"{candidate.base_token_symbol} · {candidate.base_token_name}"
        return {
            "id": candidate.market_id,
            "label": label,
            "marketName": candidate.base_token_name,
            "imageUrl": candidate.image_url,
            "poolId": candidate.identity.pair_address,
            "tokenAddress": candidate.represented_token_address,
            "chainId": candidate.identity.chain_id,
            "dexId": candidate.identity.dex_id,
            "pairAddress": candidate.identity.pair_address,
            "dexscreenerUrl": _candidate_dexscreener_url(candidate),
            "observedAtMs": int(candidate.provenance[0].get("observedAtMs", 0)) if candidate.provenance else 0,
            "lightweight": True,
            "liquidityUsd": candidate.liquidity_usd,
            "volume5mUsd": candidate.volume_5m_usd,
            "volume1hUsd": candidate.volume_1h_usd,
            "volume24hUsd": candidate.volume_24h_usd,
            "priceUsd": candidate.price_usd,
            "priceNative": candidate.price_native,
            "marketCapUsd": candidate.market_cap_usd,
            "fdvUsd": candidate.fdv_usd,
            "liquidityBase": candidate.liquidity_base,
            "liquidityQuote": candidate.liquidity_quote,
            "txns24h": candidate.txns_24h,
            "boostsActive": candidate.boosts_active,
            "pairAgeHours": candidate.pair_age_hours,
            "marketCapToLiquidity": candidate.market_cap_to_liquidity,
            "fdvToLiquidity": candidate.fdv_to_liquidity,
            "volume24hToMarketCap": candidate.volume_24h_to_market_cap,
            "volume24hToLiquidity": candidate.volume_24h_to_liquidity,
            "cmcId": candidate.cmc_id,
            "cmcSlug": candidate.cmc_slug,
            "cmcRank": candidate.cmc_rank,
            "circulatingSupply": candidate.circulating_supply,
            "totalSupply": candidate.total_supply,
            "cmcPercentChange7d": candidate.cmc_percent_change_7d,
            "cmcVolumeChange24h": candidate.cmc_volume_change_24h,
            "marketCapDominance": candidate.market_cap_dominance,
            "buys5m": candidate.buys_5m,
            "sells5m": candidate.sells_5m,
        }

    def as_dict(self, *, now_ms: int | None = None) -> dict[str, Any]:
        round_state = self.active_round(now_ms=now_ms)
        return {
            "source": "dexscreener",
            "worldCapacity": self.rounds.selector.world_capacity,
            "deepObserverCount": self.rounds.selector.active_count,
            "universe": self._universe.as_dict() if self._universe else None,
            "round": round_state.as_dict(),
            "lastError": self.last_error,
            "cmcRankedCount": self.universe_provider.last_cmc_count,
            "cmcError": self.universe_provider.last_cmc_error,
        }


def candidate_from_pair(
    pair: Mapping[str, Any],
    *,
    profile_class: Mapping[tuple[str, str], str] | None = None,
    observed_at_ms: int | None = None,
    cmc_context: Mapping[tuple[str, str], Mapping[str, Any]] | None = None,
) -> MarketCandidate | None:
    """Normalize one DexScreener pair payload without adding derived bias."""

    chain_id = _norm(pair.get("chainId"))
    dex_id = _norm(pair.get("dexId"))
    pair_address = _norm(pair.get("pairAddress"))
    base = pair.get("baseToken") if isinstance(pair.get("baseToken"), Mapping) else {}
    quote = pair.get("quoteToken") if isinstance(pair.get("quoteToken"), Mapping) else {}
    base_address = _norm(base.get("address"))
    if not chain_id or not dex_id or not pair_address or not base_address:
        return None
    quote_address = _optional_norm(quote.get("address"))
    liquidity = pair.get("liquidity") if isinstance(pair.get("liquidity"), Mapping) else {}
    volume = pair.get("volume") if isinstance(pair.get("volume"), Mapping) else {}
    txns = pair.get("txns") if isinstance(pair.get("txns"), Mapping) else {}
    price_change = pair.get("priceChange") if isinstance(pair.get("priceChange"), Mapping) else {}
    info = pair.get("info") if isinstance(pair.get("info"), Mapping) else {}
    image_url = _optional_string(info.get("imageUrl")) or _optional_string(pair.get("imageUrl"))
    websites = _dict_tuple(info.get("websites"))
    socials = _dict_tuple(info.get("socials"))
    timestamp_ms = int(time.time() * 1000) if observed_at_ms is None else int(observed_at_ms)
    created_ms = _timestamp_ms(pair.get("pairCreatedAt"))
    price_usd = _optional_number(pair.get("priceUsd"))
    price_native = _optional_number(pair.get("priceNative"))
    fdv_usd = _optional_number(pair.get("fdv"))
    market_cap_usd = _optional_number(pair.get("marketCap"))
    liquidity_usd = _number(liquidity.get("usd"))
    volume_24h_usd = _optional_number(volume.get("h24"))
    pair_age_hours = None
    if created_ms is not None and timestamp_ms >= created_ms:
        pair_age_hours = (timestamp_ms - created_ms) / 3_600_000.0
    market_cap_to_liquidity = _ratio(market_cap_usd, liquidity_usd)
    fdv_to_liquidity = _ratio(fdv_usd, liquidity_usd)
    volume_24h_to_market_cap = _ratio(volume_24h_usd, market_cap_usd)
    volume_24h_to_liquidity = _ratio(volume_24h_usd, liquidity_usd)
    boosts = pair.get("boosts") if isinstance(pair.get("boosts"), Mapping) else {}
    provenance = (
        {
            "provider": "dexscreener",
            "endpoint": "/tokens/v1/{chainId}/{tokenAddresses}",
            "observedAtMs": timestamp_ms,
            "url": _optional_string(pair.get("url")),
        },
    )
    cmc = (cmc_context or {}).get((chain_id, base_address), {})
    cmc_quote = cmc.get("quote", {}).get("USD", {}) if isinstance(cmc.get("quote"), Mapping) else {}
    cmc_market_cap = _optional_number(cmc_quote.get("market_cap")) if isinstance(cmc_quote, Mapping) else None
    cmc_price = _optional_number(cmc_quote.get("price")) if isinstance(cmc_quote, Mapping) else None
    # DexScreener does not include an image on every pair response. Give the
    # browser a deterministic public logo URL so a missing pair-level image
    # never turns into a blank habitat. CMC is preferred for ranked assets;
    # DexScreener's token CDN covers everything else without another API call.
    if not image_url and cmc.get("id"):
        image_url = f"https://s2.coinmarketcap.com/static/img/coins/64x64/{cmc['id']}.png"
    if not image_url:
        image_url = f"https://dd.dexscreener.com/ds-data/tokens/{chain_id}/{base_address}.png"
    if market_cap_usd is None:
        market_cap_usd = cmc_market_cap
    if price_usd is None:
        price_usd = cmc_price
    if cmc:
        provenance = (*provenance, {
            "provider": "coinmarketcap",
            "cmcId": cmc.get("id"),
            "cmcRank": cmc.get("cmc_rank"),
            "slug": cmc.get("slug"),
        })
    return MarketCandidate(
        identity=MarketIdentity(chain_id, dex_id, pair_address),
        base_token_address=base_address,
        base_token_symbol=_optional_string(base.get("symbol")) or "",
        base_token_name=_optional_string(base.get("name")) or "",
        quote_token_address=quote_address,
        quote_token_symbol=_optional_string(quote.get("symbol")),
        represented_token_address=base_address,
        liquidity_usd=liquidity_usd,
        volume_5m_usd=_optional_number(volume.get("m5")),
        volume_1h_usd=_optional_number(volume.get("h1")),
        volume_24h_usd=_optional_number(volume.get("h24")),
        buys_5m=_nested_int(txns, "m5", "buys"),
        sells_5m=_nested_int(txns, "m5", "sells"),
        buys_1h=_nested_int(txns, "h1", "buys"),
        sells_1h=_nested_int(txns, "h1", "sells"),
        price_change_5m=_optional_number(price_change.get("m5")),
        price_change_1h=_optional_number(price_change.get("h1")),
        price_change_24h=_optional_number(price_change.get("h24")),
        pair_created_at_ms=created_ms,
        image_url=image_url,
        websites=websites,
        socials=socials,
        source="dexscreener",
        provenance=provenance,
        price_usd=price_usd,
        price_native=price_native,
        fdv_usd=fdv_usd,
        market_cap_usd=market_cap_usd,
        liquidity_base=_optional_number(liquidity.get("base")),
        liquidity_quote=_optional_number(liquidity.get("quote")),
        txns_24h=_nested_txn_total(txns, "h24"),
        boosts_active=_optional_int(boosts.get("active")),
        pair_age_hours=pair_age_hours,
        market_cap_to_liquidity=market_cap_to_liquidity,
        fdv_to_liquidity=fdv_to_liquidity,
        volume_24h_to_market_cap=volume_24h_to_market_cap,
        volume_24h_to_liquidity=volume_24h_to_liquidity,
        cmc_id=_optional_int(cmc.get("id")),
        cmc_slug=_optional_string(cmc.get("slug")),
        cmc_rank=_optional_int(cmc.get("cmc_rank")),
        circulating_supply=_optional_number(cmc.get("circulating_supply")),
        total_supply=_optional_number(cmc.get("total_supply")),
        cmc_percent_change_7d=_optional_number(cmc_quote.get("percent_change_7d")) if isinstance(cmc_quote, Mapping) else None,
        cmc_volume_change_24h=_optional_number(cmc_quote.get("volume_change_24h")) if isinstance(cmc_quote, Mapping) else None,
        market_cap_dominance=_optional_number(cmc_quote.get("market_cap_dominance")) if isinstance(cmc_quote, Mapping) else None,
    )


def _profile_addresses(profiles: Iterable[Mapping[str, Any]], chains: set[str], limit: int) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for profile in profiles:
        chain_id = _norm(profile.get("chainId"))
        address = _optional_string(profile.get("tokenAddress"))
        if chain_id not in chains or not address:
            continue
        if len(result.get(chain_id, ())) >= max(0, limit):
            continue
        result.setdefault(chain_id, []).append(address)
    return result


def _cmc_context(
    listings: Iterable[Mapping[str, Any]],
    chains: set[str],
) -> dict[tuple[str, str], Mapping[str, Any]]:
    """Index CMC listings only when they carry an exact chain address.

    CMC symbols are intentionally never used as identifiers: symbols can
    collide, while a chain/address pair can be resolved against a real DEX
    pair by DexScreener.
    """

    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    for listing in listings:
        platform = listing.get("platform") if isinstance(listing.get("platform"), Mapping) else None
        if platform is None:
            continue
        chain = _norm(platform.get("slug") or platform.get("name"))
        address = _optional_norm(platform.get("token_address"))
        if chain in chains and address:
            result[(chain, address)] = listing
    return result


def _candidate_class(candidate: MarketCandidate, profile_class: Mapping[tuple[str, str], str]) -> str:
    chain = candidate.identity.chain_id
    if profile_class.get((chain, candidate.base_token_address)) == "core":
        return "core"
    if profile_class.get((chain, candidate.quote_token_address or "")) == "core":
        return "core"
    if profile_class.get((chain, candidate.base_token_address)) == "recent":
        return "recent"
    return "recent"


def _candidate_dexscreener_url(candidate: MarketCandidate) -> str:
    for item in candidate.provenance:
        url = item.get("url")
        if isinstance(url, str) and url.startswith("http"):
            return url
    return f"https://dexscreener.com/{candidate.identity.chain_id}/{candidate.identity.pair_address}"


def _candidate_quality(candidate: MarketCandidate) -> tuple[float, float, str]:
    return (candidate.liquidity_usd, candidate.volume_24h_usd or 0.0, candidate.market_id)


def _universe_sort_key(candidate: MarketCandidate) -> tuple[float, float, str]:
    return (-candidate.liquidity_usd, -(candidate.volume_24h_usd or 0.0), candidate.market_id)


def _discovery_score(candidate: MarketCandidate) -> float:
    """Rank market data for arena inclusion, never for fly attraction."""

    liquidity = math.tanh(max(0.0, candidate.liquidity_usd) / 1_000_000.0)
    volume = math.tanh(max(0.0, candidate.volume_24h_usd or 0.0) / 1_000_000.0)
    transactions = sum(value or 0 for value in (candidate.buys_1h, candidate.sells_1h))
    activity = math.tanh(max(0, transactions) / 200.0)
    movement = math.tanh(abs(candidate.price_change_1h or 0.0) / 10.0)
    return 0.40 * liquidity + 0.30 * volume + 0.20 * activity + 0.10 * movement


def _nested_int(value: Mapping[str, Any], outer: str, inner: str) -> int | None:
    child = value.get(outer)
    return _optional_int(child.get(inner)) if isinstance(child, Mapping) else None


def _nested_txn_total(value: Mapping[str, Any], outer: str) -> int | None:
    child = value.get(outer)
    if not isinstance(child, Mapping):
        return None
    buys = _optional_int(child.get("buys"))
    sells = _optional_int(child.get("sells"))
    if buys is None and sells is None:
        return None
    return (buys or 0) + (sells or 0)


def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _dict_tuple(value: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, list):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))


def _timestamp_ms(value: Any) -> int | None:
    number = _optional_number(value)
    if number is None or number <= 0:
        return None
    return int(number if number >= 1_000_000_000_000 else number * 1000)


def _optional_number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float:
    return _optional_number(value) or 0.0


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_string(value: Any) -> str | None:
    normalized = str(value or "").strip()
    return normalized or None


def _optional_norm(value: Any) -> str | None:
    normalized = _norm(value)
    return normalized or None


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _unique_addresses(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized.lower() not in seen:
            result.append(normalized)
            seen.add(normalized.lower())
    return result


def _unique_strings(values: Iterable[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            result.append(normalized)
            seen.add(key)
    return tuple(result)


def _csv(value: str) -> tuple[str, ...]:
    return tuple(item.strip().lower() for item in str(value or "").split(",") if item.strip())


def _seed_tokens(value: str, default_chain: str) -> dict[str, tuple[str, ...]]:
    result: dict[str, list[str]] = {}
    for item in str(value or "").split(","):
        token = item.strip()
        if not token:
            continue
        if ":" in token:
            chain, address = token.split(":", 1)
        else:
            chain, address = default_chain, token
        result.setdefault(chain.strip().lower(), []).append(address.strip())
    return {chain: tuple(_unique_addresses(addresses)) for chain, addresses in result.items()}
