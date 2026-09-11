# 🪰 FRUIT FLY CAPITAL

### What happens when a swarm of fruit-fly brains gets control of a crypto wallet?

**We turn the crypto market into an ecosystem—and let biology decide where to go.**

Fruit Fly Capital's multi-agent system is called **NeuroSwarm**. It combines the
official MaleCNS v1.0 connectome, Brian2 neural dynamics, the canonical
TuragaLab/Flybody body, Three.js, The Graph, and a direct on-chain Uniswap boundary.

```text
market data → sensory world → MaleCNS circuits → body movement
             → population behavior → guarded trade intent
```

The flies never receive a token symbol, chart, price recommendation, target
coordinate, or direct command such as “go to TOKEN-X”. Market information is
translated into environmental signals—light, motion, odor, and danger—and is
then sensed through the embodied loop.

## Current reality

The current interactive default is an **8-brain pilot**, not 100 completed
full-CNS simulations. The browser renders ten visible Flybody bodies per
brain by default, so 8 brains produce 80 visible flies. Each numbered primary
agent (`fly-001` through `fly-008`) has its
own Flybody pose, sensor frame, actuator state, and server-side Brian2 runtime
identity/seed. The connectome topology and model parameters are shared as
immutable configuration; membrane state, spikes, history, and RNG state are
not shared. Additional bodies can be enabled as render-only followers: they
share the primary actuator intent with small deterministic spacing and timing
variation, but do not sense, run a brain, or add votes.

The realtime adapter currently runs a documented source-reachable three-hop
MaleCNS circuit of roughly 6,641 neurons and 65,110 retained weighted edges
per runtime. It does not step the full 211,577-neuron, 151,856,684-edge graph for
each fly. The UI therefore separates `AGENTS`, `CNS RUNTIMES`, `CNS ACTIVE`,
`MOVING`, and `DRIVE` instead of implying that neural activity equals movement.

The literal MaleCNS decoder has evidence-constrained turning/flight readouts.
The browser starts in that real `MALECNS` driver: each fly's embodied
eye/antenna/optic-flow/contact observations are encoded, simulated by its
independent Brian2 runtime, decoded, and sent through the shared
`FlyActuators -> FlyBody` interface. It does not receive token coordinates or
issue a hidden “go to coin” command. If the validated pathway is quiet, the
command remains neutral and the UI reports that state.

The product strategy uses eight independent brains and 80 visible bodies by default:

```env
VITE_SWARM_SIZE=8
VITE_BODIES_PER_BRAIN=10
```

`VITE_BODIES_PER_BRAIN` controls render-only followers. Followers never sense,
vote, receive capital, or create trade events.

The canonical rendered Drosophila body is TuragaLab/Flybody's MuJoCo model,
loaded from `flybody/fruitfly/assets/fruitfly.xml` and its referenced OBJ
assets. The browser uses Three.js for visualization; MaleCNS remains the brain
and the current physics-backend boundary is documented in
`docs/FLYBODY_INTEGRATION.md`.

The vendored dependency is Apache-2.0 licensed. Do not replace it with a
random GLTF asset or silently call the placeholder fallback a canonical body.

An optional MuJoCo wrapper loads this exact XML without changing it. On macOS,
use an explicit Python 3.12 interpreter; a global `python` command may not be
installed, and the system `python3` may be too old for this project:

```bash
brew install python@3.12
PYTHON312="$(brew --prefix python@3.12)/bin/python3.12"
"$PYTHON312" -m venv .venv312
./.venv312/bin/python -m pip install -e '.[dev,physics,speed]'
cp .env.example .env
```

The Python brain server and market-report command automatically load this
repository-root `.env` for local development. Explicitly exported shell
variables take precedence. Restart the brain server after changing `.env`.

`malecns.flybody.MuJoCoFlybody` accepts Flybody's native actuator vector and
returns its pose. A FlightCommand-to-native-joint mapping is intentionally not
invented; the browser remains on the existing actuator-compatible adapter
until that mapping is scientifically specified.

## Deployment boundary

