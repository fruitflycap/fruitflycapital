"""Provider-neutral asset valuation with a documented CoinMarketCap adapter."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlencode
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class PriceQuote:
    chain_id: int
    token_address: str
    price_usd: float
    observed_at_ms: int
    source: str
    provenance: Mapping[str, Any]


class ValuationProvider(Protocol):
    def get_price(self, chain_id: int, token_address: str) -> PriceQuote | None: ...
    def get_prices(self, assets: Sequence[tuple[int, str]]) -> Mapping[tuple[int, str], PriceQuote]: ...


class FakeValuationProvider:
    def __init__(self, prices: Mapping[tuple[int, str], float] | None = None) -> None:
        self.prices = dict(prices or {})

    def get_price(self, chain_id: int, token_address: str) -> PriceQuote | None:
        value = self.prices.get((chain_id, token_address))
        if value is None: return None
        return PriceQuote(chain_id, token_address, float(value), 0, "fake", {})

    def get_prices(self, assets: Sequence[tuple[int, str]]) -> Mapping[tuple[int, str], PriceQuote]:
        return {asset: quote for asset in assets if (quote := self.get_price(*asset)) is not None}


class CMCValuationProvider:
    """CMC quotes by symbol or CoinMarketCap ID; token address mapping is caller-owned.

    CMC's REST API is a market quote source, not proof of a chain balance. The
    returned provenance is retained for the portfolio audit trail.
    """
    endpoint = "https://pro-api.coinmarketcap.com/v3/cryptocurrency/quotes/latest"

    def __init__(self, api_key: str | None = None, *, symbols_by_asset: Mapping[tuple[int, str], str] | None = None, timeout_s: float = 8.0) -> None:
        self.api_key = api_key or os.getenv("CMC_API_KEY")
        self.symbols_by_asset = dict(symbols_by_asset or {})
        self.timeout_s = timeout_s

    def get_price(self, chain_id: int, token_address: str) -> PriceQuote | None:
        return self.get_prices([(chain_id, token_address)]).get((chain_id, token_address))

    def get_prices(self, assets: Sequence[tuple[int, str]]) -> Mapping[tuple[int, str], PriceQuote]:
        if not self.api_key or not assets: return {}
        symbols = sorted({self.symbols_by_asset.get(asset, "") for asset in assets} - {""})
        if not symbols: return {}
        query = urlencode({"symbol": ",".join(symbols), "convert": "USD", "skip_invalid": "true"})
        request = Request(f"{self.endpoint}?{query}", headers={"X-CMC_PRO_API_KEY": self.api_key, "Accept": "application/json"})
        with urlopen(request, timeout=self.timeout_s) as response:
            payload = json.load(response)
        quotes: dict[str, Any] = payload.get("data", {})
        result: dict[tuple[int, str], PriceQuote] = {}
        for asset in assets:
            symbol = self.symbols_by_asset.get(asset)
            entry = quotes.get(symbol) if symbol else None
            if isinstance(entry, list): entry = entry[0] if entry else None
            if not isinstance(entry, Mapping): continue
            quote = entry.get("quote", {}).get("USD", {})
            if isinstance(quote, Mapping) and isinstance(quote.get("price"), (int, float)):
                result[asset] = PriceQuote(asset[0], asset[1], float(quote["price"]), 0, "coinmarketcap", {"symbol": symbol, "endpoint": self.endpoint})
        return result

