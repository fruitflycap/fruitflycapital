"""Small server-side CoinMarketCap listings client.

CoinMarketCap is used as a broad ranked-asset and metadata provider. It is not
treated as proof that an asset has a tradable pool on a configured chain; the
market universe still resolves contract addresses through DexScreener.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from urllib.parse import urlencode


class CoinMarketCapApiError(RuntimeError):
    """Raised when CoinMarketCap cannot return a valid listings response."""


JsonFetcher = Callable[[str, float, dict[str, str]], Any]


@dataclass
class CoinMarketCapClient:
    """Fetch and cache the classic ranked listings table on the server."""

    api_key: str
    base_url: str = "https://pro-api.coinmarketcap.com"
    timeout_seconds: float = 10.0
    cache_ttl_seconds: float = 300.0
    fetcher: JsonFetcher | None = None
    _cache: dict[str, tuple[float, list[dict[str, Any]]]] = field(default_factory=dict, init=False, repr=False)

    @classmethod
    def from_env(cls) -> "CoinMarketCapClient | None":
        api_key = os.getenv("CMC_API_KEY", "").strip()
        if not api_key:
            return None
        return cls(
            api_key=api_key,
            base_url=os.getenv("CMC_API_BASE_URL", "https://pro-api.coinmarketcap.com").strip().rstrip("/"),
            timeout_seconds=float(os.getenv("CMC_TIMEOUT_SECONDS", "10")),
            cache_ttl_seconds=float(os.getenv("CMC_CACHE_TTL_SECONDS", "300")),
        )

    def latest_listings(self, *, limit: int = 100, start: int = 1, convert: str = "USD", force: bool = False) -> list[dict[str, Any]]:
        query = urlencode({"start": max(1, int(start)), "limit": max(1, min(int(limit), 5000)), "convert": convert})
        path = f"/v3/cryptocurrency/listings/latest?{query}"
        now = time.monotonic()
        cached = self._cache.get(path)
        if not force and cached is not None and now - cached[0] < self.cache_ttl_seconds:
            return cached[1]
        url = f"{self.base_url}{path}"
        headers = {
            "Accept": "application/json",
            "X-CMC_PRO_API_KEY": self.api_key,
            "User-Agent": "fruit-fly-capital/0.1",
        }
        try:
            payload = self.fetcher(url, self.timeout_seconds, headers) if self.fetcher else self._request(url, headers)
        except CoinMarketCapApiError:
            raise
        except Exception as exc:
            raise CoinMarketCapApiError(f"CoinMarketCap request failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise CoinMarketCapApiError("CoinMarketCap returned a non-object response")
        rows = payload.get("data")
        if not isinstance(rows, list):
            raise CoinMarketCapApiError("CoinMarketCap response did not contain a listings data array")
        result = [row for row in rows if isinstance(row, dict)]
        self._cache[path] = (now, result)
        return result

    def _request(self, url: str, headers: dict[str, str]) -> Any:
        request = Request(url, headers=headers, method="GET")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise CoinMarketCapApiError(f"HTTP {exc.code} from CoinMarketCap") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CoinMarketCapApiError("CoinMarketCap returned malformed JSON") from exc
        except Exception as exc:
            raise CoinMarketCapApiError(str(exc)) from exc
