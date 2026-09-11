"""Direct on-chain Uniswap route discovery and transaction preparation.

This module deliberately does not call the hosted Uniswap Trading API.  It
uses JSON-RPC ``eth_call`` for pool discovery/quoting and builds calldata for
the chain's deployed SwapRouter02 or V2 Router02.  It never signs or sends a
transaction.

The implementation is intentionally dependency-light so the executor can
prepare a transaction in the project's existing environment.  A separate
signer remains responsible for the final broadcast boundary.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..fund.wallet import RpcWalletClient


ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


# Function selectors from the deployed Uniswap V2/V3 interfaces.
SEL_ALLOWANCE = "dd62ed3e"
SEL_APPROVE = "095ea7b3"
SEL_V3_GET_POOL = "1698ee82"
SEL_V3_QUOTE_EXACT_INPUT = "cdca1753"
SEL_V3_EXACT_INPUT_SINGLE = "04e45aaf"
SEL_V2_GET_PAIR = "e6a43905"
SEL_V2_GET_AMOUNTS_OUT = "d06ca61f"
SEL_V2_SWAP_EXACT_ETH_FOR_TOKENS = "7ff36ab5"
SEL_V2_SWAP_EXACT_TOKENS_FOR_ETH = "18cbafe5"
SEL_MULTICALL = "5ae401dc"
SEL_UNWRAP_WETH9 = "49404b7c"

ROBINHOOD_V3_FACTORY = "0x1f7d7550b1b028f7571e69a784071f0205fd2efa"
ROBINHOOD_V3_QUOTER = "0x33e885ed0ec9bf04ecfb19341582aadcb4c8a9e7"
ROBINHOOD_V3_ROUTER = "0xcaf681a66d020601342297493863e78c959e5cb2"
ROBINHOOD_V2_FACTORY = "0x8bceaa40b9acdfaedf85adf4ff01f5ad6517937f"
ROBINHOOD_V2_ROUTER = "0x89e5db8b5aa49aa85ac63f691524311aeb649eba"
ROBINHOOD_WETH = "0x0Bd7D308f8E1639FAb988df18A8011f41EAcAD73"


class DirectUniswapError(RuntimeError):
    """Raised when no safe direct on-chain route can be prepared."""


@dataclass(frozen=True)
class DirectRouteQuote:
    kind: str
    token_in: str
    token_out: str
    amount_in: int
    amount_out: int
    fee: int | None = None
    pool: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "source": "onchain-rpc",
            "route": self.kind,
            "tokenIn": self.token_in,
            "tokenOut": self.token_out,
            "amountIn": str(self.amount_in),
            "amountOut": str(self.amount_out),
            "fee": self.fee,
            "pool": self.pool,
        }


@dataclass(frozen=True)
class DirectUniswapClient:
    wallet: RpcWalletClient
    weth_address: str
    v3_factory: str
    v3_quoter: str
    v3_router: str
    v2_factory: str
    v2_router: str
    fee_tiers: tuple[int, ...] = (100, 500, 3000, 10000)
    deadline_seconds: int = 300

    @classmethod
    def from_env(cls, wallet: RpcWalletClient) -> "DirectUniswapClient":
        chain_id = wallet.expected_chain_id or int(os.getenv("FUND_CHAIN_ID", "4663"))
        required_overrides = ("UNISWAP_V3_FACTORY", "UNISWAP_V3_QUOTER", "UNISWAP_V3_ROUTER", "UNISWAP_V2_FACTORY", "UNISWAP_V2_ROUTER", "FUND_WETH_ADDRESS")
        if chain_id != 4663 and any(not os.getenv(name, "").strip() for name in required_overrides):
            raise DirectUniswapError(
                f"direct Uniswap route addresses are not configured for chain {chain_id}; set {', '.join(required_overrides)}"
            )
        return cls(
            wallet=wallet,
            weth_address=_address(os.getenv("FUND_WETH_ADDRESS", ROBINHOOD_WETH), "FUND_WETH_ADDRESS"),
            v3_factory=_address(os.getenv("UNISWAP_V3_FACTORY", ROBINHOOD_V3_FACTORY), "UNISWAP_V3_FACTORY"),
            v3_quoter=_address(os.getenv("UNISWAP_V3_QUOTER", ROBINHOOD_V3_QUOTER), "UNISWAP_V3_QUOTER"),
            v3_router=_address(os.getenv("UNISWAP_V3_ROUTER", os.getenv("UNISWAP_ROUTER_ADDRESS", ROBINHOOD_V3_ROUTER)), "UNISWAP_V3_ROUTER"),
            v2_factory=_address(os.getenv("UNISWAP_V2_FACTORY", ROBINHOOD_V2_FACTORY), "UNISWAP_V2_FACTORY"),
            v2_router=_address(os.getenv("UNISWAP_V2_ROUTER", ROBINHOOD_V2_ROUTER), "UNISWAP_V2_ROUTER"),
            fee_tiers=_fee_tiers(os.getenv("UNISWAP_V3_FEE_TIERS", "100,500,3000,10000")),
            deadline_seconds=max(60, int(os.getenv("UNISWAP_SWAP_DEADLINE_SECONDS", "300"))),
        )

    @property
    def routers(self) -> tuple[str, str]:
        return self.v3_router, self.v2_router

    def quote(self, *, token_in: str, token_out: str, amount_in: int) -> DirectRouteQuote:
        if amount_in <= 0:
            raise DirectUniswapError("swap input amount must be greater than zero")
        token_in = _address(token_in, "tokenIn")
        token_out = _address(token_out, "tokenOut")
        if token_in.lower() == token_out.lower():
            raise DirectUniswapError("swap input and output token must differ")
        wrapped_in = self.weth_address if token_in.lower() == ZERO_ADDRESS.lower() else token_in
        wrapped_out = self.weth_address if token_out.lower() == ZERO_ADDRESS.lower() else token_out

        # Prefer V3, because that is where the current Robinhood token market
        # feed most often points.  A V3 pool is only accepted if its quoter
        # returns a positive amount; an empty/unusable pool is skipped.
        for fee in self.fee_tiers:
            try:
                pool = _address_from_word(self._call(self.v3_factory, "0x" + SEL_V3_GET_POOL + _word(wrapped_in) + _word(wrapped_out) + _word(fee)))
                if pool == ZERO_ADDRESS:
                    continue
                path = _address_bytes(wrapped_in) + fee.to_bytes(3, "big") + _address_bytes(wrapped_out)
                output = _first_word(self._call(self.v3_quoter, "0x" + SEL_V3_QUOTE_EXACT_INPUT + _encode_bytes_uint(path, amount_in)))
                if output > 0:
                    return DirectRouteQuote("v3", token_in, token_out, amount_in, output, fee, pool)
            except Exception:
                continue

        # Keep a direct V2 fallback for any pair that is actually deployed;
        # this is still entirely on-chain and does not treat a symbol as a
        # route.  No pair means no quote and therefore no transaction.
        try:
            pair = _address_from_word(self._call(self.v2_factory, "0x" + SEL_V2_GET_PAIR + _word(wrapped_in) + _word(wrapped_out)))
            if pair != ZERO_ADDRESS:
                output = _last_word(self._call(self.v2_router, "0x" + SEL_V2_GET_AMOUNTS_OUT + _encode_address_array_uint((wrapped_in, wrapped_out), amount_in)))
                if output > 0:
                    return DirectRouteQuote("v2", token_in, token_out, amount_in, output, pool=pair)
        except Exception:
            pass
        raise DirectUniswapError(
            f"no direct on-chain Uniswap V2/V3 route with liquidity for {token_in} -> {token_out}; V4 route metadata is not configured"
        )

    def router_for(self, kind: str) -> str:
        if kind == "v3":
            return self.v3_router
        if kind == "v2":
            return self.v2_router
        raise DirectUniswapError(f"unsupported direct route kind: {kind}")

    def allowance(self, token: str, owner: str, *, route_kind: str = "v3") -> int:
        router = self.router_for(route_kind)
        return _first_word(self._call(_address(token, "token"), "0x" + SEL_ALLOWANCE + _word(owner) + _word(router)))

    def approval_transaction(self, token: str, amount: int, *, route_kind: str = "v3") -> dict[str, Any]:
        token = _address(token, "token")
        return {"to": token, "data": "0x" + SEL_APPROVE + _word(self.router_for(route_kind)) + _word(amount), "value": 0}

    def build_swap(self, route: DirectRouteQuote, *, recipient: str, slippage_tolerance: float) -> dict[str, Any]:
        recipient = _address(recipient, "recipient")
        minimum = max(0, int(route.amount_out * (1.0 - min(5.0, max(0.0, slippage_tolerance)) / 100.0)))
        deadline = int(time.time()) + self.deadline_seconds
        wrapped_in = self.weth_address if route.token_in.lower() == ZERO_ADDRESS.lower() else route.token_in
        wrapped_out = self.weth_address if route.token_out.lower() == ZERO_ADDRESS.lower() else route.token_out
        if route.kind == "v3":
            single = "0x" + SEL_V3_EXACT_INPUT_SINGLE + _word(wrapped_in) + _word(wrapped_out) + _word(route.fee or 0) + _word(recipient if route.token_out.lower() != ZERO_ADDRESS.lower() else self.v3_router) + _word(route.amount_in) + _word(minimum) + _word(0)
            if route.token_out.lower() == ZERO_ADDRESS.lower():
                unwrap = "0x" + SEL_UNWRAP_WETH9 + _word(minimum) + _word(recipient)
                data = "0x" + SEL_MULTICALL + _word(deadline) + _word(64) + _encode_bytes_array_body((bytes.fromhex(single[2:]), bytes.fromhex(unwrap[2:])))
                return {"to": self.v3_router, "data": data, "value": 0}
            return {"to": self.v3_router, "data": single, "value": route.amount_in if route.token_in.lower() == ZERO_ADDRESS.lower() else 0}
        if route.kind == "v2":
            path = (wrapped_in, wrapped_out)
            if route.token_in.lower() == ZERO_ADDRESS.lower():
                data = "0x" + SEL_V2_SWAP_EXACT_ETH_FOR_TOKENS + _word(minimum) + _encode_address_array_tail(path, 4) + _word(recipient) + _word(deadline)
                return {"to": self.v2_router, "data": data, "value": route.amount_in}
            data = "0x" + SEL_V2_SWAP_EXACT_TOKENS_FOR_ETH + _word(route.amount_in) + _word(minimum) + _encode_address_array_tail(path, 5) + _word(recipient) + _word(deadline)
            return {"to": self.v2_router, "data": data, "value": 0}
        raise DirectUniswapError(f"unsupported direct route kind: {route.kind}")

    def _call(self, to: str, data: str) -> Any:
        return self.wallet.call("eth_call", [{"to": to, "data": data}, "latest"])


def _address(value: str, field: str) -> str:
    text = str(value or "").strip()
    if len(text) != 42 or not text.startswith("0x"):
        raise ValueError(f"{field} must be a 20-byte 0x-prefixed address")
    int(text[2:], 16)
    return text


def _fee_tiers(value: str) -> tuple[int, ...]:
    tiers: list[int] = []
    for item in value.split(","):
        fee = int(item.strip())
        if 0 <= fee <= 1_000_000 and fee not in tiers:
            tiers.append(fee)
    if not tiers:
        raise ValueError("UNISWAP_V3_FEE_TIERS must contain at least one fee tier")
    return tuple(tiers)


def _address_bytes(address: str) -> bytes:
    return bytes.fromhex(_address(address, "address")[2:])


def _word(value: str | int) -> str:
    if isinstance(value, str):
        if value.startswith("0x") and len(value) == 42:
            raw = value[2:].lower()
            return raw.rjust(64, "0")
        value = int(value, 16) if value.startswith("0x") else int(value)
    if value < 0:
        raise ValueError("ABI uint values cannot be negative")
    return f"{value:064x}"


def _first_word(result: Any) -> int:
    text = str(result or "0x")
    if not text.startswith("0x") or len(text) < 66:
        raise DirectUniswapError("RPC contract call returned no uint256 result")
    return int(text[2:66], 16)


def _last_word(result: Any) -> int:
    text = str(result or "0x")
    if not text.startswith("0x") or len(text) < 66:
        raise DirectUniswapError("RPC contract call returned no array result")
    return int(text[-64:], 16)


def _address_from_word(result: Any) -> str:
    value = _first_word(result)
    return "0x" + f"{value:064x}"[-40:]


def _encode_bytes_uint(value: bytes, amount: int) -> str:
    padded = value + (b"\x00" * ((32 - len(value) % 32) % 32))
    return _word(64) + _word(amount) + _word(len(value)) + padded.hex()


def _encode_address_array_uint(addresses: tuple[str, ...], amount: int) -> str:
    return _word(amount) + _word(64) + _word(len(addresses)) + "".join(_word(address) for address in addresses)


def _encode_address_array_tail(addresses: tuple[str, ...], head_words: int) -> str:
    return _word(head_words * 32) + _word(len(addresses)) + "".join(_word(address) for address in addresses)


def _encode_bytes_array_body(values: tuple[bytes, ...]) -> str:
    body = [_word(len(values))]
    offset = 32 * len(values)
    encoded_values: list[str] = []
    for value in values:
        padded = value + (b"\x00" * ((32 - len(value) % 32) % 32))
        encoded = _word(len(value)) + padded.hex()
        body.append(_word(offset))
        encoded_values.append(encoded)
        offset += len(encoded) // 2
    return _word(32) + "".join(body) + "".join(encoded_values)
