"""Small REST client for durable market discovery snapshots in Supabase.

The market engine is intentionally usable without Supabase. When configured,
the service-role key is used only by this server-side module to persist the
DexScreener universe and locked arena rounds. The browser never receives it.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .models import MarketCandidate, MarketIdentity

if TYPE_CHECKING:
    from .universe import MarketRound, MarketUniverse


class SupabaseCacheError(RuntimeError):
    """A persistence failure that should not be confused with market data."""


@dataclass(frozen=True)
class SupabaseConfig:
    url: str
    read_key: str
    write_key: str | None
    candidate_table: str = "market_candidates"
    round_table: str = "market_rounds"

    @classmethod
    def from_env(cls) -> "SupabaseConfig | None":
        url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
        read_key = (os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
                    or os.getenv("SUPABASE_ANON_KEY", "").strip())
        if not url or not read_key:
            return None
        service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip() or None
        return cls(
            url=url,
            read_key=read_key,
            write_key=service_key,
            candidate_table=os.getenv("SUPABASE_MARKET_TABLE", "market_candidates").strip() or "market_candidates",
            round_table=os.getenv("SUPABASE_ROUND_TABLE", "market_rounds").strip() or "market_rounds",
        )


@dataclass
class SupabaseMarketCache:
    config: SupabaseConfig
    fetch: Callable[..., Any] = urlopen

    @classmethod
    def from_env(cls) -> "SupabaseMarketCache | None":
        config = SupabaseConfig.from_env()
        return cls(config) if config else None

    @property
    def writable(self) -> bool:
        return self.config.write_key is not None

    def save(self, universe: MarketUniverse, round_state: MarketRound) -> None:
        """Persist both normalized candidate rows and the locked round."""
        if not self.writable:
            return
        candidate_rows = [_candidate_row(candidate) for candidate in universe.all_candidates]
        if candidate_rows:
            self._request(
                "POST",
                self.config.candidate_table,
                query={"on_conflict": "market_id"},
                body=candidate_rows,
                write=True,
                prefer="resolution=merge-duplicates,return=minimal",
            )
        round_row = {
            "round_id": f"{round_state.started_at_ms}",
            "round_number": round_state.round_number,
            "started_at_ms": round_state.started_at_ms,
            "expires_at_ms": round_state.expires_at_ms,
            "core_markets": [candidate.as_dict() for candidate in universe.core_markets],
            "recent_markets": [candidate.as_dict() for candidate in universe.recent_markets],
            "markets": [candidate.as_dict() for candidate in round_state.markets],
            "deep_markets": [candidate.as_dict() for candidate in round_state.deep_markets],
        }
        self._request(
            "POST",
            self.config.round_table,
            query={"on_conflict": "round_id"},
            body=[round_row],
            write=True,
            prefer="resolution=merge-duplicates,return=minimal",
        )

    def load_active(self, now_ms: int) -> tuple[MarketUniverse, MarketRound] | None:
        """Load the newest non-expired arena round, if one is available."""
        return self._load_round(
            {
                "select": "*",
                "expires_at_ms": f"gt.{int(now_ms)}",
                "order": "started_at_ms.desc",
                "limit": "1",
            },
            now_ms,
        )

    def load_latest(self, now_ms: int, *, max_age_ms: int) -> tuple[MarketUniverse, MarketRound] | None:
        """Load a bounded stale round for outages/rate limits."""
        lower_bound = max(0, int(now_ms) - max(0, int(max_age_ms)))
        return self._load_round(
            {
                "select": "*",
                "started_at_ms": f"gte.{lower_bound}",
                "order": "started_at_ms.desc",
                "limit": "1",
            },
            now_ms,
        )

    def _load_round(self, query: Mapping[str, str], now_ms: int) -> tuple[MarketUniverse, MarketRound] | None:
        from .universe import MarketRound, MarketUniverse

        rows = self._request("GET", self.config.round_table, query=query, write=False)
        if not isinstance(rows, list) or not rows:
            return None
        row = rows[0]
        if not isinstance(row, Mapping):
            return None
        try:
            core = tuple(_candidate_from_dict(item) for item in row.get("core_markets", []))
            recent = tuple(_candidate_from_dict(item) for item in row.get("recent_markets", []))
            markets = tuple(_candidate_from_dict(item) for item in row.get("markets", []))
            deep_markets = tuple(_candidate_from_dict(item) for item in row.get("deep_markets", row.get("deepMarkets", [])))
            universe = MarketUniverse(core, recent, int(row.get("started_at_ms", now_ms)))
            round_state = MarketRound(
                round_number=int(row.get("round_number", 0)),
                started_at_ms=int(row["started_at_ms"]),
                expires_at_ms=int(row["expires_at_ms"]),
                markets=markets,
                deep_markets=deep_markets,
            )
            return universe, round_state
        except (KeyError, TypeError, ValueError) as exc:
            raise SupabaseCacheError(f"invalid cached market round: {exc}") from exc

    def _request(
        self,
        method: str,
        table: str,
        *,
        query: Mapping[str, str],
        write: bool,
        body: Any = None,
        prefer: str | None = None,
    ) -> Any:
        key = self.config.write_key if write else self.config.read_key
        if key is None:
            return None
        url = f"{self.config.url}/rest/v1/{table}"
        if query:
            url = f"{url}?{urlencode(query)}"
        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        if prefer:
            headers["Prefer"] = prefer
        request = Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
        try:
            with self.fetch(request, timeout=float(os.getenv("SUPABASE_TIMEOUT_SECONDS", "8"))) as response:
                payload = response.read()
        except Exception as exc:
            raise SupabaseCacheError(f"Supabase {method} {table} failed: {exc}") from exc
        if not payload:
            return None
        try:
            decoded = json.loads(payload.decode())
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SupabaseCacheError(f"Supabase returned invalid JSON for {table}") from exc
        return decoded


def _candidate_row(candidate: MarketCandidate) -> dict[str, Any]:
    payload = candidate.as_dict()
    return {
        "market_id": candidate.market_id,
        "token_id": candidate.token_id,
        "chain_id": candidate.identity.chain_id,
        "dex_id": candidate.identity.dex_id,
        "pair_address": candidate.identity.pair_address,
        "represented_token_address": candidate.represented_token_address,
        "symbol": candidate.base_token_symbol,
        "name": candidate.base_token_name,
        "quote_symbol": candidate.quote_token_symbol,
        "image_url": candidate.image_url,
        "liquidity_usd": candidate.liquidity_usd,
        "volume_5m_usd": candidate.volume_5m_usd,
        "volume_1h_usd": candidate.volume_1h_usd,
        "volume_24h_usd": candidate.volume_24h_usd,
        "buys_5m": candidate.buys_5m,
        "sells_5m": candidate.sells_5m,
        "buys_1h": candidate.buys_1h,
        "sells_1h": candidate.sells_1h,
        "price_change_5m": candidate.price_change_5m,
        "price_change_1h": candidate.price_change_1h,
        "price_change_24h": candidate.price_change_24h,
        "pair_created_at_ms": candidate.pair_created_at_ms,
        "websites": list(candidate.websites),
        "socials": list(candidate.socials),
        # `source` is retained in the JSON payload/provenance. Keep the
        # top-level insert compatible with the original cache migration,
        # which intentionally stores provider metadata in those JSON fields.
        "provenance": list(candidate.provenance),
        "payload": payload,
        "price_usd": candidate.price_usd,
        "price_native": candidate.price_native,
        "fdv_usd": candidate.fdv_usd,
        "market_cap_usd": candidate.market_cap_usd,
        "liquidity_base": candidate.liquidity_base,
        "liquidity_quote": candidate.liquidity_quote,
        "txns_24h": candidate.txns_24h,
        "boosts_active": candidate.boosts_active,
        "pair_age_hours": candidate.pair_age_hours,
        "market_cap_to_liquidity": candidate.market_cap_to_liquidity,
        "fdv_to_liquidity": candidate.fdv_to_liquidity,
        "volume_24h_to_market_cap": candidate.volume_24h_to_market_cap,
        "volume_24h_to_liquidity": candidate.volume_24h_to_liquidity,
        "cmc_id": candidate.cmc_id,
        "cmc_slug": candidate.cmc_slug,
        "cmc_rank": candidate.cmc_rank,
        "circulating_supply": candidate.circulating_supply,
        "total_supply": candidate.total_supply,
        "cmc_percent_change_7d": candidate.cmc_percent_change_7d,
        "cmc_volume_change_24h": candidate.cmc_volume_change_24h,
        "market_cap_dominance": candidate.market_cap_dominance,
    }


def _candidate_from_dict(value: Any) -> MarketCandidate:
    if not isinstance(value, Mapping):
        raise TypeError("candidate is not an object")
    identity = MarketIdentity(
        str(value["chainId"]),
        str(value["dexId"]),
        str(value["pairAddress"]),
    )
    base = value.get("baseToken") if isinstance(value.get("baseToken"), Mapping) else {}
    quote = value.get("quoteToken") if isinstance(value.get("quoteToken"), Mapping) else {}
    return MarketCandidate(
        identity=identity,
        base_token_address=str(base.get("address", "")),
        base_token_symbol=str(base.get("symbol", "")),
        base_token_name=str(base.get("name", "")),
        quote_token_address=quote.get("address"),
        quote_token_symbol=quote.get("symbol"),
        represented_token_address=str(value["representedTokenAddress"]),
        liquidity_usd=float(value.get("liquidityUsd") or 0),
        volume_5m_usd=_optional_float(value.get("volume5mUsd")),
        volume_1h_usd=_optional_float(value.get("volume1hUsd")),
        volume_24h_usd=_optional_float(value.get("volume24hUsd")),
        buys_5m=_optional_int(value.get("buys5m")),
        sells_5m=_optional_int(value.get("sells5m")),
        buys_1h=_optional_int(value.get("buys1h")),
        sells_1h=_optional_int(value.get("sells1h")),
        price_change_5m=_optional_float(value.get("priceChange5m")),
        price_change_1h=_optional_float(value.get("priceChange1h")),
        price_change_24h=_optional_float(value.get("priceChange24h")),
        pair_created_at_ms=_optional_int(value.get("pairCreatedAtMs")),
        image_url=value.get("imageUrl"),
        websites=tuple(value.get("websites") or ()),
        socials=tuple(value.get("socials") or ()),
        source=str(value.get("source", "dexscreener")),
        provenance=tuple(value.get("provenance") or ()),
        price_usd=_optional_float(value.get("priceUsd")),
        price_native=_optional_float(value.get("priceNative")),
        fdv_usd=_optional_float(value.get("fdvUsd")),
        market_cap_usd=_optional_float(value.get("marketCapUsd")),
        liquidity_base=_optional_float(value.get("liquidityBase")),
        liquidity_quote=_optional_float(value.get("liquidityQuote")),
        txns_24h=_optional_int(value.get("txns24h")),
        boosts_active=_optional_int(value.get("boostsActive")),
        pair_age_hours=_optional_float(value.get("pairAgeHours")),
        market_cap_to_liquidity=_optional_float(value.get("marketCapToLiquidity")),
        fdv_to_liquidity=_optional_float(value.get("fdvToLiquidity")),
        volume_24h_to_market_cap=_optional_float(value.get("volume24hToMarketCap")),
        volume_24h_to_liquidity=_optional_float(value.get("volume24hToLiquidity")),
        cmc_id=_optional_int(value.get("cmcId")),
        cmc_slug=_optional_string(value.get("cmcSlug")),
        cmc_rank=_optional_int(value.get("cmcRank")),
        circulating_supply=_optional_float(value.get("circulatingSupply")),
        total_supply=_optional_float(value.get("totalSupply")),
        cmc_percent_change_7d=_optional_float(value.get("cmcPercentChange7d")),
        cmc_volume_change_24h=_optional_float(value.get("cmcVolumeChange24h")),
        market_cap_dominance=_optional_float(value.get("marketCapDominance")),
    )


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _optional_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