The Three.js client can be deployed to Vercel as a Vite site. Set Vercel's
project root to `frontend`, use `npm run build`, and publish `dist`. Commit
both the normal vendored `third_party/flybody/` directory and the
`frontend/public/models/flybody` link; the build now fails if the canonical XML
or any referenced OBJ is absent. Set
`VITE_BRAIN_WS_URL` to a public `wss://` endpoint in the deployed environment;
the local `ws://127.0.0.1:8765` default only works on the developer's machine.

The current `malecns.brain_server` is a standalone, long-running WebSocket
process with an in-memory Brian2 runtime registry. It is not a Vercel Function
entrypoint and should run on a persistent Python host/container. Vercel's
Python runtime is suitable for HTTP Functions, but adapting this stateful brain
server to Vercel would require a Function/WebSocket entrypoint, externalized
runtime state, and a separate capacity plan. Keep Graph and Uniswap credentials
on that server; never expose them as `VITE_` variables.

When DexScreener discovery is enabled, the backend can persist the discovered
market list and locked arena round in Supabase. Run
[`supabase/migrations/001_market_cache.sql`](supabase/migrations/001_market_cache.sql)
once, then set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` on Render along
with `NEUROSWARM_MARKET_DISCOVERY_ENABLED=true`. Names, symbols, image URLs,
links, metrics, and provenance are cached server-side; the service-role key is
never sent to Vercel. See [`supabase/README.md`](supabase/README.md).

## Fund / treasury layer

Fruit Fly Capital includes a safe fund boundary under `contracts/` and
`src/malecns/fund/`. The Foundry vault uses explicit WETH/FFC share accounting
on Robinhood Chain testnet,
authorized external NAV reporting, and asynchronous withdrawals. The Python
ledger and portfolio engine keep book state distinct from on-chain state; the
autonomous wallet runtime supports simulation fills or a separate queued
execution service. See
[docs/FUND_ARCHITECTURE.md](docs/FUND_ARCHITECTURE.md).

For the shared Supabase path, run migrations 004 and 005 from
[`supabase/migrations`](supabase/migrations) in the Supabase SQL editor, then
set `FUND_ADAPTER=supabase` and `FUND_INTENT_QUEUE_BACKEND=supabase` on the
brain service. Every fly BUY/SELL proposal is recorded as an `observed` row;
the amount-bearing netted order is recorded as `pending` for the executor.

### Standalone fly trade runner

To let the flies publish BUY/SELL decisions to a separately run process, set
these values in the server environment:

```env
FUND_ADAPTER=queue
FUND_INTENT_QUEUE_PATH=data/fund/execution-intents.jsonl
```

Start the brain server as usual, then run the executor from the repository
root. It consumes netted intents, resolves the exact chain/address, checks
balances, obtains a route/quote, builds transaction calldata, estimates gas,
and records the result in the shared fund ledger. When `UNISWAP_API_KEY` is
set, it uses the hosted Uniswap Trading API so Robinhood Chain V4 and
multihop routes are available. Without that key it falls back to the direct
JSON-RPC V2/V3 adapter:

```bash
PYTHONPATH=src .venv/bin/python scripts/run_trade_executor.py
```

The default is `prepare`, which prints prepared transactions without signing
or broadcasting. To run the same queue consumer in broadcast mode, configure
the signer in the executor environment and explicitly enable that mode:

```bash
FUND_RUNNER_MODE=broadcast \
FUND_RUNNER_CONFIRM_BROADCAST=true \
PYTHONPATH=src .venv/bin/python scripts/run_trade_executor.py --mode broadcast
```

The runner signs only with `PRIVATE_KEY` from its own process, verifies that it
controls `FUND_WALLET_ADDRESS`, submits the raw transaction, polls the RPC
receipt, and lets the existing receipt/Blockscout layer classify and reconcile
the real hash. Simulation fills never enter the mainnet-executed table. The
Uniswap API key is server-side only and is never sent to the frontend.

For Robinhood testnet use `FUND_CHAIN_ID=46630`,
`FUND_RPC_URL=https://rpc.testnet.chain.robinhood.com`, and the testnet
explorer URL. Direct routing is currently configured for chain 4663; supply
the testnet V2/V3 factory, quoter, router, and WETH addresses through the
`UNISWAP_*` environment variables before preparing testnet swaps.

