# Fruit Fly Capital / NeuroSwarm frontend

This is a small Three.js/Vite client for the Fruit Fly Capital embodied market
ecology prototype. The product surface is NeuroSwarm; the technical stack is
MaleCNS v1.0, Flybody, Three.js, and The Graph.
Physical positions are in metres and the world is 2 m x 1 m x 2 m. The visible
fly body is loaded from the canonical TuragaLab/Flybody XML and referenced OBJ
meshes; see `../docs/FLYBODY_INTEGRATION.md` for provenance and scale
conversion. The body integrator advances at 120 Hz; rendering is decoupled
with `requestAnimationFrame`.

## Run

From this directory:

```bash
npm install
npm run dev
```

On macOS, use an explicit Python 3.12 environment from the repository root.
Do not use the global `python` command, and do not use the system `python3` if
it is older than 3.10:

```bash
brew install python@3.12
PYTHON312="$(brew --prefix python@3.12)/bin/python3.12"
"$PYTHON312" -m venv .venv312
./.venv312/bin/python -m pip install -e '.[dev,physics,speed]'
PYTHONPATH=src ./.venv312/bin/python -m malecns.brain_server --host 127.0.0.1 --port 8765
```

The Vite script uses `--force` so stale optimized-dependency responses do not
leave the browser showing `504 Outdated Optimize Dep`. Restart the dev server
after changing dependencies.

In another terminal, the optional Python protocol adapter can be started from
the repository root:

```bash
PYTHONPATH=src ./.venv312/bin/python -m malecns.brain_server --host 127.0.0.1 --port 8765
```

Before starting the adapter, build the realtime cache from the official local
Feather files in the repository root:

```bash
./.venv312/bin/malecns-realtime-cache \
  --data-dir data/raw \
  --output-dir data/runtime/malecns-realtime-3hop --path-hops 3
```

The adapter encodes each embodied sensor frame into exact MaleCNS sensory IDs,
advances one persistent Brian2 runtime per connected fly ID, and decodes that
window's `spikeRates`/`spikeCounts` into the normalized `FlightCommand` through
`FlightMotorDecoder`. The browser starts eight independent agents named
`fly-001` through `fly-008`; there is no special A/B pair. Every browser agent
uses the MaleCNS controller. If the cache is absent, the command remains
neutral and the diagnostic UI reports the missing source instead of fabricating
spikes. See `../docs/SWARM_ARCHITECTURE.md` and `../docs/LIVE_CNS_LOOP.md`.

The browser sends each numbered fly's compact brain frame at 2 Hz by default.
Set
`VITE_BRAIN_UPDATE_HZ` when testing a different cadence; this is a transport
cadence choice, not a neural-parameter change.

All browser agents use the decoded Brian2 command. If the live runtime is
unavailable or the selected MaleCNS output populations are quiet, the command
remains neutral and the UI reports that state. There is no manual or synthetic
preview driver in the product surface.

The current default is eight independent brains and 80 visible bodies:
each brain owns one primary body plus render-only followers. Set
`VITE_BODIES_PER_BRAIN` to change that presentation count. Followers do
not create brain runtimes, sense the world, or add consensus votes. To stage a
larger brain population experiment, set `VITE_SWARM_SIZE` to a value from 1 to
100. This changes the number of browser agents and brain IDs requested; it does
not make 100 full MaleCNS simulations fit within the current realtime CPU
budget. The eight-brain pilot preserves the previous 6.25% maximum capital
allocation per brain, leaving 50% of deployable capital unallocated until the
population is expanded. Visible follower bodies do
not create 1% voting units; that requires one hundred independently running CNS
agents, which still needs a runtime benchmark before becoming the default.

## Controls

The product surface is autonomous and mouse-first. In the default free camera,
left-drag rotates, right-drag pans, and the mouse wheel zooms toward the cursor.
The browser does not expose a manual flight or preview switch.

The renderer reconstructs Flybody's articulated abdomen, thorax, head, eyes,
antennae, halteres, legs, and wing assemblies while retaining `FlyBody`,
`FlySensors`, and `FlyActuators`. The current browser physics adapter is still
the existing rigid-body path until an optional MuJoCo pose server is attached.

The arena is intentionally restrained: an invisible bounded flight volume, a
readable city floor, and up to 100 differentiated market habitats. Each habitat is
presented as a compact food, rot, trash, or market-smell source derived from
its encoded signals. Unrelated props are not rendered. The eight primary
agents and their render-only followers all use the same canonical Flybody
XML/OBJ source. Habitat particles use a pooled GPU buffer.

The fly is rendered at an explicit 12x inspection magnification because its
physical body is millimetre-scale. This does not alter positions, collisions,
sensors, or telemetry.

At startup, all eight agents begin in a deterministic distant launch
formation. Each primary body's compact sensor summary goes to that fly's own
brain stream, and the live token habitat fields become the fly's visual and
olfactory environment. The selected causal panel exposes the local sensor
values, exact encoded `R8d`/`ORN_DA1` counts, neural telemetry, and the command
returned by that fly's MaleCNS runtime. Live market discovery is the only
normal habitat source; local fixtures are reserved for developer tests.
It also shows the SENSORY -> CNS -> descending activity -> FLIGHT COMMAND
pipeline and a downloadable JSON flight log. The sensor contract
intentionally excludes food, target, and obstacle coordinates. Sensor details
and provenance are documented in `../docs/SENSORY_WORLD.md`.
