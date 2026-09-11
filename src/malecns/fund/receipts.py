"""Post-broadcast Robinhood Chain receipt and Blockscout verification.

This module starts at a real transaction hash. It never creates hashes and it
never treats a simulation identifier as a mainnet execution. The JSON-RPC
receipt is canonical; Blockscout is an optional presentation/enrichment layer.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Mapping


ROBINHOOD_CHAIN_ID = 4663
ROBINHOOD_EXPLORER_URL = "https://robinhoodchain.blockscout.com"
TX_HASH_RE = r"^0x[a-fA-F0-9]{64}$"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


class ReceiptStatus:
    BROADCAST = "BROADCAST"
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REVERTED = "REVERTED"


JsonFetcher = Callable[[str, float], Any]


@dataclass
class BlockscoutClient:
    """Small cached public metadata client; failures are deliberately soft."""

    base_url: str = ROBINHOOD_EXPLORER_URL
    timeout_seconds: float = 8.0
    fetcher: JsonFetcher | None = None
    _cache: dict[str, dict[str, Any]] = field(default_factory=dict, init=False, repr=False)

    @classmethod
    def from_env(cls) -> "BlockscoutClient":
        return cls(
            base_url=os.getenv("FUND_EXPLORER_URL", ROBINHOOD_EXPLORER_URL).strip() or ROBINHOOD_EXPLORER_URL,
            timeout_seconds=float(os.getenv("BLOCKSCOUT_TIMEOUT_SECONDS", "8")),
        )

    def transaction(self, tx_hash: str) -> dict[str, Any]:
        cached = self._cache.get(tx_hash.lower())
        if cached is not None:
            return cached
        url = f"{self.base_url.rstrip('/')}/api/v2/transactions/{tx_hash}"
        try:
            payload = self.fetcher(url, self.timeout_seconds) if self.fetcher else self._request(url)
        except Exception as exc:
            raise RuntimeError(f"Blockscout request failed: {exc}") from exc
        if not isinstance(payload, dict):
            raise RuntimeError("Blockscout returned a non-object response")
        self._cache[tx_hash.lower()] = payload
        return payload

    def _request(self, url: str) -> Any:
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "fruit-fly-capital/0.1"}, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(str(exc)) from exc


@dataclass(frozen=True)
class ReceiptObservation:
    status: str
    explorer_url: str
    block_number: int | None = None
    transaction_index: int | None = None
    sender: str | None = None
    recipient: str | None = None
    gas_used: str | None = None
    effective_gas_price: str | None = None
    transaction_fee: str | None = None
    receipt_status: str | None = None
    actual_input_amount: str | None = None
    actual_output_amount: str | None = None
    actual_token_received: dict[str, Any] | None = None
    transfer_events: tuple[dict[str, Any], ...] = ()
    blockscout: dict[str, Any] | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "explorerUrl": self.explorer_url,
            "blockNumber": self.block_number,
            "transactionIndex": self.transaction_index,
            "from": self.sender,
            "to": self.recipient,
            "gasUsed": self.gas_used,
            "effectiveGasPrice": self.effective_gas_price,
            "transactionFee": self.transaction_fee,
            "receiptStatus": self.receipt_status,
            "actualInputAmount": self.actual_input_amount,
            "actualOutputAmount": self.actual_output_amount,
            "actualTokenReceived": self.actual_token_received,
            "transferEvents": list(self.transfer_events),
            "blockscout": self.blockscout,
            "error": self.error,
        }


def explorer_url(tx_hash: str) -> str:
    base_url = os.getenv("FUND_EXPLORER_URL", ROBINHOOD_EXPLORER_URL).strip() or ROBINHOOD_EXPLORER_URL
    return f"{base_url.rstrip('/')}/tx/{tx_hash}"


def observe_receipt(
    wallet: Any,
    tx_hash: str,
    *,
    side: str,
    token_address: str,
    token_symbol: str,
    input_token: str,
    input_amount: str,
    blockscout: BlockscoutClient | None = None,
    wallet_before_native_wei: int | None = None,
    wallet_before_input_raw: int | None = None,
    wallet_before_output_raw: int | None = None,
    output_decimals: int | None = None,
) -> ReceiptObservation:
    """Read one canonical receipt and derive best-effort transfer amounts."""

    url = explorer_url(tx_hash)
    receipt = wallet.call("eth_getTransactionReceipt", [tx_hash])
    if receipt is None:
        return ReceiptObservation(ReceiptStatus.PENDING, url)
    raw_receipt_status = receipt.get("status")
    if raw_receipt_status is None:
        return ReceiptObservation(ReceiptStatus.PENDING, url)
    receipt_status = _hex_int(raw_receipt_status)
    if receipt_status == 0:
        status = ReceiptStatus.REVERTED
    elif receipt_status == 1:
        status = ReceiptStatus.CONFIRMED
    else:
        return ReceiptObservation(ReceiptStatus.PENDING, url, receipt_status=_hex_or_none(receipt.get("status")))

    transaction = wallet.call("eth_getTransactionByHash", [tx_hash]) or {}
    sender = _address_from_topic(transaction.get("from")) or _address_from_topic(receipt.get("from"))
    recipient = _address_from_topic(transaction.get("to")) or _address_from_topic(receipt.get("to"))
    gas_used_int = _hex_int(receipt.get("gasUsed"))
    effective_price_int = _hex_int(receipt.get("effectiveGasPrice"))
    fee_int = gas_used_int * effective_price_int
    transfers = _transfer_events(receipt.get("logs"), sender)
    token_key = token_address.lower()
    relevant = [event for event in transfers if str(event.get("tokenAddress", "")).lower() == token_key]
    wallet_key = str(getattr(wallet, "wallet_address", "")).lower()
    if not wallet_key and sender:
        wallet_key = sender.lower()
    token_sent_raw = sum(int(event["amountRaw"]) for event in relevant if str(event.get("from", "")).lower() == wallet_key)
    token_received_raw = sum(int(event["amountRaw"]) for event in relevant if str(event.get("to", "")).lower() == wallet_key)

    tx_value = _hex_int(transaction.get("value"))
    actual_input = _format_raw(token_sent_raw if input_token.lower() != _zero_address() else tx_value, 18)
    if side.lower() == "buy":
        actual_output = _format_raw(token_received_raw, output_decimals or 0) if token_received_raw else None
        received = {"tokenAddress": token_address, "tokenSymbol": token_symbol, "amountRaw": str(token_received_raw), "amount": actual_output, "decimals": output_decimals} if token_received_raw else None
    else:
        actual_output = _native_output_after_fee(wallet, wallet_before_native_wei, fee_int)
        received = {"tokenAddress": _zero_address(), "tokenSymbol": "ETH", "amount": actual_output, "amountRaw": _raw_from_decimal(actual_output, 18) if actual_output is not None else None, "decimals": 18} if actual_output is not None else None
    metadata: dict[str, Any] | None = None
    metadata_error: str | None = None
    if status == ReceiptStatus.CONFIRMED and blockscout is not None:
        try:
            metadata = blockscout.transaction(tx_hash)
        except Exception as exc:
            # Public enrichment is optional. Never turn this into an on-chain
            # failure or alter the canonical receipt classification.
            metadata_error = str(exc)
    return ReceiptObservation(
        status=status,
        explorer_url=url,
        block_number=_hex_int_or_none(receipt.get("blockNumber")),
        transaction_index=_hex_int_or_none(receipt.get("transactionIndex")),
        sender=sender,
        recipient=recipient,
        gas_used=str(gas_used_int),
        effective_gas_price=str(effective_price_int),
        transaction_fee=str(fee_int),
        receipt_status=_hex_or_none(receipt.get("status")),
        actual_input_amount=actual_input,
        actual_output_amount=actual_output,
        actual_token_received=received,
        transfer_events=tuple(relevant),
        blockscout=metadata,
        error=metadata_error,
    )


def _transfer_events(logs: Any, wallet_address: str | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    if not isinstance(logs, list):
        return result
    for log in logs:
        if not isinstance(log, Mapping):
            continue
        topics = log.get("topics")
        if not isinstance(topics, list) or len(topics) < 3 or str(topics[0]).lower() != TRANSFER_TOPIC:
            continue
        amount_raw = _hex_int(log.get("data"))
        result.append({
            "tokenAddress": str(log.get("address") or ""),
            "from": _address_from_topic(topics[1]),
            "to": _address_from_topic(topics[2]),
            "amountRaw": str(amount_raw),
            "walletInvolved": bool(wallet_address and wallet_address.lower() in {str(_address_from_topic(topics[1]) or "").lower(), str(_address_from_topic(topics[2]) or "").lower()}),
        })
    return result


def _native_output_after_fee(wallet: Any, before_wei: int | None, fee_wei: int) -> str | None:
    if before_wei is None:
        return None
    try:
        after_wei = int(wallet.snapshot().native_balance_wei)
    except Exception:
        return None
    output_wei = after_wei - before_wei + fee_wei
    return _format_raw(output_wei, 18) if output_wei >= 0 else None


def _format_raw(value: int, decimals: int) -> str:
    if decimals <= 0:
        return str(value)
    return format(Decimal(value) / (Decimal(10) ** decimals), "f")


def _raw_from_decimal(value: str | None, decimals: int) -> str | None:
    if value is None:
        return None
    try:
        return str(int(Decimal(value) * (Decimal(10) ** decimals)))
    except Exception:
        return None


def _hex_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    return int(str(value), 16) if str(value).startswith("0x") else int(str(value))


def _hex_int_or_none(value: Any) -> int | None:
    return None if value is None else _hex_int(value)


def _hex_or_none(value: Any) -> str | None:
    return None if value is None else str(value)


def _address_from_topic(value: Any) -> str | None:
    if not isinstance(value, str) or not value.startswith("0x"):
        return None
    raw = value[2:]
    if len(raw) == 64:
        raw = raw[-40:]
    return f"0x{raw}" if len(raw) == 40 else None


def _zero_address() -> str:
    return "0x0000000000000000000000000000000000000000"