```bash
PYTHONPATH=src python -m malecns.fund.bootstrap_privy
cd contracts && forge test --offline -vvv
```

No frontend control signs or broadcasts a transaction, and no mainnet
deployment is automated. The deployment script uses the configured real
Robinhood Chain testnet WETH asset; MockUSDC is test-only.

Bootstrap for a biologically grounded MaleCNS *Drosophila* swarm project. The
product is Fruit Fly Capital / NeuroSwarm: biological agents in an onchain
market ecology.

It loads and queries the official Janelia/Google MaleCNS v1.0 dataset
(`male-cns:v1.0`) through either neuPrint or local Apache Feather files and
provides a CPU Brian2 reference LIF model plus conservative sensory/motor
population registries. It does not implement learning, reinforcement
learning, or any direct fly-to-fly neural edge.

## Setup

Use the project environment explicitly (the package requires Python >=3.10):

```bash
brew install python@3.12
PYTHON312="$(brew --prefix python@3.12)/bin/python3.12"
"$PYTHON312" -m venv .venv312
./.venv312/bin/python -m pip install -e '.[dev,physics]'
cp .env.example .env
```

Start the optional brain adapter from the repository root with:

```bash
PYTHONPATH=src ./.venv312/bin/python -m malecns.brain_server --host 127.0.0.1 --port 8765
```

For the live MaleCNS loop, build the small, reproducible runtime cache
from the official local Feather files before starting the adapter:

```bash
./.venv312/bin/malecns-realtime-cache \
  --data-dir data/raw \
  --output-dir data/runtime/malecns-realtime-3hop --path-hops 3
PYTHONPATH=src ./.venv312/bin/python -m malecns.brain_server --host 127.0.0.1 --port 8765
```

The cache retains exact MaleCNS weighted paths from the mapped sensory IDs to
annotated flight-output IDs within a documented three-hop analysis boundary.
It is not a replacement for the full 211,577-neuron/151,856,684-edge source
graph; see [docs/LIVE_CNS_LOOP.md](docs/LIVE_CNS_LOOP.md).

Run the one-fly live smoke test after building the cache:

```bash
MPLCONFIGDIR=/tmp/malecns-mpl PYTHONPATH=src \
  ./.venv312/bin/python experiments/live_malecns_smoke.py
```

This reports actual neutral, lateralized-visual, and odor-only spike/DN
responses. It is a diagnostic result, not a claim that autonomous flight has
already succeeded.

The public neuPrint service requires a token for live queries. Put it in the
environment as `NEUPRINT_TOKEN`; never commit it.

## Official local data

The downloader accepts explicit file keys so the large connectivity table is
never fetched accidentally:

```bash
python -m malecns.download annotations neurotransmitters stats --output-dir data/raw
python -m malecns.download connectivity --output-dir data/raw  # approximately 1.1 GB
```

The loader recognizes the exact v1.0 filenames from the official download page,
and a single clearly named local variant for each file. Annotations and
connectivity are required; neurotransmitter and body-stats files are optional.

Run the validation report after the required files are present:

```bash
malecns-report --data-dir data/raw
```

The report prints loaded neuron and edge counts, total edge weight, observed
neurotransmitter and side distributions, and category counts only when an
exact `class`/`subclass` label is present. It does not infer sensory,
descending, or motor identity from names such as DN/MN.

## Python API

```python
from malecns import load_malecns_tables, query_neurons
from malecns.annotations import incoming_edges, outgoing_edges

neurons, edges = load_malecns_tables("data/raw")
right = query_neurons(neurons, side="right")
dn = query_neurons(neurons, type="DNge104")
outgoing = outgoing_edges(edges, dn["body_id"].tolist())
incoming = incoming_edges(edges, dn["body_id"].tolist())
```

For live access:

```python
from malecns.neuprint_client import MaleCNSClient

client = MaleCNSClient()
neurons = client.query_neurons(type="DNge104")
edges = client.connectivity(body_ids=neurons["body_id"].tolist(), direction="outgoing")
```

## Brian2 reference dynamics

After the complete connectivity Feather is available:

