# Fruit Fly Capital / NeuroSwarm — project status

Updated: 2026-09-10

This document separates what is implemented from what is demonstrated. A
moving fly in the browser is not automatically evidence that the MaleCNS is
driving it, so the UI and this report keep those claims separate.

## What exists now

### Biological agents

- The structural source is the official MaleCNS v1.0 dataset, with the
  published Shiu-style LIF reference adapted to the available MaleCNS graph.
- The browser creates 16 primary agents by default: `fly-001` through
  `fly-016`.
- Each primary has its own body state, sensors, actuator state, controller,
  brain ID, trajectory, and server-side runtime key.
- Each primary has four render-only followers by default. The visual population
  is therefore 80 Flybody meshes, but the scientific population is 16 CNS
  agents. Followers do not sense, run Brian2, vote, or create trades.
- The strategy population is fixed at 16 independent brains. The optional
  extra bodies are render-only followers and are not strategy agents.

### Neural runtime

- Python exposes one persistent realtime runtime per `fly-NNN` over WebSocket.
- The interactive runtime currently uses a bounded three-hop MaleCNS subgraph,
  approximately 6,641 neurons and 65,110 weighted edges per runtime, rather
  than the complete CNS graph. This is an explicit performance boundary.
- The browser keeps a developer-only **NEURAL TRACE** panel available for
  inspection. It shows
  the exact output origin, recent spike-window activity, selected descending
  activity, and the decoded actuator command.
- The canonical proof label is `LIVE BRIAN2 → DECODER`; no synthetic preview
  driver is part of the application.
- The current MaleCNS path has not established sustained, validated ordinary
  flight output. A neutral command from the autonomous brain path is therefore a real result,
  not a rendering failure. The application does not substitute a synthetic
  movement driver while this biological gap remains.

### Body and world

- The renderer targets TuragaLab Flybody's canonical XML/OBJ body hierarchy.
- This checkout contains the upstream Flybody XML and its 85 referenced OBJ
  meshes under `third_party/flybody`; the frontend prebuild script copies them
  into a real browser-facing directory and verifies every referenced mesh.
- The room has an explicit 2 m × 2 m × 1 m physical volume, a full-screen
  presentation floor, the supplied street-city GLB surrounding the arena, up
  to 128 dynamically instantiated token habitats, simple odor fields, visual
  sampling, contact sampling, and pooled habitat particles. The default camera
  is the user-controlled free street view, framed around the city floor.
- Each habitat is a compact semantic smell source: food, rot, trash, or market
  crate. Live habitats show food, bananas, rot, trash cans/bags, or crates
  instead of abstract floating signal columns. The category is a deterministic
  visual metaphor derived from encoded activity/liquidity/risk; it is not a
  direct navigation rule. Brightness, motion, odor, risk, and particles come
  from the provider-neutral `TokenState`/signal model or the documented
  fixture. Live labels include the token symbol and full coin name where the
  provider supplies both.

### Market and fund boundary

- The Graph and DexScreener are market-data providers; they do not directly
  steer a fly or choose a trade.
- DexScreener discovery has an optional Supabase REST cache. It persists
  normalized candidates, names, symbols, image URLs, links, pair metrics, and
  provenance, plus the locked arena round. The active round can be loaded
  after a backend restart instead of querying discovery immediately.
- The schema is in `supabase/migrations/001_market_cache.sql`; setup is in
  `supabase/README.md`. Writes require the server-only service-role key, which
  is never sent to the browser.
- The provider-neutral path is raw observation → normalized signals → habitat
  encoder → sensory exposure → CNS/runtime → swarm observations.
- The swarm layer records visits, approaches, departures, dwell, persistence,
  and congregation before producing a temporal conviction proposal.
- The fund layer contains a retained inactive Foundry vault, an append-only
  SQLite ledger, the autonomous 16-fly runtime, risk gates, wallet balance
  discovery, and Uniswap quote/calldata preparation. The direct strategy
  wallet is the only execution-path account.
- Simulation fills automatically for demos. Mainnet mode stops after approval,
  quote, calldata, gas, and nonce preparation; no signer or broadcaster is
  reached by the strategy runtime.

## How to verify that the brain is guiding a fly

Use one selected primary agent and enable the developer-only diagnostic surface.

