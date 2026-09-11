"""Minimal server-side Privy REST client.

Endpoints and payloads follow Privy's current REST documentation. Secrets are
read only from the process environment and are never serialised into browser
messages or logs. Creating a wallet is opt-in in the bootstrap CLI.
"""
from __future__ import annotations
import base64, json, os
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.request import Request, urlopen

@dataclass(frozen=True)
class PrivyConfig:
    app_id: str | None = None; app_secret: str | None = None; wallet_id: str | None = None; wallet_address: str | None = None; policy_id: str | None = None
    @classmethod
    def from_env(cls) -> "PrivyConfig":
        return cls(*(os.getenv(name) or None for name in ("PRIVY_APP_ID", "PRIVY_APP_SECRET", "PRIVY_WALLET_ID", "PRIVY_WALLET_ADDRESS", "PRIVY_POLICY_ID")))
    @property
    def configured(self) -> bool: return bool(self.app_id and self.app_secret)

class PrivyClient:
    base_url = "https://api.privy.io"
    def __init__(self, config: PrivyConfig | None = None, *, timeout_s: float = 10.0) -> None: self.config, self.timeout_s = config or PrivyConfig.from_env(), timeout_s
    def _request(self, method: str, path: str, payload: Mapping[str, Any] | None = None, query: str = "") -> Any:
        if not self.config.configured: raise RuntimeError("PRIVY_APP_ID and PRIVY_APP_SECRET are required")
        token = base64.b64encode(f"{self.config.app_id}:{self.config.app_secret}".encode()).decode()
        headers = {"Authorization": f"Basic {token}", "privy-app-id": self.config.app_id or "", "Content-Type": "application/json"}
        request = Request(f"{self.base_url}{path}{query}", method=method, headers=headers, data=json.dumps(payload).encode() if payload is not None else None)
        with urlopen(request, timeout=self.timeout_s) as response: return json.load(response)
    def list_wallets(self) -> Any: return self._request("GET", "/v1/wallets")
    def get_wallet(self, wallet_id: str | None = None) -> Any: return self._request("GET", f"/v1/wallets/{wallet_id or self.config.wallet_id}")
    def create_wallet(self, *, display_name: str = "Fruit Fly Capital Treasury", external_id: str = "fruit-fly-capital-treasury", policy_id: str | None = None) -> Any:
        return self._request("POST", "/v1/wallets", {"chain_type": "ethereum", "display_name": display_name, "external_id": external_id, **({"policy_ids": [policy_id]} if policy_id else {})})
    def get_balance(self, wallet_id: str | None = None, *, chain: str = "base_sepolia", asset: str = "usdc") -> Any:
        return self._request("GET", f"/v1/wallets/{wallet_id or self.config.wallet_id}/balance", query=f"?chain={chain}&asset={asset}")
    def send_transaction(self, wallet_id: str, transaction: Mapping[str, Any], *, caip2: str, confirmed: bool = False) -> Any:
        if not confirmed: raise PermissionError("Privy transaction requires explicit confirmation")
        return self._request("POST", f"/v1/wallets/{wallet_id}/rpc", {"method": "eth_sendTransaction", "caip2": caip2, "chain_type": "ethereum", "params": {"transaction": dict(transaction)}})

class FakePrivyClient:
    """Deterministic test double; it never contacts Privy or signs anything."""
    def __init__(self, wallet: Mapping[str, Any] | None = None) -> None: self.wallet = dict(wallet or {"id": "fake-wallet", "address": "0x0000000000000000000000000000000000000001"}); self.transactions: list[Mapping[str, Any]] = []
    def get_wallet(self, wallet_id: str | None = None) -> Mapping[str, Any]: return self.wallet
    def get_balance(self, wallet_id: str | None = None, **_: Any) -> Mapping[str, Any]: return {"balances": []}
    def send_transaction(self, wallet_id: str, transaction: Mapping[str, Any], *, caip2: str, confirmed: bool = False) -> Mapping[str, Any]:
        if not confirmed: raise PermissionError("Privy transaction requires explicit confirmation")
        self.transactions.append({"walletId": wallet_id, "transaction": dict(transaction), "caip2": caip2}); return {"status": "simulated", "data": {"hash": None}}
