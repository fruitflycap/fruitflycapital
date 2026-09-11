# NeuroSwarm: what the sixteen pilot brains are doing

The browser simulation currently contains sixteen real pilot brains, numbered
`fly-001` through `fly-016`. The browser renders one primary and four
render-only followers per brain, for eighty visible Flybody bodies. Followers
share only presentation intent; they do not sense, run Brian2, or vote. The
letters A and B are not agent identities in this architecture. This is
intentionally a verification population, not the final 100-brain deployment.

## One fly's complete state

Every `FlyAgent` owns these independent objects:

| State | Code | Meaning |
|---|---|---|
| body pose | `FlyBody.position`, `quaternion` | SI-metre position and orientation |
| body motion | `FlyBody.velocity`, `angularVelocity` | integrated translational and angular motion |
| sensors | `FlySensors` | observations sampled from that fly's own pose |
| actuators | `FlyActuators` | the latest command applied to that fly only |
| controller | `MaleCNSController` | Every primary body is controlled by its own MaleCNS runtime |
| brain identity | `fly-NNN` | the key for that fly's persistent Python runtime and output cache |
| RNG stream | server-side stable seed | deterministic but independent neural randomness |

The camera selector only changes which agent is inspected. It does not make a
selected fly smarter, give it a target, or share its brain with another fly.

## How to read the population counters

The HUD keeps population existence separate from neural activity:

| Counter | Meaning |
|---|---|
| `AGENTS` | Physical Flybody agents created in the browser |
| `VISUAL FLIES` | Primary bodies plus render-only followers shown in the scene |
| `CNS RUNTIMES` | Distinct `fly-NNN` runtime outputs received from the adapter |
| `CNS ACTIVE` | Those runtimes that reported at least one spike in the latest returned window |
| `CNS DRIVE` | MaleCNS agents whose decoded command is currently non-neutral |
| `MALECNS DRIVE` | Primary agents with a non-neutral command from the live decoder |

Thus `CNS RUNTIMES 16/16` does not imply that all sixteen flies are moving, and
`CNS ACTIVE 0/16` is a meaningful neural result rather than a rendering error.

## What can move one fly

The movement path is deliberately one-way through the sensorimotor interface:

```text
coin geometry + odor field + physical boundaries
              |
              v
fly-NNN FlySensors at its current pose
              |
              |  eye summaries, odor, motion, contact
              v
MaleCNSSensoryEncoder
              |
              |  exact annotated body IDs, currently R8d and ORN_DA1
              v
fly-NNN persistent Brian2 MaleCNS runtime
              |
              |  cached MaleCNS weighted edges and LIF spike windows
              v
FlightMotorDecoder
              |
              |  selected annotated descending-neuron rates
              v
fly-NNN FlyActuators
              |
              |  thrust, yaw, pitch, roll
              v
fly-NNN FlyBody rigid-body integrator
              |
              v
new pose -> new sensors -> next loop
```

There is no `targetPosition`, no token-coordinate message, and no direct
fly-to-fly neural connection. A coin's synthetic state changes brightness,
visual motion, attractive odor, or aversive odor. Those fields can change what
a fly senses; they do not directly select a coin or add a steering force.

## Why the literal MaleCNS mode may not go anywhere

“MaleCNS mode” does not mean “autopilot.” The decoded flight command is zero
when the selected descending populations have no spikes. The current bounded
realtime graph has already shown this distinction:

- sensory stimulation can produce upstream activity;
- odor can produce a turning readout;
- the selected DNg02 wing-amplitude population has not produced sustained
  thrust in the smoke experiment;
- therefore sustained autonomous flight and token-directed navigation are not
  yet demonstrated.

The UI's causal panel reports this as `DN active` or `DN quiet`, then shows the
actual command received by the body. If it says `waiting for this fly's brain
output`, the Python adapter has not returned a window for that ID yet. If it
says `DN quiet` and command values are zero, the brain ran and returned no
selected motor activity.

The browser uses the literal `MALECNS` driver for every primary body. It reads
only local eye, antenna, optic-flow, and contact observations and sends commands
through the same `FlyActuators -> FlyBody` boundary. If the live provider or
decoded path is quiet, commands remain neutral and the diagnostic UI exposes
that fact. The public application has no manual or preview driver.

## What “independent brains” means operationally

The browser sends a compact sensor frame for every distinct `fly-NNN` ID. The
Python adapter creates one `LiveMaleCNSRuntime` per ID, with the same official
MaleCNS topology and separate membrane state, spike history, and deterministic
RNG stream. The initial requests are staggered to avoid a single connection
burst. The browser also applies one-in-flight-frame backpressure per fly, so a
slow Brian2 window cannot create an unbounded queue of stale sensor frames.

The realtime cache is an explicit performance boundary: approximately 6,641
neurons and 65,110 retained weighted edges per runtime before transmitter-sign
filtering. One laptop may not sustain many full Brian2 copies at interactive
latency. The status therefore distinguishes:

```text
16/16 independent browser bodies
N/16 brain outputs received so far
```

If `N` remains low, that is runtime capacity/queueing—not evidence that the
other bodies are secretly sharing a brain. The correct scaling work is a
fleet scheduler or compiled/vectorized Brian2-compatible backend. Replacing
the missing brains with a hand-written “go to coin” rule would invalidate the
experiment.

## Debugging one selected fly

1. Enable the developer-only diagnostic surface, then select any `#NNN` in the inspection control.
2. Click `FOCUS`, or use camera `2` for follow mode.
3. Press `I` to open the causal panel.
4. Read the chain from left/right luminance and odor, through encoded ID
   counts and DN activity, to the command and body velocity.
5. Compare the returned MaleCNS command against an `OFF`/no-runtime test
   outside the product surface. The public application always leaves control
   with MaleCNS.

The flight log downloads the selected fly's sensor, stimulation, spike/DN,
command, pose, and velocity history so a visible movement can be traced back
to the exact input frame that preceded it.
