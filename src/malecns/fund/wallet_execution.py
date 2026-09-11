"""Deprecated direct-wallet compatibility surface; broadcasting is disabled."""

from __future__ import annotations

import os
from typing import Any, Mapping

from .models import TradeIntent
from ..market.direct_uniswap import DirectUniswapClient
from .wallet import ZERO_ADDRESS, RpcWalletClient


class WalletExecutionUnavailable(RuntimeError):
    pass


class DirectWalletUniswapAdapter:
    """Deprecated compatibility name; direct broadcast is disabled.

    Autonomous strategy execution uses ``MainnetExecutionAdapter`` from
    ``autonomous.py``, which stops at unsigned transaction preparation.
    """

    def __init__(self, wallet: RpcWalletClient, client: DirectUniswapClient, private_key: str) -> None:
        self.wallet = wallet
        self.client = client
        self.private_key = private_key

    def execute(self, intent: TradeIntent) -> Mapping[str, Any]:
        raise WalletExecutionUnavailable("direct-wallet broadcast is disabled; use MainnetExecutionAdapter transaction preparation")

        # Kept below only as a migration reference for older integrations;
        # the unconditional boundary above makes this path unreachable.
        if not self.private_key:
            raise WalletExecutionUnavailable("PRIVATE_KEY is not configured")
        snapshot = self.wallet.snapshot()
        if snapshot.chain_id != intent.chain_id:
            raise WalletExecutionUnavailable("trade chain does not match the wallet RPC chain")
        if intent.token_in.lower() == ZERO_ADDRESS.lower() and int(intent.amount) > snapshot.available_native_wei:
            raise WalletExecutionUnavailable("native input exceeds the wallet balance after the gas reserve")
        self._assert_signer_matches_wallet(snapshot.wallet_address)
        quote = self.client.quote(
            {
                "type": "EXACT_INPUT",
                "amount": intent.amount,
                "tokenIn": intent.token_in,
                "tokenOut": intent.token_out,
                "tokenInChainId": intent.chain_id,
                "tokenOutChainId": intent.chain_id,
                "swapper": snapshot.wallet_address,
            }
        )
        if intent.token_in.lower() != ZERO_ADDRESS.lower():
            approval = self.client.check_approval(
                {
                    "token": intent.token_in,
                    "amount": intent.amount,
                    "chainId": intent.chain_id,
                    "tokenOut": intent.token_out,
                    "tokenOutChainId": intent.chain_id,
                    "walletAddress": snapshot.wallet_address,
                }
            )
            if _approval_required(approval):
                return {"status": "approval_required", "quote": quote, "approval": approval, "txHash": None}
        swap = self.client.create_unsigned_swap(quote)
        transaction = _transaction_from_swap(swap)
        raw_transaction = self._sign(transaction)
        tx_hash = self.wallet.send_raw_transaction(raw_transaction)
        return {
            "status": "submitted",
            "txHash": tx_hash,
            "quote": quote,
            "swap": swap,
        }

    def _sign(self, transaction: Mapping[str, Any]) -> str:
        try:
            from eth_account import Account
        except ImportError as exc:
            raise WalletExecutionUnavailable("install the fund extra to enable PRIVATE_KEY signing") from exc
        tx = dict(transaction)
        tx.setdefault("chainId", self.wallet.snapshot().chain_id)
        tx.setdefault("nonce", int(self.wallet.call("eth_getTransactionCount", [self.wallet.wallet_address, "pending"]), 16))
        if "gas" not in tx:
            tx["gas"] = int(self.wallet.call("eth_estimateGas", [_rpc_transaction(tx)]), 16)
        if "gasPrice" not in tx and "maxFeePerGas" not in tx:
            tx["gasPrice"] = int(self.wallet.call("eth_gasPrice", []), 16)
        signed = Account.sign_transaction(tx, self.private_key)
        raw = getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction", None)
        if raw is None:
            raise WalletExecutionUnavailable("signer did not return raw transaction bytes")
        return "0x" + bytes(raw).hex()

    def _assert_signer_matches_wallet(self, wallet_address: str) -> None:
        try:
            from eth_account import Account
        except ImportError as exc:
            raise WalletExecutionUnavailable("install the fund extra to enable PRIVATE_KEY signing") from exc
        derived = Account.from_key(self.private_key).address
        if derived.lower() != wallet_address.lower():
            raise WalletExecutionUnavailable("PRIVATE_KEY does not control FUND_WALLET_ADDRESS")


def _approval_required(payload: Mapping[str, Any]) -> bool:
    if payload.get("approval") is not None:
        return True
    if payload.get("approvalTransaction") is not None:
        return True
    return str(payload.get("status", "")).lower() in {"required", "not_approved", "approval_required"}


def _transaction_from_swap(payload: Mapping[str, Any]) -> dict[str, Any]:
    candidate = payload.get("swap") or payload.get("transaction")
    if not isinstance(candidate, Mapping):
        candidate = payload
    to = candidate.get("to")
    data = candidate.get("data") or candidate.get("calldata")
    if not isinstance(to, str) or not to.startswith("0x") or len(to) != 42:
        raise WalletExecutionUnavailable("Uniswap response did not include a valid transaction recipient")
    if not isinstance(data, str) or not data.startswith("0x") or len(data) < 4:
        raise WalletExecutionUnavailable("Uniswap response did not include swap calldata")
    transaction: dict[str, Any] = {"to": to, "data": data}
    for source, target in (("value", "value"), ("gas", "gas"), ("chainId", "chainId"), ("maxFeePerGas", "maxFeePerGas"), ("maxPriorityFeePerGas", "maxPriorityFeePerGas"), ("gasPrice", "gasPrice"), ("nonce", "nonce")):
        if candidate.get(source) is not None:
            transaction[target] = _numeric(candidate[source])
    return transaction


def _numeric(value: Any) -> int:
    return int(value, 16) if isinstance(value, str) and value.startswith("0x") else int(value)


def _rpc_transaction(transaction: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(transaction)
    result["from"] = result.get("from") or os.getenv("FUND_WALLET_ADDRESS", "")
    for key in ("value", "gas", "gasPrice", "maxFeePerGas", "maxPriorityFeePerGas", "nonce", "chainId"):
        if key in result:
            result[key] = hex(int(result[key]))
    return result