| Evidence | What it proves | What it does not prove |
|---|---|---|
| `LIVE BRIAN2 → DECODER` | The latest command came from the live Brian2 adapter source | That the biological pathway is complete or validated |
| Nonzero `SPIKES` in NEURAL TRACE | A returned MaleCNS window contained spikes | That those spikes caused the body command |
| Nonzero `DN PEAK` | A selected descending population was active | That it is a validated forward-flight pathway |
| `COMMAND` and body velocity change after the returned window | Timing consistency between neural output and motion | Causal proof by itself |
| Same seed, `MALECNS` versus `OFF` | A controlled ablation comparison | A successful result if both remain neutral |
| Downloaded selected-fly log | A replayable chain of sensors → IDs → spikes/DN → command → pose | That missing data should be filled with guesses |

The strongest practical audit is a source-ablation test:

1. Run the same seed with the live MaleCNS path and an isolated no-runtime control test.
2. Record sensor frames, stimulation body IDs, spike counts/rates, DN rates,
   commands, and pose for each run.
3. Confirm the MaleCNS run has a source beginning with
   `brian2-malecns-v1-realtime-` (normally `...-3hop`).
4. Compare the command and trajectory only after aligning the returned brain
   timestamps. A neutral trajectory is not evidence of successful flight.

## What is still missing

1. A validated sustained MaleCNS sensory-to-flight/VNC pathway that produces
   lift, forward flight, and stable turning from validated MaleCNS outputs.
2. Full-connectome realtime scheduling or a compiled/vectorized backend for
   scaling toward 100 independent brains.
3. A deployed runtime asset report confirming that Vercel serves the vendored
  canonical Flybody XML and all referenced OBJ meshes after the asset commit.
4. The Supabase migration run and a production check that the first market
  round survives a backend restart; local environment variables alone do not
  prove database connectivity.
5. A persistent production database and authenticated backend deployment for
  fund ledger/NAV data.
6. Configure the deployed transparent proxy's ProxyAdmin owner, Privy
  wallet/policy, and a human-approved live execution run. Quote/calldata is
  not a filled trade.
7. More market providers and rolling signal windows in production, with clear
  provenance and freshness handling.
8. Fly-to-fly sensory coupling through the environment, social experiments,
  and statistically meaningful swarm evaluations.

## Highest-value improvements

- First, finish the one-fly neural audit and publish the failed cases as well
  as successful ones.
- Second, add a replayable experiment runner so a sensor frame and brain output
  can be inspected without relying on a live browser session.
- Third, benchmark 16, 32, and 100 runtime schedules before choosing the final
  independent-brain count.
- Fourth, deploy and verify the canonical Flybody assets after committing the
  build script and `third_party/flybody` source. The browser-facing directory
  is generated and intentionally is not a symlink.
- Fifth, run the Supabase migration and confirm cached candidates survive a
  backend restart.
- Sixth, make swarm observations durable before enabling
  any live fund execution.
- Seventh, move the ProxyAdmin owner to a multisig or timelock before holding
  meaningful funds; upgrade authority is custody-critical.

## Good next demo features

- Click a habitat to show its signal provenance and freshness.
- Show a faint causal trail from the selected primary body to its five-body
  visual cohort, while counting the cohort as one CNS vote.
- Add experiment replay: same seed, same habitats, three driver modes,
  synchronized side-by-side traces.
- Add a “why this market?” panel that shows temporal visits/dwell/conviction,
  never a one-frame fly count.
- Add a visible safety state: `SIMULATION`, `QUOTE ONLY`, or `LIVE TESTNET`.

## Reproducible checks

```bash
PYTHONPATH=src ./.venv/bin/python -m pytest -q
cd frontend && npm run check && npm run build
cd ../contracts && forge test --offline -vvv
```

## Git/deployment note for the Flybody asset

The old `frontend/public/models/flybody` directory symlink caused Git's
“beyond a symbolic link” error when a path such as
`frontend/public/models/flybody/README.txt` was staged. That symlink has been
removed. The checked-in source remains under `third_party/flybody`, and the
frontend `prebuild` script copies only the XML and referenced OBJ meshes into
the ignored browser-facing directory:

```bash
git add frontend/scripts/prepare-flybody-assets.mjs third_party/flybody
```

Vercel rebuilds the real browser asset directory from those sources, so a
nested `README.txt` under `frontend/public/models/flybody` is neither needed
nor staged.
