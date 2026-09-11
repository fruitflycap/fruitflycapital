"""Market data providers. Providers return raw observations only."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .graph_client import GraphClient
from .models import RawSwapObservation, RawTokenObservation


@dataclass(frozen=True)
class GraphProvider:
    """Read raw Uniswap pool/swap entities from The Graph."""

    client: GraphClient
    lookback_seconds: int = 3600
    swap_limit: int = 1000

    def observe(self, config: dict[str, Any], *, now_s: int | None = None) -> RawTokenObservation:
        pool_id = str(config.get("poolId", "")).strip().lower()
        token_address = str(config.get("tokenAddress", "")).strip().lower()
        token_id = str(config.get("id", "")).strip()
        label = str(config.get("label", token_id)).strip()
        chain_id = str(config.get("chainId", "ethereum")).strip().lower() or "ethereum"
        dex_id = str(config.get("dexId", "uniswap")).strip().lower() or "uniswap"
        pair_address = str(config.get("pairAddress", pool_id)).strip().lower() or pool_id
        if not token_id or not pool_id or not token_address:
            raise ValueError("each Graph habitat requires id, poolId, and tokenAddress")

        observed_s = int(time.time()) if now_s is None else int(now_s)
        pool = self.client.pool_state(pool_id)
        if not pool:
            raise ValueError(f"Graph returned no pool state for {pool_id}")
        # Deep Graph observation supplies the swap/pool truth, while the
        # discovery provider supplies optional market context that Graph does
        # not expose on a pool entity (market cap, FDV, USD price, pair age).
        # Keep the namespaces explicit; this is enrichment, not a replacement
        # for Graph's liquidity or swap measurements.
        pool = dict(pool)
        for key in (
            "priceUsd", "priceNative", "marketCapUsd", "fdvUsd",
            "pairCreatedAt", "liquidityBase", "liquidityQuote",
            "volume24hUsd", "cmcId", "cmcSlug", "cmcRank",
            "circulatingSupply", "totalSupply", "cmcPercentChange7d",
            "cmcVolumeChange24h", "marketCapDominance",
            "dexscreenerUrl",
        ):
            if key in config and config[key] is not None and key not in pool:
                pool[key] = config[key]
        token0 = _address(pool.get("token0"))
        token1 = _address(pool.get("token1"))
        if token_address not in {token0, token1}:
            raise ValueError(f"tokenAddress {token_address} is not token0/token1 of pool {pool_id}")

        payloads = self.client.recent_swaps(
            pool_id,
            first=self.swap_limit,
            since_timestamp=observed_s - self.lookback_seconds,
        )
        swaps = tuple(
            RawSwapObservation(
                swap_id=str(payload.get("id", "")),
                timestamp_s=_integer(payload.get("timestamp")),
                amount0=_number(payload.get("amount0")),
                amount1=_number(payload.get("amount1")),
                amount_usd=abs(_number(payload.get("amountUSD"))),
                token0_address=token0,
                token1_address=token1,
                transaction_id=_transaction_id(payload),
                raw=dict(payload),
            )
            for payload in payloads
            if isinstance(payload, dict)
        )
        return RawTokenObservation(
            provider="the-graph",
            token_id=token_id,
            token_address=token_address,
            pool_id=pool_id,
            label=label,
            observed_at_ms=observed_s * 1000,
            pool=dict(pool),
            swaps=swaps,
            chain_id=chain_id,
            dex_id=dex_id,
            pair_address=pair_address,
        )


def _address(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("id", "")).strip().lower()
    return str(value or "").strip().lower()


def _transaction_id(payload: dict[str, Any]) -> str | None:
    transaction = payload.get("transaction")
    if isinstance(transaction, dict) and transaction.get("id") is not None:
        return str(transaction["id"])
    return None


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
