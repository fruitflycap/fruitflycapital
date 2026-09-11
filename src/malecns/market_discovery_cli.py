"""Discover and print the currently eligible DexScreener market round."""

from __future__ import annotations

import json

from .config import load_project_env
from .market.graph_client import GraphClient
from .market.universe import DexScreenerMarketDiscovery


def main() -> None:
    load_project_env()
    discovery = DexScreenerMarketDiscovery.from_env(graph_client=GraphClient.from_env())
    if discovery is None:
        print(
            json.dumps(
                {
                    "source": "dexscreener",
                    "status": "disabled",
                    "reason": "set NEUROSWARM_MARKET_DISCOVERY_ENABLED=true",
                },
                indent=2,
            )
        )
        return
    try:
        payload = discovery.as_dict()
        payload["status"] = "ok" if payload.get("round", {}).get("markets") else "empty"
    except Exception as exc:
        payload = {"source": "dexscreener", "status": "error", "error": str(exc)}
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
