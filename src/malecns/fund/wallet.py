"""Small Robinhood wallet boundary for balance reads and signed RPC calls.

The wallet is deliberately independent from the retained Fruit Fly Capital
vault contract.  It can read the configured wallet without a signer, while
the signing method is only used by the separately guarded execution adapter.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping


ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


class WalletRpcError(RuntimeError):
    """Raised when the configured RPC cannot answer a wallet request."""


def _int_hex(value: str | int) -> int:
    return int(value, 16) if isinstance(value, str) else int(value)


def _address(value: str) -> str:
    candidate = value.strip()
    if len(candidate) != 42 or not candidate.startswith("0x"):
        raise ValueError("wallet address must be a 20-byte 0x-prefixed address")
    int(candidate[2:], 16)
    return candidate


@dataclass(frozen=True)
class WalletSnapshot:
    chain_id: int
    wallet_address: str
    native_balance_wei: int
    native_symbol: str = "ETH"
    gas_reserve_wei: int = 2_000_000_000_000_000

    @property
    def native_balance_eth(self) -> Decimal:
        return Decimal(self.native_balance_wei) / Decimal(10**18)

    @property
    def available_native_wei(self) -> int:
        return max(0, self.native_balance_wei - self.gas_reserve_wei)

    @property
    def available_native_eth(self) -> Decimal:
        return Decimal(self.available_native_wei) / Decimal(10**18)

    def as_dict(self) -> dict[str, Any]:
        return {
            "chainId": self.chain_id,
            "address": self.wallet_address,
            "nativeSymbol": self.native_symbol,
            "nativeBalanceWei": str(self.native_balance_wei),
            "nativeBalance": float(self.native_balance_eth),
            "gasReserveWei": str(self.gas_reserve_wei),
            "gasReserve": float(Decimal(self.gas_reserve_wei) / Decimal(10**18)),
            "availableToTradeWei": str(self.available_native_wei),
            "availableToTrade": float(self.available_native_eth),
            "source": "rpc",
        }


class RpcWalletClient:
    """Dependency-light JSON-RPC client for the configured wallet."""

    def __init__(
        self,
        rpc_url: str,
        wallet_address: str,
        *,
        expected_chain_id: int | None = None,
        gas_reserve_wei: int = 2_000_000_000_000_000,
        timeout_seconds: float = 12.0,
    ) -> None:
        if not rpc_url.strip():
            raise ValueError("rpc_url is required")
        self.rpc_url = rpc_url.strip()
        self.wallet_address = _address(wallet_address)
        self.expected_chain_id = expected_chain_id
        self.gas_reserve_wei = max(0, int(gas_reserve_wei))
        self.timeout_seconds = timeout_seconds
        self._request_id = 0

    @classmethod
    def from_env(cls) -> "RpcWalletClient | None":
        rpc_url = os.getenv("FUND_RPC_URL", "").strip()
        wallet_address = os.getenv("FUND_WALLET_ADDRESS", "").strip()
        if not rpc_url or not wallet_address:
            return None
        return cls(
            rpc_url,
            wallet_address,
            expected_chain_id=int(os.getenv("FUND_CHAIN_ID", "4663")),
            gas_reserve_wei=int(os.getenv("FUND_GAS_RESERVE_WEI", "2000000000000000")),
        )

    def call(self, method: str, params: list[Any]) -> Any:
        self._request_id += 1
        request = urllib.request.Request(
            self.rpc_url,
            data=json.dumps({"jsonrpc": "2.0", "id": self._request_id, "method": method, "params": params}).encode("utf-8"),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise WalletRpcError(f"wallet RPC request failed: {exc}") from exc
        if not isinstance(payload, Mapping):
            raise WalletRpcError("wallet RPC returned a non-object response")
        if payload.get("error"):
            raise WalletRpcError(str(payload["error"]))
        return payload.get("result")

    def snapshot(self) -> WalletSnapshot:
        chain_id = _int_hex(self.call("eth_chainId", []))
        if self.expected_chain_id is not None and chain_id != self.expected_chain_id:
            raise WalletRpcError(f"configured chain {self.expected_chain_id} does not match RPC chain {chain_id}")
        balance = _int_hex(self.call("eth_getBalance", [self.wallet_address, "latest"]))
        return WalletSnapshot(chain_id, self.wallet_address, balance, gas_reserve_wei=self.gas_reserve_wei)

    def send_raw_transaction(self, raw_transaction: str) -> str:
        result = self.call("eth_sendRawTransaction", [raw_transaction])
        if not isinstance(result, str) or not result.startswith("0x"):
            raise WalletRpcError("wallet RPC did not return a transaction hash")
        return result

    def erc20_balance_raw(self, token_address: str) -> int:
        token = _address(token_address)
        owner = self.wallet_address[2:].lower().rjust(64, "0")
        result = self.call("eth_call", [{"to": token, "data": f"0x70a08231{owner}"}, "latest"])
        return _int_hex(result)

    def erc20_decimals(self, token_address: str) -> int:
        result = self.call("eth_call", [{"to": _address(token_address), "data": "0x313ce567"}, "latest"])
        return _int_hex(result)
