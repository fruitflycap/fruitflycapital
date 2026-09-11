"""Server-side Uniswap Trading API client used by the fund executor.

When ``UNISWAP_API_KEY`` is configured, the executor uses this client for
Uniswap Protocol V2/V3/V4 and multihop route discovery. The direct JSON-RPC
V2/V3 client remains available as the no-key fallback.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class UniswapApiError(RuntimeError):
    pass


@dataclass(frozen=True)
class TradeIntent:
    habitat_id: str
    side: str
    token_in: str
    token_out: str
    amount: str
    chain_id: int
    rationale: str
    status: str = "proposal_only"
    requires_human_signature: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "habitatId": self.habitat_id,
            "side": self.side,
            "tokenIn": self.token_in,
            "tokenOut": self.token_out,
            "amount": self.amount,
            "chainId": self.chain_id,
            "rationale": self.rationale,
            "status": self.status,
            "requiresHumanSignature": self.requires_human_signature,
        }


@dataclass(frozen=True)
class HostedRouteQuote:
    """A routing-aware quote returned by the hosted Uniswap API."""

    response: dict[str, Any]
    token_in: str
    token_out: str
    amount_in: int
    amount_out: int

    @property
    def routing(self) -> str:
        return str(self.response.get("routing") or "CLASSIC")

    def as_dict(self) -> dict[str, Any]:
        quote = self.response.get("quote")
        return {
            "source": "uniswap-trading-api",
            "route": self.routing,
            "tokenIn": self.token_in,
            "tokenOut": self.token_out,
            "amountIn": str(self.amount_in),
            "amountOut": str(self.amount_out),
            "quote": quote,
            "requestId": self.response.get("requestId"),
        }


@dataclass(frozen=True)
class UniswapTradingClient:
    api_key: str
    base_url: str = "https://trade-api.gateway.uniswap.org/v1"
    timeout_seconds: float = 15.0
    permit2_disabled: bool = True

    @classmethod
    def from_env(cls) -> "UniswapTradingClient | None":
        api_key = os.getenv("UNISWAP_API_KEY", "").strip()
        if not api_key:
            return None
        return cls(
            api_key=api_key,
            base_url=os.getenv("UNISWAP_API_BASE_URL", "https://trade-api.gateway.uniswap.org/v1").strip(),
            timeout_seconds=max(2.0, float(os.getenv("UNISWAP_API_TIMEOUT_SECONDS", "15"))),
            permit2_disabled=os.getenv("UNISWAP_PERMIT2_DISABLED", "true").strip().lower() == "true",
        )

    def quote(self, request_body: dict[str, Any]) -> dict[str, Any]:
        return self._post("/quote", request_body)

    def check_approval(self, request_body: dict[str, Any]) -> dict[str, Any]:
        return self._post("/check_approval", request_body)

    def quote_exact_input(
        self,
        *,
        swapper: str,
        token_in: str,
        token_out: str,
        chain_id: int,
        amount_in: int,
        slippage_tolerance: float,
    ) -> HostedRouteQuote:
        _validate_address(swapper, "swapper")
        _validate_address(token_in, "tokenIn")
        _validate_address(token_out, "tokenOut")
        if amount_in <= 0:
            raise UniswapApiError("swap amount must be greater than zero")
        response = self.quote({
            "swapper": swapper,
            "tokenIn": token_in,
            "tokenOut": token_out,
            "tokenInChainId": str(chain_id),
            "tokenOutChainId": str(chain_id),
            "amount": str(amount_in),
            "type": "EXACT_INPUT",
            "slippageTolerance": min(5.0, max(0.0, float(slippage_tolerance))),
            "routingPreference": "BEST_PRICE",
            # Keep the route on Uniswap Protocol AMMs. This includes V2, V3,
            # and V4 while avoiding UniswapX's off-chain order-signing flow.
            "protocols": ["V2", "V3", "V4"],
        })
        quote = response.get("quote")
        if not isinstance(quote, dict):
            raise UniswapApiError("Uniswap API quote response did not contain quote data")
        output = quote.get("output")
        if isinstance(output, dict) and output.get("amount") is not None:
            amount_out = _int_value(output["amount"])
        else:
            order_info = quote.get("orderInfo")
            outputs = order_info.get("outputs") if isinstance(order_info, dict) else None
            first = outputs[0] if isinstance(outputs, list) and outputs else None
            if not isinstance(first, dict) or first.get("startAmount") is None:
                raise UniswapApiError("Uniswap API quote response did not contain an output amount")
            amount_out = _int_value(first["startAmount"])
        if amount_out <= 0:
            raise UniswapApiError("Uniswap API returned a zero output amount")
        return HostedRouteQuote(response, token_in, token_out, amount_in, amount_out)

    def check_approval_for_swap(self, *, wallet_address: str, token: str, amount: int, chain_id: int) -> dict[str, Any]:
        _validate_address(wallet_address, "walletAddress")
        _validate_address(token, "token")
        response = self.check_approval({
            "walletAddress": wallet_address,
            "token": token,
            "amount": str(amount),
            "chainId": chain_id,
        })
        if response.get("approval") is not None and not isinstance(response.get("approval"), dict):
            raise UniswapApiError("Uniswap API returned an invalid approval transaction")
        if response.get("cancel") is not None and not isinstance(response.get("cancel"), dict):
            raise UniswapApiError("Uniswap API returned an invalid approval cancellation transaction")
        return response

    def create_swap_transaction(self, quote: HostedRouteQuote) -> dict[str, Any]:
        response = dict(quote.response)
        # The API consumes the quote response at the top level. With the
        # backend proxy-approval flow permitData is null and must be omitted.
        response.pop("permitData", None)
        response.pop("permitTransaction", None)
        response = {key: value for key, value in response.items() if value is not None}
        swap_response = self.create_unsigned_swap(response)
        swap = swap_response.get("swap")
        if not isinstance(swap, dict):
            raise UniswapApiError("Uniswap API swap response did not contain transaction data")
        return swap

    def create_unsigned_swap(self, quote: dict[str, Any], *, permit_data: dict[str, Any] | None = None, deadline: int | None = None) -> dict[str, Any]:
        # Trading API /swap consumes the quote response fields at the top
        # level; wrapping them under {"quote": ...} is not the documented
        # request shape.
        body: dict[str, Any] = dict(quote)
        if permit_data is not None:
            body["permitData"] = permit_data
        if deadline is not None:
            body["deadline"] = deadline
        return self._post("/swap", body)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        decision_origin = os.getenv("UNISWAP_DECISION_ORIGIN", "human_mediated").strip().lower()
        if decision_origin not in {"human_mediated", "autonomous"}:
            raise ValueError("UNISWAP_DECISION_ORIGIN must be human_mediated or autonomous")
        url = f"{self.base_url.rstrip('/')}{path}"
        headers = {
            "x-api-key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
            # Cloudflare rejects Python's default urllib signature on this
            # endpoint. curl is available in the local and Render images and
            # uses the same transport that succeeds from the terminal.
            "User-Agent": "Mozilla/5.0",
            # Robinhood Chain mainnet is supported by Universal Router 2.1.1.
            "x-universal-router-version": os.getenv("UNISWAP_ROUTER_VERSION", "2.1.1"),
            "x-agent-info": json.dumps({
                "integration_name": "swap-integration",
                "decision_origin": decision_origin,
                "version": "1.5.0",
            }, separators=(",", ":")),
            "x-permit2-disabled": "true" if self.permit2_disabled else "false",
        }
        if shutil.which("curl"):
            try:
                command = ["curl", "--silent", "--show-error", "--max-time", str(max(2, int(self.timeout_seconds))), "--request", "POST", url]
                for name, value in headers.items():
                    command.extend(["--header", f"{name}: {value}"])
                command.extend(["--data", json.dumps(body), "--write-out", "\n__FFC_HTTP_STATUS__:%{http_code}"])
                result = subprocess.run(command, capture_output=True, text=True, check=False)
                if result.returncode != 0:
                    raise UniswapApiError(f"Uniswap API request failed: curl exited {result.returncode}: {result.stderr[:300]}")
                raw, marker, status_text = result.stdout.rpartition("\n__FFC_HTTP_STATUS__:")
                if not marker:
                    raise UniswapApiError("Uniswap API request failed: curl returned no HTTP status")
                status = int(status_text.strip() or "0")
                if status >= 400:
                    raise UniswapApiError(f"Uniswap API request failed: HTTP {status}: {raw[:500]}")
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise UniswapApiError("Uniswap API returned a non-object response")
                return payload
            except UniswapApiError:
                raise
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise UniswapApiError(f"Uniswap API request failed: {exc}") from exc
        request = Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise UniswapApiError(f"Uniswap API request failed: HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            raise UniswapApiError(f"Uniswap API request failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise UniswapApiError("Uniswap API returned a non-object response")
        return payload


def _validate_address(value: str, field: str) -> None:
    if not re.fullmatch(r"0x[a-fA-F0-9]{40}", str(value or "")):
        raise UniswapApiError(f"{field} must be a 20-byte 0x-prefixed address")


def _int_value(value: Any) -> int:
    if isinstance(value, int):
        return value
    text = str(value or "0")
    return int(text, 16) if text.startswith("0x") else int(text)
