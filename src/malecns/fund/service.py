"""Application service used by the WebSocket adapter and portfolio page."""
from __future__ import annotations
import os
from typing import Any, Iterable, Mapping
from .execution import ExecutionEngine
from .ledger import FundLedger
from .portfolio import PortfolioEngine
from .valuation import FakeValuationProvider
from .wallet import RpcWalletClient, WalletRpcError

class FundService:
    def __init__(self, ledger: FundLedger, portfolio: PortfolioEngine, execution: ExecutionEngine, wallet: RpcWalletClient | None = None) -> None: self.ledger, self.portfolio, self.execution, self.wallet = ledger, portfolio, execution, wallet
    @classmethod
    def from_env(cls) -> "FundService":
        # Supabase is the shared queue between the brain and executor. Keep a
        # separate local brain ledger so a stale legacy process holding
        # data/fund/fund.db cannot prevent the websocket server from starting.
        configured_path = os.getenv("FUND_DB_PATH")
        if configured_path:
            ledger_path = configured_path
        elif os.getenv("FUND_ADAPTER", "simulation").lower() == "supabase":
            ledger_path = os.getenv("FUND_BRAIN_DB_PATH", "data/fund/brain.db")
        else:
            ledger_path = "data/fund/fund.db"
        ledger = FundLedger(ledger_path)
        wallet = RpcWalletClient.from_env()
        # The autonomous runtime owns strategy execution. Keep this legacy
        # service read-only/guarded so no hidden route reaches a signer.
        return cls(ledger, PortfolioEngine(ledger, FakeValuationProvider()), ExecutionEngine(), wallet)
    def status(self) -> dict[str, Any]:
        wallet_payload: dict[str, Any] = {"configured": self.wallet is not None, "source": "rpc"}
        if self.wallet is not None:
            try:
                wallet_payload = {"configured": True, **self.wallet.snapshot().as_dict()}
            except (WalletRpcError, ValueError) as exc:
                wallet_payload = {"configured": True, "status": "error", "error": str(exc), "address": self.wallet.wallet_address, "source": "rpc"}
        try:
            fly_count = max(1, min(100, int(os.getenv("NEUROSWARM_SWARM_SIZE", "8"))))
        except ValueError:
            fly_count = 8
        fly_weight = min(1.0 / fly_count, float(os.getenv("FUND_MAX_PER_FLY_ALLOCATION_FRACTION", "0.0625")))
        allocation: dict[str, Any] = {"flyCount": fly_count, "perFlyWeight": fly_weight, "perFlyPercent": fly_weight * 100.0, "maxStrategyAllocationPercent": min(100.0, fly_weight * fly_count * 100.0), "basis": "tradeable wallet balance after gas reserve; prior per-fly cap preserved"}
        if wallet_payload.get("availableToTrade") is not None:
            allocation["perFlyBudget"] = float(wallet_payload["availableToTrade"]) * fly_weight
            allocation["perFlyBudgetSymbol"] = wallet_payload.get("nativeSymbol", "ETH")
        resolved_chain_id = int(wallet_payload.get("chainId") or os.getenv("FUND_CHAIN_ID") or "4663")
        return {"name": "Fruit Fly Capital", "mode": os.getenv("FUND_EXECUTION_MODE", "dry-run"), "chainId": resolved_chain_id, "rpcUrl": os.getenv("FUND_RPC_URL"), "explorerUrl": os.getenv("FUND_EXPLORER_URL") or "https://robinhoodchain.blockscout.com", "wallet": wallet_payload, "allocation": allocation, "contractAddress": os.getenv("FUND_CONTRACT_ADDRESS"), "treasuryAddress": os.getenv("FUND_WALLET_ADDRESS") or os.getenv("PRIVY_WALLET_ADDRESS"), "accountingAsset": os.getenv("FUND_ACCOUNTING_ASSET", "ETH"), "wethAddress": os.getenv("FUND_WETH_ADDRESS"), "security": {"walletProvider": "private-key-server", "policyConfigured": False, "autonomousTradeLimitUsd": float(os.getenv("FUND_MAX_TRADE_USD", "10"))}, "executionBoundary": "read-only-compatibility" if self.execution.mode.value == "dry-run" else "guarded", "contracts": {"retained": True, "active": False}}
    def portfolio_update(self) -> dict[str, Any]: return {"fund": {**self.status(), **self.portfolio.snapshot().as_dict()}, "demoData": False}
    def trade_history(self) -> dict[str, Any]: return {"trades": self.ledger.rows("trades", limit=50), "demoData": False}
