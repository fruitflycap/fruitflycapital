"""Small server-side GraphQL client for configured Uniswap subgraphs.

The client is deliberately schema-specific to the common Uniswap v3
subgraph shape, but the endpoint and pool IDs are configuration, not hidden
constants. API keys never leave this process.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen


class GraphQueryError(RuntimeError):
    pass


@dataclass(frozen=True)
class GraphClient:
    endpoint: str
    api_key: str | None = None
    timeout_seconds: float = 10.0

    @classmethod
    def from_env(cls) -> "GraphClient | None":
        endpoint = os.getenv("GRAPH_SUBGRAPH_URL", "").strip()
        api_key = os.getenv("GRAPH_API_KEY", "").strip() or None
        subgraph_id = os.getenv("GRAPH_UNISWAP_SUBGRAPH_ID", "").strip()
        if not endpoint and subgraph_id and api_key:
            endpoint = f"https://gateway.thegraph.com/api/{api_key}/subgraphs/id/{subgraph_id}"
        if not endpoint:
            return None
        return cls(endpoint=endpoint, api_key=api_key)

    def query(self, document: str, variables: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            self.endpoint,
            data=json.dumps({"query": document, "variables": variables}).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # urllib exposes several transport exceptions
            raise GraphQueryError(f"The Graph request failed: {exc}") from exc
        errors = payload.get("errors") if isinstance(payload, dict) else None
        if errors:
            raise GraphQueryError(f"The Graph returned errors: {errors}")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            raise GraphQueryError("The Graph response did not contain an object-shaped data field")
        return data

    def recent_swaps(self, pool_id: str, *, first: int = 1000, since_timestamp: int = 0) -> list[dict[str, Any]]:
        document = """
        query RecentSwaps($pool: ID!, $first: Int!, $since: BigInt!) {
          swaps(first: $first, orderBy: timestamp, orderDirection: desc,
                where: {pool: $pool, timestamp_gt: $since}) {
            id
            timestamp
            amount0
            amount1
            amountUSD
            pool { id }
            transaction { id }
          }
        }
        """
        return list(self.query(document, {"pool": pool_id.lower(), "first": first, "since": since_timestamp}).get("swaps", []))

    def pool_state(self, pool_id: str) -> dict[str, Any] | None:
        document = """
        query PoolState($pool: ID!) {
          pools(where: {id: $pool}, first: 1) {
            id
            token0 { id symbol decimals }
            token1 { id symbol decimals }
            totalValueLockedUSD
            volumeUSD
            txCount
            token0Price
            token1Price
          }
        }
        """
        pools = self.query(document, {"pool": pool_id.lower()}).get("pools", [])
        return pools[0] if pools else None

    def top_pools(self, *, first: int = 100) -> list[dict[str, Any]]:
        """Discover high-TVL pools for universe bootstrap when supported."""

        document = """
        query TopPools($first: Int!) {
          pools(first: $first, orderBy: totalValueLockedUSD, orderDirection: desc) {
            id
            token0 { id symbol decimals }
            token1 { id symbol decimals }
            totalValueLockedUSD
            volumeUSD
            txCount
            token0Price
            token1Price
          }
        }
        """
        return list(self.query(document, {"first": max(1, min(int(first), 1000))}).get("pools", []))
