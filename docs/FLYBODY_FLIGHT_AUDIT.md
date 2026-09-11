# Flybody flight-control audit

## Decision

NeuroSwarm navigation stays in the MaleCNS path. Flybody is the low-level
motor execution layer: it may generate wingbeats, stabilize the body, and
convert a steering reference into joint actions. It must never receive a
token ID, market score, habitat ranking, target coordinate, or portfolio
state.

The implemented boundary is `MaleCNSFlightAdapter` in
`src/malecns/motor/flight_adapter.py`:

```text
FlySensors -> MaleCNS -> documented descending readouts
          -> MaleCNSFlightAdapter -> bounded 7D steering reference
          -> frozen Flybody flight-imitation policy (when installed)
          -> WPG / wing joints -> MuJoCo pose
```

The browser-compatible scalar fields remain in telemetry during the migration,
but they are compatibility fields. They are not the upstream high-level
interface.

## What the upstream code actually does

The vendored source was audited at the current repository revision. The
relevant components are:

| Component | Finding |
| --- | --- |
| `flybody/agents/network_factory_vis.py` | `TwoLevelController` replaces the low-level observation block named `walker/ref_displacement` + `walker/ref_root_quat` with its steering output. With one current reference, this is 7 values. |
| `flybody/tasks/base.py` | `ref_displacement` is a future root-position difference transformed into the fly's egocentric frame. `ref_root_quat` is the reference root orientation expressed relative to the current root orientation. |
| `flybody/tasks/flight_imitation.py` | The task adds those two observables, while its one user action is separately used to modulate WPG frequency. That scalar is not navigation. |
| `flybody/tasks/pattern_generators.py` | WPG creates the continuous wing pattern. The default base frequency is 218 Hz, with six wing-joint outputs (three per wing). |
| `flybody/fly_envs.py` | The stock `flight_imitation` default uses `future_steps=5`; a 7D steering input therefore requires an explicitly constructed `future_steps=0` low-level environment. |

## Exact 7D semantics

For the V1 contract (`future_steps=0`):

```text
[ dx, dy, dz, qw, qx, qy, qz ]
```

### `walker/ref_displacement`

The upstream code computes:

```text
reference_root_position - current_fly_root_position
then transform into the current fly's egocentric frame
```

It is a relative displacement, not a world-space target and not a velocity.
The Flybody model uses centimetre-scale CGS units: the source documents
trajectory speed in cm/s and terminal height in cm. The project therefore
serializes this field as `refDisplacementCm` and keeps browser world metres
separate from the native Flybody contract.

### `walker/ref_root_quat`

The upstream code computes the relative orientation with
`get_dquat_local(current_root_quat, reference_root_quat)`. It is a unit
quaternion in `[w, x, y, z]` order, expressed in the current fly-local frame.
It is not Euler yaw/pitch/roll. A neutral reference is exactly:

```text
[ 0, 0, 0, 1, 0, 0, 0 ]
```

For `future_steps > 0`, the block is repeated for each reference frame and
its dimension is `7 * (future_steps + 1)`. The adapter is explicitly the
one-current-reference V1 contract.

## How the original high-level controller constructs references

The upstream vision controller uses a visual/task high-level MLP. Its output
is initialized close to a no-op ballpark of zero displacement plus identity
quaternion, then inserted into the low-level observation at the two reference
observables. The frozen low-level policy receives the resulting observation
and emits native actions.

NeuroSwarm deliberately removes that upstream navigation decision. The
MaleCNS adapter now supplies the same observation block from neural readouts:

| Reference component | V1 source | Status |
| --- | --- | --- |
| forward `dx` | normalized MaleCNS forward/wing/takeoff readout | project calibration assumption, bounded to 0.5 cm by default |
| lateral `dy` | none | fixed at zero until a documented lateral mapping exists |
| vertical `dz` | none | fixed at zero; no fabricated vertical DN mapping |
| heading quaternion | normalized bilateral yaw readout | project calibration assumption, bounded to +/-0.35 rad |
| roll/pitch quaternion components | none | fixed at zero |

The adapter does not know which habitat is attractive and does not receive a
habitat coordinate. Habitat odor and visual signals influence the neural
readouts upstream; only the resulting, documented neural output crosses this
boundary.

## Update frequencies

The upstream constants are:

```text
MuJoCo physics timestep:  5e-5 s  (20 kHz)
Flybody control timestep: 2e-4 s  (5 kHz)
```

The WPG is updated inside the flight task at the control timestep. The
upstream `TwoLevelController` does not define a separate navigation cadence;
it is called by the policy loop. NeuroSwarm's realtime MaleCNS window is much
slower and therefore supplies a zero-order-held steering reference between
neural updates. That hold interval is a project runtime choice, not an
upstream biological or Flybody constant.

## Checkpoint and runtime status

No trained Flybody checkpoint is included in this repository. The upstream
download script exposes public Janelia Figshare archives, including
`controller-reuse-checkpoints` and `trained-policies`. The controller-reuse
archive is the first candidate for the low-level policy because the upstream
two-level factory restores a low-level DMPO policy from a checkpoint.

The exact checkpoint member/version still has to be resolved by downloading
and listing that archive, then constructing a matching
`flight_imitation(future_steps=0)` environment spec. Until that probe passes,
the browser must not claim that it is running the frozen pretrained policy.

The native low-level policy also has not yet been proven to sustain airborne
flight from a neutral steering reference. A neutral steering reference means
“track the current pose/orientation”; it does not itself assert lift. This
must be tested from Flybody's initialized airborne pose with the WPG active,
using the exact restored policy and recording height, velocity, joint action,
and termination.

## Neural versus low-level responsibility

```text
NEURAL / MALECNS
  sensory encoding
  neural spikes
  descending locomotor readouts
  navigation and trajectory modulation

FLYBODY LOW LEVEL
  steering-reference tracking
  wingbeat pattern generation
  wing-joint actuation
  lift and aerodynamic stabilization
  MuJoCo integration
```

The vision/high-level RL controller may be studied to understand the
interface, but it must not choose NeuroSwarm targets. A single restored
low-level policy may be shared across 16 independent CNS agents only if each
agent keeps independent CNS state, steering hold state, WPG phase, and
MuJoCo physics state.

## Required real-policy probe

Before claiming biological flight control, run one canonical fly first, then
4, 8, and 16:

1. Build the low-level environment with `future_steps=0`.
2. Restore the public controller-reuse checkpoint with the matching network
   factory.
3. Feed a neutral 7D reference from an initialized airborne pose.
4. Feed a bounded forward reference and then a bounded yaw reference.
5. Record `maleCnsCommand`, `steeringReference7d`,
   `flybodyJointAction`, `physicalVelocity`, and `physicalPosition`.
6. Repeat with fixed sensory input and different neural input, proving that
   only the MaleCNS-derived reference changes navigation.

If the exact checkpoint cannot run in the deployment environment, use the
existing WPG/simplified trajectory renderer only as an explicitly labelled
diagnostic fallback. It must not be presented as the pretrained low-level
policy.

## Sources

- Upstream two-level controller: `third_party/flybody/flybody/agents/network_factory_vis.py`
- Upstream reference observables: `third_party/flybody/flybody/tasks/base.py`
- Upstream flight task and timestep configuration:
  `third_party/flybody/flybody/tasks/flight_imitation.py` and
  `third_party/flybody/flybody/tasks/constants.py`
- Public data/checkpoint URLs:
  `third_party/flybody/flybody/download_data.py`
