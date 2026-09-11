"""Print one configured The Graph -> habitat snapshot."""

from __future__ import annotations

import json

from .config import load_project_env
from .market.signal_engine import MarketSignalEngine


def main() -> None:
    load_project_env()
    engine = MarketSignalEngine.from_env()
    if engine is None:
        print(json.dumps({"source": "graph-uniswap", "status": "disabled", "reason": "configure Graph credentials plus NEUROSWARM_MARKET_HABITATS, or enable DexScreener discovery"}, indent=2))
        return
    print(json.dumps(engine.snapshot_if_due(force=True), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
