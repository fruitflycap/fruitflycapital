from __future__ import annotations

from malecns.fund import SwarmDecisionPipeline
from malecns.swarm.observer import FlyObservation, HabitatObservation, SwarmObserver


def _frame(timestamp_ms: int, positions: dict[str, tuple[float, float, float]], distances: dict[str, dict[str, float]]):
    return tuple(
        FlyObservation(
            fly_id=fly_id,
            timestamp_ms=timestamp_ms,
            position=position,
            habitats=tuple(
                HabitatObservation(habitat_id, distance, 0.05)
                for habitat_id, distance in habitat_distances.items()
            ),
        )
        for fly_id, position in positions.items()
        for habitat_distances in (distances[fly_id],)
    )


def test_temporal_consensus_prefers_sustained_behavior_over_one_frame_headcount():
    pipeline = SwarmDecisionPipeline(expected_agents=4)
    positions = {f"fly-{index}": (index * 0.02, 0.5, 0.0) for index in range(4)}
    for timestamp in range(0, 31_000, 1_000):
        distances = {
            "fly-0": {"ETH": 0.03, "TOKEN-X": 0.30},
            "fly-1": {"ETH": 0.03, "TOKEN-X": 0.30},
            "fly-2": {"ETH": 0.03, "TOKEN-X": 0.03 if timestamp == 30_000 else 0.30},
            "fly-3": {"ETH": 0.30, "TOKEN-X": 0.30},
        }
        decision = pipeline.ingest(_frame(timestamp, positions, distances))

    convictions = {item.habitat_id: item for item in decision.convictions}
    targets = {item.habitat_id: item.target_weight for item in decision.targets}
    assert convictions["ETH"].conviction > convictions["TOKEN-X"].conviction
    assert targets["ETH"] > targets["TOKEN-X"]
    assert decision.execution_status == "proposal_only"
    assert all(item.allowed for item in decision.risk)


def test_observer_keeps_each_primary_agent_in_the_evidence():
    pipeline = SwarmDecisionPipeline(expected_agents=2)
    decision = pipeline.ingest(
        [
            FlyObservation("fly-001", 0, (0, 0, 0), (HabitatObservation("ETH", 0.03, 0.05),)),
            FlyObservation("fly-002", 0, (1, 0, 0), (HabitatObservation("ETH", 0.30, 0.05),)),
        ]
    )
    summary = decision.behavior[0]
    assert summary.observed_agents == 2
    assert {item.fly_id for item in summary.agent_behaviors} == {"fly-001", "fly-002"}


def test_contact_dwell_emits_buy_and_departure_emits_sell_intents():
    pipeline = SwarmDecisionPipeline(expected_agents=16)
    inside = lambda timestamp: [FlyObservation(
        "fly-001",
        timestamp,
        (0, 0, 0),
        (HabitatObservation("ETH", 0.03, 0.05, contact=True),),
    )]
    outside = lambda timestamp: [FlyObservation(
        "fly-001",
        timestamp,
        (1, 0, 0),
        (HabitatObservation("ETH", 0.30, 0.05, contact=False),),
    )]

    pipeline.ingest(inside(0))
    pipeline.ingest(inside(1_000))
    decision = pipeline.ingest(outside(2_000))

    intents = decision.behavior_intents
    assert [item.side for item in intents] == ["buy", "sell"]
    assert intents[0].reason == "dwell"
    assert intents[1].reason == "departure"
    assert intents[0].metrics["contact"] is True
    assert intents[1].metrics["contact"] is False
    assert intents[0].portfolio_weight == 0.0625
    assert intents[1].portfolio_weight == 0.0625


def test_observer_allows_only_one_active_commitment_per_fly():
    observer = SwarmObserver(
        expected_agents=1,
        sustained_dwell_s=1.0,
        intent_cooldown_s=30.0,
    )

    def frame(timestamp_ms, first_distance, second_distance, first_contact=False, second_contact=False):
        return [FlyObservation(
            "fly-001",
            timestamp_ms,
            (0.0, 0.0, 0.0),
            (
                HabitatObservation("TOKEN-A", first_distance, 0.05, contact=first_contact),
                HabitatObservation("TOKEN-B", second_distance, 0.05, contact=second_contact),
            ),
        )]

    observer.ingest(frame(0, 0.03, 0.30, True, False))
    observer.ingest(frame(1_000, 0.03, 0.03, True, True))
    observer.ingest(frame(2_000, 0.03, 0.03, True, True))
    buys = [intent for intent in observer.snapshot().behavior_intents if intent.side == "buy"]
    assert [intent.habitat_id for intent in buys] == ["TOKEN-A"]