```python
from malecns.brain import BrainSimulation, LIFParameters

brain = BrainSimulation.from_malecns(
    "data/raw",
    parameters=LIFParameters.load("data/parameters/shiu-male-cns-v1.json"),
    seed=7,
)
brain.stimulate(body_ids=[10001], frequency_hz=150.0)
result = brain.run(duration_ms=500.0)
print(result.spikes)
print(result.firing_rates.sort_values("firing_rate_hz", ascending=False).head())
```

The default `unknown_sign="exclude"` policy uses only acetylcholine-positive
and GABA-negative edges. Ambiguous or missing transmitter signs are reported
and excluded from the Brian2 graph; raw edges remain available through the
`ConnectivityMatrix`. No edge-weight normalization is performed.

The reference demo is:

```bash
python experiments/connectome_propagation_demo.py
```

## Controlled 3-D flight experiments

The headless controlled-run harness is:

```bash
MPLCONFIGDIR=/tmp/malecns-mpl MPLBACKEND=Agg PYTHONPATH=src \
  python experiments/autonomous_flight_experiments.py \
  --output-dir results/single_fly_3d --seed 20260909
```

It runs visual stabilization, four visual target directions, odor-only flight,
and 60 seconds of free flight, writing compressed JSONL, Parquet telemetry,
plots, a trajectory CSV, configuration, and a numerical report. The current
rate-provider boundary is explicit: until a live Brian2 provider is attached,
the `malecns_connected` condition has neutral decoded motor output and is not
an autonomous MaleCNS result. See [results/single_fly_3d/REPORT.md](results/single_fly_3d/REPORT.md).

## Sensory/motor mapping status

Annotation-grounded sensory and descending registries are implemented in
`src/malecns/sensory/registry.py` and `src/malecns/motor/registry.py`.
The reproducible left/right visual audit is:

```bash
MPLBACKEND=Agg PYTHONPATH=src python experiments/lateralized_sensory_asymmetry.py
```

It retains official `R8d` → three-hop → `DNa01`/`DNa02`/`DNp09`/`DNp28`
paths, reports exact body IDs and spikes, and writes a plot under
`results/figures/`. It does not assign movement gains. Stop and dedicated
walking-state registries remain empty when MaleCNS v1.0 does not expose those
exact labels. See [docs/SENSORY_MOTOR_MAPPING.md](docs/SENSORY_MOTOR_MAPPING.md)
and [docs/MODEL_ASSUMPTIONS.md](docs/MODEL_ASSUMPTIONS.md).

## 3D fly world

The `frontend/` directory contains the Three.js/Vite embodied-world prototype.
It uses a 2 m x 1 m x 2 m arena, a 120 Hz rigid-body step, mouse orbit camera
controls, and a WebSocket actuator boundary for the Python MaleCNS process.
See [frontend/README.md](frontend/README.md) for launch commands.
`FlightMotorDecoder` provides the documented, rate-only
MaleCNS-to-actuator boundary for exact annotated flight populations. With the
realtime cache present, the adapter owns one persistent Brian2 runtime per
connected `fly-NNN` ID and returns live spike counts/rates; without it, the
adapter stays neutral and reports that source explicitly. The public application
does not substitute manual or preview movement.
See [docs/LIVE_CNS_LOOP.md](docs/LIVE_CNS_LOOP.md) and
[docs/FLIGHT_MOTOR_MAPPING.md](docs/FLIGHT_MOTOR_MAPPING.md) for evidence and
limitations.
The embodied sensor contract is documented in
[docs/SENSORY_WORLD.md](docs/SENSORY_WORLD.md).

The Flybody integration boundary is the upstream 7D
`ref_displacement + ref_root_quat` steering block when its low-level
flight-imitation checkpoint is installed; the WPG frequency scalar is not the
navigation interface. See [docs/FLYBODY_FLIGHT_AUDIT.md](docs/FLYBODY_FLIGHT_AUDIT.md).

## Onchain market discovery and habitat data

The optional live feed is deliberately layered:

```text
CoinMarketCap ranked context + DexScreener pairs -> MarketUniverse -> eligibility -> locked MarketRound
            -> up to 100 physical market habitats
            -> 12 deep Ethereum/Uniswap observer configs
GraphProvider -> RawTokenObservation -> TokenSignalEngine -> Signal[]
              -> HabitatEncoder -> physical habitat fields -> fly sensors
```

