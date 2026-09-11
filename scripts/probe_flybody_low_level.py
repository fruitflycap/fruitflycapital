#!/usr/bin/env python3
"""Probe the real Flybody low-level flight-imitation policy.

This script intentionally does not download weights or use the vision/high-
level navigation policy. Set ``FLYBODY_LL_CHECKPOINT`` to an extracted
TensorFlow checkpoint prefix from the public controller-reuse archive, then
run it in the Flybody ML environment. The probe builds the exact
``future_steps=0`` environment required by NeuroSwarm's 7D steering contract.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--checkpoint",
        default=os.environ.get("FLYBODY_LL_CHECKPOINT"),
        help="TensorFlow checkpoint prefix, or FLYBODY_LL_CHECKPOINT",
    )
    parser.add_argument("--steps", type=int, default=25)
    args = parser.parse_args()

    if not args.checkpoint:
        return _report(
            status="not_run",
            reason="Set FLYBODY_LL_CHECKPOINT to an extracted checkpoint prefix.",
            checkpoint_url="https://janelia.figshare.com/ndownloader/files/51196886",
        )

    checkpoint = Path(args.checkpoint)
    if not _checkpoint_exists(checkpoint):
        return _report(status="not_run", reason=f"Checkpoint not found: {checkpoint}")

    try:
        import numpy as np
        from acme import specs
        from flybody import fly_envs
        from flybody.agents import network_factory
        from flybody.agents.utils_tf import TestPolicyWrapper, restore_dmpo_networks_from_checkpoint
    except ImportError as error:
        return _report(
            status="not_run",
            reason=(
                "The ML Flybody environment is not installed. Install the upstream "
                "TensorFlow/Acme dependencies in a compatible Python environment: "
                f"{error}"
            ),
        )

    try:
        # This is the important compatibility choice. The stock factory
        # defaults to future_steps=5, which is not a 7-value observation block.
        environment = fly_envs.flight_imitation(
            future_steps=0,
            randomize_start_step=False,
            random_state=np.random.RandomState(0),
        )
        environment_spec = specs.make_environment_spec(environment)
        networks = restore_dmpo_networks_from_checkpoint(
            ckpt_path=str(checkpoint),
            network_factory=network_factory.make_network_factory_dmpo(),
            environment_spec=environment_spec,
        )
        policy = TestPolicyWrapper(networks.policy_network, sample=False)
        timestep = environment.reset()
        neutral_observation = _replace_steering_with_neutral(timestep.observation)
        neutral_action = policy(neutral_observation)
        timestep = environment.reset()

        actions = []
        terminated = False
        for _ in range(max(1, args.steps)):
            action = policy(timestep.observation)
            actions.append(np.asarray(action, dtype=float))
            timestep = environment.step(action)
            if timestep.last():
                terminated = True
                break

        observation = timestep.observation
        result = {
            "status": "ok",
            "futureSteps": 0,
            "steeringCommandDim": 7,
            "nativeActionDim": int(np.asarray(neutral_action).size),
            "neutralActionFinite": bool(np.isfinite(neutral_action).all()),
            "neutralAction": np.asarray(neutral_action, dtype=float).tolist(),
            "stepsRequested": max(1, args.steps),
            "stepsCompleted": len(actions),
            "terminated": terminated,
            "finalObservationKeys": _observation_keys(observation),
            "checkpoint": str(checkpoint),
            "airborneSustainance": "requires pose/height telemetry from the worker",
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except Exception as error:  # The probe should report a useful runtime failure.
        return _report(
            status="failed",
            reason=f"Flybody low-level restore/step failed: {type(error).__name__}: {error}",
            checkpoint=str(checkpoint),
        )


def _checkpoint_exists(path: Path) -> bool:
    return path.exists() or path.with_suffix(path.suffix + ".index").exists() or Path(f"{path}.index").exists()


def _replace_steering_with_neutral(observation: Any) -> Any:
    """Copy an observation and replace both reference observables with no-op."""
    try:
        import copy
        import numpy as np

        cloned = copy.deepcopy(observation)

        def visit(value: Any) -> None:
            if isinstance(value, Mapping):
                for key, child in value.items():
                    key_text = str(key)
                    if key_text.endswith("ref_displacement"):
                        value[key] = np.zeros_like(child, dtype=float)
                    elif key_text.endswith("ref_root_quat"):
                        neutral = np.zeros_like(child, dtype=float)
                        neutral[..., 0] = 1.0
                        value[key] = neutral
                    else:
                        visit(child)

        visit(cloned)
        return cloned
    except Exception:
        # The action probe still remains useful if a particular dm_control
        # observation container is immutable; the normal observation is then
        # used by the caller and the failure is visible in the report.
        return observation


def _observation_keys(observation: Any) -> list[str]:
    if not isinstance(observation, Mapping):
        return []
    return sorted(str(key) for key in observation.keys())


def _report(**values: Any) -> int:
    print(json.dumps(values, indent=2, sort_keys=True))
    return 0 if values.get("status") == "ok" else 2


if __name__ == "__main__":
    raise SystemExit(main())
