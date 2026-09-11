# Live MaleCNS swarm loop

This is the embodied integration path for the sixteen-fly browser population
pilot. It makes
the data path real for each numbered fly without claiming that a desired
behavior has emerged.

```text
Three.js FlySensors (fly-001 ... fly-016)
  -> that fly's R8d / ORN_DA1 stimulation entries
  -> that fly's persistent Brian2 MaleCNS runtime
  -> actual cached-window spike counts and rates
  -> FlightMotorDecoder selected DN rates
  -> FlyActuators
  -> FlyBody rigid-body physics
  -> changed pose and new sensor frame
```

There is no A/B comparison body. The frontend owns sixteen independent
`FlyAgent`s, each with its own body state, sensors, actuator state, brain ID,
and deterministic server-side RNG stream. The camera and causal panel inspect
one selected ID at a time; selection does not alter the simulation.

## Literal neural driver

The browser uses the literal `MALECNS` driver for every agent. Each body's
local eye, antenna-odor, optic-flow, and contact observations are encoded into
the documented sensory populations, stepped by its own Brian2 runtime, decoded
from selected MaleCNS output populations, and sent through
`FlyActuators -> FlyBody`. The driver does not receive token coordinates. If
the runtime is unavailable or the selected path is quiet, the command remains
neutral and the diagnostic UI reports that state; no manual or synthetic flight
policy is substituted.

## Starting it

From the repository root, with the official local Feather files present:

```bash
./.venv312/bin/malecns-realtime-cache \
  --data-dir data/raw \
  --output-dir data/runtime/malecns-realtime-3hop --path-hops 3
./.venv312/bin/python -m malecns.brain_server --host 127.0.0.1 --port 8765
```

In another terminal:

```bash
cd frontend
npm run dev
```

If the cache is absent, the server reports `decoder-without-live-provider` and
returns neutral CNS commands. The product does not silently replace the brain
with a hand-written navigation rule.

## What is observed versus assumed

Observed and preserved:

- official MaleCNS v1.0 body IDs and annotations;
- official weighted edge direction and raw synapse weights;
- exact mapped R8d, ORN_DA1, JO-B1_b, and flight-output populations;
- actual Brian2 spike counts/rates from each fixed runtime window.

Published methodology retained:

- Shiu-style LIF equation and parameters;
- external Poisson drive semantics;
- Brian2 state evolution and synaptic delay/decay model.

Our explicit boundary assumptions:

- only the source-reachable three-hop path from mapped sensory IDs to
  annotated flight outputs is stepped interactively for each connected ID;
- visual mean luminance and center odor concentration are converted to
  `150 Hz * bounded signal` input rates;
- optic flow, aversive odor, wind, gravity, and contact remain observed but
  unencoded until a defensible MaleCNS mapping is established;
- decoder normalization and the yaw sign remain project-level actuator
  conventions;
- the default browser brain cadence is 2 Hz and initial requests are staggered
  across the sixteen IDs to avoid a startup burst;
- the browser permits only one in-flight sensor frame per fly, preventing
  stale brain-input backlog when Brian2 is slower than the requested cadence.

## Runtime capacity is part of the result

One default cached Brian2 runtime is approximately 6,641 neurons and 65,110
retained weighted edges before transmitter-sign filtering. One runtime is
created per distinct `fly-NNN` ID by the Python adapter. Therefore each pilot
brain is an independent state and runtime identity, but the population is
still a substantial CPU/RAM workload on a laptop. The UI reports live
brain outputs received as `N/16`; it must not be read as proof that all sixteen
Brian2 runtimes have already completed their first window. If the machine
cannot sustain the full fleet, the next engineering step is a fleet scheduler
or a compiled/vectorized backend—not a scripted movement replacement.

The cache is not a replacement for the full official graph. The local source
contains 211,577 annotated neurons and 151,856,684 weighted edges. The default
cache manifest records its 6,641 nodes, 65,110 retained edges, source/target
IDs, raw total weight, and three-hop boundary. An optional four-hop cache can
be built for pathway inspection, but is not the Render/free-tier default.

## Current scientific result

The reproducible smoke run is `experiments/live_malecns_smoke.py` and writes
`results/live_malecns_smoke.json`. With seed 17 and four 50 ms windows:

- neutral produced zero spikes and a neutral command;
- visual-left and visual-right produced upstream activity, but no selected
  flight-DN activity reached the decoder in this bounded graph;
- odor-only produced nonzero turning-DN activity and a nonzero yaw command;
- DNg02 wing-amplitude activity was zero in all four cases, so decoded thrust
  was zero.

This is a genuine partial success and a genuine flight failure: the live
sensor → Brian2 → DN → decoder path works, but sustained autonomous flight is
not demonstrated. The next investigation is whether a scientifically
defensible longer MaleCNS path or additional annotated flight population can
be justified. No motor gain, lift command, or target-following rule should be
added merely to make the fly move.
