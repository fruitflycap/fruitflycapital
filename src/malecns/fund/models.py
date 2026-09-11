"""Explicit fund proposal models, separate from custody and signing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class TradeRoute:
    """A caller-supplied route identity; never inferred from a habitat label."""

    habitat_id: str
    token_in: str
    token_out: str
    amount: str
    chain_id: int


@dataclass(frozen=True)
class TradeIntent:
    habitat_id: str
    side: str
    token_in: str
    token_out: str
    amount: str
    chain_id: int
    target_weight: float
    conviction: float
    rationale: str
    status: str = "proposal_only"
    requires_human_signature: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "habitatId": self.habitat_id,
            "side": self.side,
            "tokenIn": self.token_in,
            "tokenOut": self.token_out,
            "amount": self.amount,
            "chainId": self.chain_id,
            "targetWeight": round(self.target_weight, 6),
            "conviction": round(self.conviction, 6),
            "rationale": self.rationale,
            "status": self.status,
            "requiresHumanSignature": self.requires_human_signature,
        }
