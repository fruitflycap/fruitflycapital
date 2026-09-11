"""Portfolio accounting from our ledger plus independently observed prices."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping
from .ledger import FundLedger
from .valuation import ValuationProvider

@dataclass(frozen=True)
class PositionValue:
    chain_id: int; token_address: str; symbol: str | None; asset_class: str; amount: float; price_usd: float | None; value_usd: float | None; cost_basis_usd: float; unrealized_pnl_usd: float | None
    def as_dict(self) -> dict[str, Any]: return self.__dict__.copy()

@dataclass(frozen=True)
class PortfolioSnapshot:
    observed_at_ms: int; nav_usd: float; nav_per_share_usd: float; shares_outstanding: float; cash_usd: float; deployed_strategy_usd: float; portfolio_return_pct: float; realized_pnl_usd: float; unrealized_pnl_usd: float; positions: tuple[PositionValue, ...]; allocation_by_chain: Mapping[str, float]; recent_trades: tuple[Mapping[str, Any], ...]; nav_history: tuple[Mapping[str, Any], ...]; reconciliation: Mapping[str, Any]
    def as_dict(self) -> dict[str, Any]:
        return {"observedAtMs": self.observed_at_ms, "navUsd": self.nav_usd, "navPerShareUsd": self.nav_per_share_usd, "sharesOutstanding": self.shares_outstanding, "cashUsd": self.cash_usd, "deployedStrategyUsd": self.deployed_strategy_usd, "returnPct": self.portfolio_return_pct, "realizedPnlUsd": self.realized_pnl_usd, "unrealizedPnlUsd": self.unrealized_pnl_usd, "positions": [p.as_dict() for p in self.positions], "allocationByChain": [{"chainId": chain, "weight": weight} for chain, weight in self.allocation_by_chain.items()], "recentTrades": list(self.recent_trades), "navHistory": list(self.nav_history), "reconciliation": dict(self.reconciliation)}

class PortfolioEngine:
    def __init__(self, ledger: FundLedger, valuation: ValuationProvider, *, cash_asset: str = "USDC") -> None: self.ledger, self.valuation, self.cash_asset = ledger, valuation, cash_asset

    def snapshot(self, *, observed_at_ms: int = 0, reported_strategy_nav_usd: float = 0.0, shares_outstanding: float | None = None) -> PortfolioSnapshot:
        rows = self.ledger.rows("positions")
        assets = [(int(row["chain_id"]), str(row["token_address"])) for row in rows]
        quotes = self.valuation.get_prices(assets)
        positions: list[PositionValue] = []
        for row in rows:
            key = (int(row["chain_id"]), str(row["token_address"])); quote = quotes.get(key); value = float(row["amount"]) * quote.price_usd if quote else None
            positions.append(PositionValue(key[0], key[1], row["symbol"], row["asset_class"], float(row["amount"]), quote.price_usd if quote else None, value, float(row["cost_basis_usd"]), value - float(row["cost_basis_usd"]) if value is not None else None))
        priced = [p for p in positions if p.value_usd is not None]
        cash = sum(p.value_usd or 0.0 for p in priced if (p.symbol or "").upper() == self.cash_asset)
        position_value = sum(p.value_usd or 0.0 for p in priced if (p.symbol or "").upper() != self.cash_asset)
        nav = cash + position_value + float(reported_strategy_nav_usd)
        shares = float(shares_outstanding if shares_outstanding is not None else sum(float(x["shares"]) for x in self.ledger.rows("deposits")) - sum(float(x["shares"]) for x in self.ledger.rows("withdrawals") if x["status"] == "claimed"))
        initial = sum(float(x["amount"]) for x in self.ledger.rows("deposits")); returns = ((nav / initial) - 1.0) * 100.0 if initial else 0.0
        by_chain: dict[str, float] = {}; total = nav or 1.0
        for p in priced: by_chain[str(p.chain_id)] = by_chain.get(str(p.chain_id), 0.0) + (p.value_usd or 0.0) / total
        trades = tuple(self.ledger.rows("trades", limit=20))
        realized = sum(float(trade.get("realized_pnl_usd") or 0.0) for trade in self.ledger.rows("trades", limit=10000))
        return PortfolioSnapshot(observed_at_ms, nav, nav / shares if shares else 1.0, shares, cash, position_value + float(reported_strategy_nav_usd), returns, realized, sum(p.unrealized_pnl_usd or 0.0 for p in positions), tuple(positions), by_chain, trades, tuple(self.ledger.rows("nav_snapshots", limit=100)), {"status": "not_checked", "reason": "onchain balances not supplied"})

    def apply_trade(self, *, chain_id: int, token_in: str, token_out: str, amount_in: float, amount_out: float, usd_value: float, symbol_in: str | None = None, symbol_out: str | None = None, asset_class_out: str = "crypto") -> float:
        """Apply a filled swap to book positions and return realized P&L.

        The caller supplies the executed amounts and USD valuation; this
        method never treats a quote or an intent as a fill.
        """
        existing = { (int(row["chain_id"]), str(row["token_address"])): row for row in self.ledger.rows("positions", limit=10000) }
        realized = 0.0
        in_key = (chain_id, token_in); out_key = (chain_id, token_out)
        in_row = existing.get(in_key)
        if in_row and amount_in > 0:
            old_amount, old_cost = float(in_row["amount"]), float(in_row["cost_basis_usd"])
            reduced_cost = old_cost * min(1.0, amount_in / old_amount) if old_amount > 0 else 0.0
            realized = float(usd_value) - reduced_cost
            self.ledger.upsert_position(chain_id=chain_id, token_address=token_in, amount=max(0.0, old_amount - amount_in), cost_basis_usd=max(0.0, old_cost - reduced_cost), symbol=in_row["symbol"], asset_class=in_row["asset_class"])
        out_row = existing.get(out_key)
        self.ledger.upsert_position(chain_id=chain_id, token_address=token_out, amount=(float(out_row["amount"]) if out_row else 0.0) + amount_out, cost_basis_usd=(float(out_row["cost_basis_usd"]) if out_row else 0.0) + float(usd_value), symbol=symbol_out or (out_row["symbol"] if out_row else None), asset_class=asset_class_out)
        return realized

    def reconcile(self, expected: Mapping[tuple[int, str], float], actual: Mapping[tuple[int, str], float], *, tolerance: float = 1e-9) -> dict[str, Any]:
        discrepancies = []
        for key in sorted(set(expected) | set(actual)):
            if abs(float(expected.get(key, 0.0)) - float(actual.get(key, 0.0))) > tolerance: discrepancies.append({"chainId": key[0], "tokenAddress": key[1], "expected": expected.get(key, 0.0), "actual": actual.get(key, 0.0)})
        return {"status": "ok" if not discrepancies else "discrepancy", "discrepancies": discrepancies}
