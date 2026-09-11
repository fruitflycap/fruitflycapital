from __future__ import annotations

from dataclasses import dataclass

from ..models import TokenState
from .models import InvestabilityResult


@dataclass(frozen=True)
class InvestabilityGuard:
    """Hard execution boundary; the CNS never decides these failures."""

    min_executable_liquidity_usd: float = 10_000.0
    supported_chains: tuple[str, ...] = ("ethereum", "base", "robinhood")
    max_tax_bps: int = 1_000
    require_security_evidence: bool = False

    def evaluate(self, state: TokenState) -> InvestabilityResult:
        reasons: list[str] = []
        facts: list[dict[str, object]] = []
        security = state.security
        chain = state.chain_id.lower()
        if not state.token_address or not state.pool_id or not state.pair_address:
            reasons.append("missing token or execution pair identity")
        if chain not in {item.lower() for item in self.supported_chains}:
            reasons.append(f"unsupported execution chain: {chain}")
        liquidity = float(state.liquidity.liquidity_usd)
        facts.append({"field": "liquidityUsd", "value": liquidity})
        if liquidity < self.min_executable_liquidity_usd:
            reasons.append("liquidity below executable threshold")
        if security.honeypot is True:
            reasons.append("confirmed honeypot")
        if security.sellable is False:
            reasons.append("token is not sellable")
        if security.blacklist_mechanic is True:
            reasons.append("blacklist mechanics detected")
        for label, tax in (("buy", security.buy_tax_bps), ("sell", security.sell_tax_bps)):
            if tax is not None and tax > self.max_tax_bps:
                reasons.append(f"{label} tax exceeds configured maximum")
        if self.require_security_evidence and security.status != "available":
            reasons.append("critical security evidence unavailable")
        if reasons:
            return InvestabilityResult(False, "critical", tuple(reasons), tuple(facts))
        if security.status != "available":
            return InvestabilityResult(True, "unknown", ("security evidence unavailable; execution policy must decide",), tuple(facts))
        return InvestabilityResult(True, "pass", (), tuple(facts))
