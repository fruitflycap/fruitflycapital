"""Composable swarm-to-fund decision pipeline.

No signer, wallet, Privy client, or transaction broadcaster belongs here. The
output is an auditable proposal that a future human-approved custody boundary
may consume.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from malecns.swarm.consensus import HabitatConviction, TemporalConsensusEngine
from malecns.swarm.observer import BehaviorTradeIntent, FlyObservation, HabitatSwarmSummary, SwarmObserver, SwarmSnapshot

from .allocation import PortfolioAllocator, PortfolioTarget
from .models import TradeIntent, TradeRoute
from .risk import RiskGuard, RiskResult


@dataclass(frozen=True)
class FundDecision:
    observed_at_ms: int
    behavior: tuple[HabitatSwarmSummary, ...]
    convictions: tuple[HabitatConviction, ...]
    targets: tuple[PortfolioTarget, ...]
    risk: tuple[RiskResult, ...]
    trade_intents: tuple[TradeIntent, ...] = ()
    execution_status: str = "proposal_only"
    behavior_intents: tuple[BehaviorTradeIntent, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "observedAtMs": self.observed_at_ms,
            "behavior": [summary.as_dict() for summary in self.behavior],
            "convictions": [conviction.as_dict() for conviction in self.convictions],
            "targets": [target.as_dict() for target in self.targets],
            "risk": [item.as_dict() for item in self.risk],
            "tradeIntents": [item.as_dict() for item in self.trade_intents],
            "behaviorIntents": [item.as_dict() for item in self.behavior_intents],
            "executionStatus": self.execution_status,
            "privy": {"configured": False, "broadcastEnabled": False},
        }


class SwarmDecisionPipeline:
    def __init__(
        self,
        expected_agents: int,
        *,
        observer: SwarmObserver | None = None,
        consensus: TemporalConsensusEngine | None = None,
        allocator: PortfolioAllocator | None = None,
        risk_guard: RiskGuard | None = None,
        routes: Mapping[str, TradeRoute] | None = None,
    ) -> None:
        self.observer = observer or SwarmObserver(expected_agents)
        self.consensus = consensus or TemporalConsensusEngine()
        self.allocator = allocator or PortfolioAllocator()
        self.risk_guard = risk_guard or RiskGuard(max_position_weight=self.allocator.max_position_weight)
        self.routes = dict(routes or {})

    def ingest(
        self,
        observations: Iterable[FlyObservation],
        *,
        current_weights: Mapping[str, float] | None = None,
    ) -> FundDecision:
        snapshot = self.observer.ingest(observations)
        return self._decide(snapshot, current_weights=current_weights)

    def snapshot(self, *, current_weights: Mapping[str, float] | None = None) -> FundDecision:
        return self._decide(self.observer.snapshot(), current_weights=current_weights)

    def _decide(self, snapshot: SwarmSnapshot, *, current_weights: Mapping[str, float] | None = None) -> FundDecision:
        convictions = self.consensus.evaluate(snapshot.habitats)
        targets = self.allocator.allocate(convictions)
        risk = self.risk_guard.evaluate(targets)
        intents = self._trade_intents(targets, convictions, risk, current_weights or {})
        return FundDecision(
            snapshot.observed_at_ms,
            snapshot.habitats,
            convictions,
            targets,
            risk,
            intents,
            "proposal_only",
            snapshot.behavior_intents,
        )

    def _trade_intents(
        self,
        targets: tuple[PortfolioTarget, ...],
        convictions: tuple[HabitatConviction, ...],
        risk: tuple[RiskResult, ...],
        current_weights: Mapping[str, float],
    ) -> tuple[TradeIntent, ...]:
        conviction_by_id = {item.habitat_id: item for item in convictions}
        risk_by_id = {item.habitat_id: item for item in risk}
        intents: list[TradeIntent] = []
        for target in targets:
            route = self.routes.get(target.habitat_id)
            risk_result = risk_by_id.get(target.habitat_id)
            current = max(0.0, float(current_weights.get(target.habitat_id, 0.0)))
            if route is None or risk_result is None or not risk_result.allowed or abs(target.target_weight - current) < 1e-9:
                continue
            conviction = conviction_by_id[target.habitat_id]
            intents.append(
                TradeIntent(
                    habitat_id=target.habitat_id,
                    side="buy" if target.target_weight > current else "sell",
                    token_in=route.token_in,
                    token_out=route.token_out,
                    amount=route.amount,
                    chain_id=route.chain_id,
                    target_weight=target.target_weight,
                    conviction=conviction.conviction,
                    rationale=(
                        f"temporal swarm target changed from {current:.4f} "
                        f"to {target.target_weight:.4f}; no instant-headcount rule"
                    ),
                )
            )
        return tuple(intents)