CoinMarketCap is an optional broad ranked-asset context provider. When
`CMC_API_KEY` is configured, the top listings seed exact chain/address
lookups and enrich matching candidates with rank, supply, seven-day change,
volume change, and dominance. It never creates a habitat from a symbol alone.
DexScreener still supplies the real pair, liquidity, and tradability context
through its documented public API. It decides which markets enter the tracked market world, not which market is
attractive to a fly: selection scores, rankings, bullish labels, expected
returns, coordinates, and trading recommendations never enter the habitat or
brain path. The default round exposes up to 100 tracked markets and locks
them for ten minutes; up to 12 receive deep Graph observation while the rest
receive lightweight DexScreener-derived state. See
[docs/MARKET_SIGNAL_ARCHITECTURE.md](docs/MARKET_SIGNAL_ARCHITECTURE.md).

Enable it in the Python server environment:

```bash
NEUROSWARM_MARKET_DISCOVERY_ENABLED=true
NEUROSWARM_MARKET_CHAINS=robinhood
NEUROSWARM_MARKET_DEX_IDS=
# Comma-separated Robinhood token contract addresses; see .env.example for the
# current project seed list from the DexScreener Robinhood universe.
NEUROSWARM_MARKET_DISCOVERY_TOKEN_ADDRESSES=<comma-separated-addresses>
NEUROSWARM_MARKET_CORE_TARGET=100
NEUROSWARM_MARKET_WORLD_CAPACITY=100
NEUROSWARM_MARKET_DEEP_OBSERVER_COUNT=12
NEUROSWARM_MARKET_STALE_CACHE_MAX_SECONDS=86400
CMC_API_KEY=
CMC_LISTINGS_LIMIT=100
CMC_ALLOWED_CHAINS=robinhood
```

The latest/recent profile feeds can seed discovery when they contain the
configured chain. For a stable project-specific universe, provide explicit
comma-separated token addresses (or `chainId:address` entries). The public
configuration is Robinhood-only; leaving `NEUROSWARM_MARKET_DEX_IDS` blank
accepts the native DEX venues returned by DexScreener on Robinhood.
CoinMarketCap is a global ranked table, so its seed input is separately
restricted by `CMC_ALLOWED_CHAINS` and defaults to Robinhood only; CMC rows
from other networks are ignored.

On Render, set these same values in the service environment and redeploy:
`NEUROSWARM_MARKET_DISCOVERY_ENABLED=true`,
`NEUROSWARM_MARKET_CHAINS=robinhood`,
`NEUROSWARM_MARKET_CORE_TARGET=100`,
`NEUROSWARM_MARKET_WORLD_CAPACITY=100`, and leave
`NEUROSWARM_MARKET_DEX_IDS` empty. The capacity is an upper bound: the
service shows only real candidates returned by the providers, so it will not
invent 95 markets if discovery currently returns five.
report can be inspected with:

```bash
PYTHONPATH=src python -m malecns.market_discovery_cli
```

If DexScreener is reachable but no compatible Graph observer is configured,
the report still shows the selected market round while the physical habitat
feed remains empty. That is intentional: no swap data is fabricated.

`TokenState` keeps market, flow, liquidity, holders, security, social, and
lore as separate domains. Each derived signal carries its value, normalized
value, importance, valence, confidence, freshness, source, and observation
time. DexScreener also preserves optional USD price, market cap, FDV, pair age,
LP base/quote reserves, transaction totals, market-cap/LP, FDV/LP,
volume/market-cap, and volume/LP ratios. Missing
holder, security, social, and lore data remains explicitly unavailable. See
[docs/MARKET_SIGNAL_ARCHITECTURE.md](docs/MARKET_SIGNAL_ARCHITECTURE.md) for
metric definitions, provenance, and the planned provider boundaries.

## NeuroSwarm population pilot

