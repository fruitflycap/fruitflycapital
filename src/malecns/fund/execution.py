"""Execution boundary with hard defaults against accidental live trading."""
from __future__ import annotations
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Protocol
from .models import TradeIntent

class FundExecutionMode(str, Enum): DRY_RUN = "dry-run"; TESTNET = "testnet"; WALLET = "wallet"; LIVE = "live"
@dataclass(frozen=True)
class ExecutionRecord:
    status: str; mode: str; trade_intent: Mapping[str, Any]; reason: str
    def as_dict(self) -> dict[str, Any]: return {"status": self.status, "mode": self.mode, "tradeIntent": dict(self.trade_intent), "reason": self.reason}
class ExecutionAdapter(Protocol):
    def execute(self, intent: TradeIntent) -> Mapping[str, Any]: ...
class FakeExecutionAdapter:
    def __init__(self) -> None: self.calls: list[TradeIntent] = []
    def execute(self, intent: TradeIntent) -> Mapping[str, Any]: self.calls.append(intent); return {"status": "simulated", "txHash": None}

class UniswapQuoteAdapter:
    """Quote/unsigned-calldata adapter; it deliberately has no broadcast path."""
    def __init__(self, client: Any) -> None: self.client = client
    def execute(self, intent: TradeIntent) -> Mapping[str, Any]:
        quote = self.client.quote({"type": "EXACT_INPUT", "amount": intent.amount, "tokenIn": intent.token_in, "tokenOut": intent.token_out, "chainId": intent.chain_id})
        unsigned = self.client.create_unsigned_swap(quote)
        return {"status": "unsigned_calldata", "txHash": None, "quote": quote, "unsigned": unsigned}

class ExecutionEngine:
    def __init__(self, mode: FundExecutionMode | str | None = None, *, adapter: ExecutionAdapter | None = None, live_confirmed: bool | None = None, max_trade_usd: float | None = None, max_daily_trade_usd: float | None = None) -> None:
        self.mode = FundExecutionMode(mode or os.getenv("FUND_EXECUTION_MODE", "dry-run")); self.adapter = adapter; self.live_confirmed = bool(live_confirmed if live_confirmed is not None else os.getenv("FUND_LIVE_TRADING_CONFIRMED", "false").lower() == "true"); self.max_trade_usd = float(max_trade_usd if max_trade_usd is not None else os.getenv("FUND_MAX_TRADE_USD", "10")); self.max_daily_trade_usd = float(max_daily_trade_usd if max_daily_trade_usd is not None else os.getenv("FUND_MAX_DAILY_TRADE_USD", "50"))
    def execute(self, intent: TradeIntent, *, explicit_confirmation: bool = False, usd_value: float | None = None, daily_usd_value: float | None = None) -> ExecutionRecord:
        if usd_value is not None and usd_value > self.max_trade_usd: return ExecutionRecord("blocked", self.mode.value, intent.as_dict(), "per-trade USD cap exceeded")
        if daily_usd_value is not None and daily_usd_value > self.max_daily_trade_usd: return ExecutionRecord("blocked", self.mode.value, intent.as_dict(), "daily USD cap exceeded")
        if self.mode == FundExecutionMode.DRY_RUN: return ExecutionRecord("proposal_only", self.mode.value, intent.as_dict(), "dry-run never signs or broadcasts")
        if self.mode in {FundExecutionMode.WALLET, FundExecutionMode.LIVE} and not (self.live_confirmed and explicit_confirmation): return ExecutionRecord("blocked", self.mode.value, intent.as_dict(), "wallet execution requires FUND_LIVE_TRADING_CONFIRMED=true and explicit confirmation")
        if self.adapter is None: return ExecutionRecord("blocked", self.mode.value, intent.as_dict(), "no execution adapter configured")
        try:
            result = self.adapter.execute(intent)
        except Exception as exc:
            return ExecutionRecord("blocked", self.mode.value, intent.as_dict(), str(exc))
        return ExecutionRecord(str(result.get("status", "submitted")), self.mode.value, intent.as_dict(), "adapter result; inspect tx status separately")
