"""NAV reporting plan with an explicit testnet/live gate."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
from .execution import FundExecutionMode

@dataclass(frozen=True)
class NavReportResult:
    status: str; strategy_nav_usd: float; reason: str
    def as_dict(self) -> dict[str, Any]: return {"status": self.status, "strategyNavUsd": self.strategy_nav_usd, "reason": self.reason}

class FundNavReporter:
    def __init__(self, mode: FundExecutionMode | str = FundExecutionMode.DRY_RUN, *, submit: Callable[[int], Any] | None = None) -> None: self.mode, self.submit = FundExecutionMode(mode), submit
    def report(self, strategy_nav_usd: float, *, explicit_confirmation: bool = False) -> NavReportResult:
        if strategy_nav_usd < 0: raise ValueError("strategy NAV cannot be negative")
        if self.mode == FundExecutionMode.DRY_RUN: return NavReportResult("preview", strategy_nav_usd, "dry-run calculates but does not write the contract")
        if not explicit_confirmation: return NavReportResult("blocked", strategy_nav_usd, "NAV write requires explicit confirmation")
        if self.submit is None: return NavReportResult("blocked", strategy_nav_usd, "no contract submitter configured")
        self.submit(int(round(strategy_nav_usd * 1_000_000))); return NavReportResult("submitted", strategy_nav_usd, "inspect transaction status separately")