The current milestone is an eight-brain population pilot rendered as eight
canonical Flybody bodies by default. Each primary has its own body, sensor frame,
actuator state, unique `fly-NNN` brain ID, and server-side RNG stream. Four
render-only followers can be attached to each primary with
`VITE_BODIES_PER_BRAIN`; they do not sense, create brain runtimes, or add
consensus votes. Live mode dynamically creates one
`TokenHabitat` per market ID up to the world capacity. Each habitat exposes
only physical proxies—visual brightness/motion, attractive odor, and aversive
danger. The local test scenarios can still create eight fixture habitats; those
fixtures do not call APIs or represent real tokens. Switch among
The normal scene uses live discovered market habitats; fixture scenarios are
reserved for developer tests and are not part of the product surface.

## Swarm behavior and fund boundary

The browser sends throttled behavior telemetry for the eight primary bodies
to the Python server. `malecns.swarm.SwarmObserver` measures per-agent,
per-habitat visits, approach episodes, departures, dwell, repeat visits,
distance history, contact, congregation, and persistence. The
`TemporalConsensusEngine` converts those time-dependent summaries into
evidence-bearing habitat convictions; `PortfolioAllocator` converts qualified
convictions into capped target weights; and `RiskGuard` checks the fund-policy
limits. The server returns this as a `swarm_update` message.

This is a guarded direct-wallet boundary. It does not count render-only
followers as votes, it does not send token recommendations into MaleCNS, and
it does not use the saved vault contract. Uniswap quotes and calldata are
validated by the mainnet preparation adapter; the external authorization
boundary owns signing and broadcasting. Approvals are never broadcast
implicitly. See
[docs/SWARM_INTELLIGENCE.md](docs/SWARM_INTELLIGENCE.md).

Run the deterministic headless sensory audit with:

```bash
MPLBACKEND=Agg PYTHONPATH=src python experiments/token_habitat_experiments.py \
  --output-dir results/token_habitats --seed 20260909
```

It writes `summary.json`, `telemetry.parquet`, `trajectory.csv`, a sensory
exposure plot, and a report. The live browser experiment is evidence of the
embodied input-to-Brian2-to-decoder path when the cache and adapter are
running, but it is not evidence that the MaleCNS has learned or chosen
token-directed behavior. See [docs/SWARM_ARCHITECTURE.md](docs/SWARM_ARCHITECTURE.md)
for the per-fly causal chain and runtime-capacity interpretation.

## Why the flies do not go to the boxes yet

The browser scene contains only token habitats: each colored coin pile is a
physical market city with its own market/sensory state. The frontend has no
decorative target props and does not substitute them for markets.

The movement path is intentionally:

```text
habitat light / motion / odor
        ↓
embodied FlySensors
        ↓
exact MaleCNS sensory IDs
        ↓
Brian2 spikes and annotated descending activity
        ↓
FlightMotorDecoder
        ↓
FlyActuators → FlyBody
```

There is currently no validated ordinary-forward-flight output from the
selected realtime MaleCNS path. When its thrust readout is quiet, the correct
result is that the fly stays put. Adding a direct “go to the box/coin” force
would make the demo look active but would invalidate the experiment. See
[`docs/FLIGHT_MOTOR_MAPPING.md`](docs/FLIGHT_MOTOR_MAPPING.md) and
[`docs/SWARM_ARCHITECTURE.md`](docs/SWARM_ARCHITECTURE.md).

## Next steps

1. Validate a scientifically defensible MaleCNS flight-output path, including
   sustained lift/forward movement and stable turning, first for one fly.
2. Replace synthetic habitats with configured token observations from The
   Graph, preserving signal provenance and unavailable fields.
3. Benchmark 16, 32, and then 100 independent runtimes. Add scheduling or
   vectorized/compiled execution before making 100-agent realtime claims.
4. Connect the implemented behavior intentions to token routes and portfolio
   holdings only after RiskGuard validation. The intentions are observations,
   not automatic trades.
5. Add fly-to-fly perception through the world, then tune the guarded wallet
   execution policy and token approval workflow.

## Scientific integrity

This project does not train the connectome with gradient descent or
reinforcement learning, add Fly A → Fly B neural edges, or silently modify
synaptic weights to obtain a desired behavior. Observed MaleCNS data, published
model assumptions, and project assumptions are separated in
[`docs/MODEL_ASSUMPTIONS.md`](docs/MODEL_ASSUMPTIONS.md). The project is an
experimental research/hackathon prototype, not financial advice or a validated
trading strategy.
