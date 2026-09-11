"""Small, server-side client for the public DexScreener API.

Only documented API endpoints are used here. The client intentionally has no
browser-facing fetch path and no API-key field: discovery runs in the Python
process, where timeouts, caching, and provider failures can be contained.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


class DexScreenerApiError(RuntimeError):
    """Raised when DexScreener cannot provide a valid API response."""


JsonFetcher = Callable[[str, float], Any]


@dataclass
class DexScreenerClient:
    """Dependency-light DexScreener client with an in-memory TTL cache."""

    base_url: str = "https://api.dexscreener.com"
    timeout_seconds: float = 10.0
    cache_ttl_seconds: float = 60.0
    fetcher: JsonFetcher | None = None
    _cache: dict[str, tuple[float, Any]] = field(default_factory=dict, init=False, repr=False)

    def get_json(self, path: str, *, force: bool = False) -> Any:
        normalized_path = "/" + path.lstrip("/")
        now = time.monotonic()
        cached = self._cache.get(normalized_path)
        if not force and cached is not None and now - cached[0] < self.cache_ttl_seconds:
            return cached[1]

        url = f"{self.base_url.rstrip('/')}{normalized_path}"
        try:
            payload = self.fetcher(url, self.timeout_seconds) if self.fetcher else self._request(url)
        except DexScreenerApiError:
            raise
        except Exception as exc:
            raise DexScreenerApiError(f"DexScreener request failed for {normalized_path}: {exc}") from exc
        if not isinstance(payload, (dict, list)):
            raise DexScreenerApiError(f"DexScreener returned a non-JSON-object response for {normalized_path}")
        self._cache[normalized_path] = (now, payload)
        return payload

    def latest_token_profiles(self, *, force: bool = False) -> list[dict[str, Any]]:
        return _object_list(self.get_json("/token-profiles/latest/v1", force=force))

    def recent_token_profiles(self, *, force: bool = False) -> list[dict[str, Any]]:
        return _object_list(self.get_json("/token-profiles/recent-updates/v1", force=force))

    def token_pairs(self, chain_id: str, token_address: str, *, force: bool = False) -> list[dict[str, Any]]:
        path = f"/token-pairs/v1/{_path_part(chain_id)}/{_path_part(token_address)}"
        return _pair_list(self.get_json(path, force=force))

    def pair(self, chain_id: str, pair_address: str, *, force: bool = False) -> list[dict[str, Any]]:
        path = f"/latest/dex/pairs/{_path_part(chain_id)}/{_path_part(pair_address)}"
        return _pair_list(self.get_json(path, force=force))

    def search(self, query: str, *, force: bool = False) -> list[dict[str, Any]]:
        normalized = str(query or "").strip()
        if not normalized:
            return []
        path = f"/latest/dex/search?q={quote(normalized, safe='')}"
        return _pair_list(self.get_json(path, force=force))

    def tokens(self, chain_id: str, token_addresses: list[str] | tuple[str, ...], *, force: bool = False) -> list[dict[str, Any]]:
        """Fetch pair data for token addresses in documented batches of 30."""

        normalized = _unique_nonempty(token_addresses)
        pairs: list[dict[str, Any]] = []
        for start in range(0, len(normalized), 30):
            batch = normalized[start : start + 30]
            joined = ",".join(_path_part(address) for address in batch)
            path = f"/tokens/v1/{_path_part(chain_id)}/{joined}"
            pairs.extend(_pair_list(self.get_json(path, force=force)))
        return pairs

    def _request(self, url: str) -> Any:
        request = Request(url, headers={"Accept": "application/json", "User-Agent": "fruit-fly-capital/0.1"}, method="GET")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            raise DexScreenerApiError(f"HTTP {exc.code} from DexScreener") from exc
        except Exception as exc:
            raise DexScreenerApiError(str(exc)) from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DexScreenerApiError("DexScreener returned malformed JSON") from exc


def _object_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("profiles", "tokens", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _pair_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict) and _looks_like_pair(item)]
    if isinstance(payload, dict):
        for key in ("pairs", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict) and _looks_like_pair(item)]
    return []


def _looks_like_pair(payload: dict[str, Any]) -> bool:
    return bool(payload.get("pairAddress") or payload.get("pair_address"))


def _unique_nonempty(values: list[str] | tuple[str, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        key = normalized.lower()
        if normalized and key not in seen:
            result.append(normalized)
            seen.add(key)
    return result


def _path_part(value: str) -> str:
    # DexScreener addresses and chain IDs are expected to be path-safe. Reject
    # separators rather than silently constructing a different endpoint.
    normalized = str(value or "").strip()
    if not normalized or "/" in normalized or "?" in normalized or "#" in normalized:
        raise ValueError(f"invalid DexScreener path component: {value!r}")
    return normalized
