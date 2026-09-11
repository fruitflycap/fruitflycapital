# Model assumptions and scope boundary

This milestone separates evidence from assumptions.

## A. Observed biological/connectomic data

- The structural source is the official MaleCNS v1.0 snapshot (`male-cns:v1.0`).
- Official body annotation, neurotransmitter prediction, body statistics, and
  weighted connectivity Feather files are supported.
- Body IDs are preserved as integer IDs. Edge weights are preserved as
  non-negative numeric values; they are not transformed into neural weights.
- Source-specific columns are retained after canonical fields are added.

## B. Published/historical model assumptions inspected

The referenced historical Brian2 model (`philshiu/Drosophila_brain_model`) uses
the following values in `model.py`: resting/reset potential `-52 mV`, spike
threshold `-45 mV`, membrane time scale `20 ms`, synaptic decay `5 ms`,
refractory period `2.2 ms`, delay `1.8 ms`, and per-synapse scale `0.275 mV`.
Its examples use external Poisson stimulation, and its connectivity input is
FlyWire v630/v783 data. These values are not used by this data bootstrap and
must be re-evaluated before any future simulation.

## C. Assumptions introduced by this project

- Canonical names are aliases for source column names; an unmapped field is
  left nullable and reported missing.
- Local file discovery accepts only the official filename patterns and does
  not choose arbitrary Feather files.
- Sensory, descending, and motor counts use exact, case-insensitive equality in
  `class`/`subclass`, plus the explicit MaleCNS `superclass` labels documented
  in `validation.py` (for example `vnc_sensory`, `descending_neuron`, and
  `vnc_motor`). Names such as `DN`/`MN` are not silently interpreted as
  categories.
- This project will instantiate independent fly copies later. No code in this
  milestone creates an edge between copies.

## LIF parameter provenance

Every simulator parameter is assigned one provenance class:

| Parameter or behavior | Provenance | Implementation |
|---|---|---|
| `v_0=-52 mV`, `v_reset=-52 mV`, `v_threshold=-45 mV` | `PUBLISHED_SHIU` | copied from `model.py` |
| membrane time `20 ms` | `PUBLISHED_SHIU` | copied from `model.py` |
| synaptic decay `5 ms` | `PUBLISHED_SHIU` | copied from `model.py` |
| refractory period `2.2 ms` | `PUBLISHED_SHIU` | copied from `model.py` |
| synaptic delay `1.8 ms` | `PUBLISHED_SHIU` | copied from `model.py` |
| per-synapse scale `0.275 mV` | `PUBLISHED_SHIU` | raw MaleCNS count × this scale |
| Poisson default `150 Hz` and second rate `0 Hz` | `PUBLISHED_SHIU` | stimulation defaults |
| Poisson scale `250` | `PUBLISHED_SHIU` | input weight is `0.275 mV × 250` |
| `method="linear"` and alpha-like conductance equations | `PUBLISHED_SHIU` | same equation structure |
| timestep `0.1 ms` | `OUR_ASSUMPTION` | made explicit; original relied on Brian2 defaultclock |
| MaleCNS body IDs, direction, and raw edge counts | `MALECNS_DATA` | loaded without graph normalization |
| `acetylcholine` → positive and `gaba` → negative | `OUR_ASSUMPTION` | conservative transmitter-class sign mapping |
| unknown/ambiguous transmitter → excluded by default | `OUR_ASSUMPTION` | avoids silently treating all edges as excitatory |
| visual-class histamine → negative | `OUR_ASSUMPTION` | restricted to visual presynaptic cells; supported by photoreceptor histamine-gated chloride-channel evidence |

The implemented equations are:

```text
dv/dt = (v_0 - v + g) / t_mbr
dg/dt = -g / tau
```

Brian2 executes the reset as `v = v_rst; g = 0*mV`. The published source also
contains `w = 0` in its reset string even though no `w` state is declared; the
undefined assignment is omitted as an implementation compatibility correction
with no dynamical variable to reset.

MaleCNS neurotransmitter predictions are neuron-level rather than
receptor-specific. Therefore glutamate, dopamine, octopamine, serotonin,
non-visual histamine, `unclear`, and missing predictions are not assigned a
sign by default. `unknown_sign="positive"` exists only as an explicit opt-in
and is never the default. Visual-class histamine is the one restricted
exception used by the sensory experiment.

## Embodied sensory-world assumptions

| Parameter or behavior | Provenance | Implementation |
|---|---|---|
| 5 x 2 directional samples per eye | `OUR_ASSUMPTION` | Low-resolution ray lattice used instead of thousands of cameras; sampled at 20 Hz in the browser |
| Material color to luminance and fixed ambient contrast | `OUR_ASSUMPTION` | Rendering approximation, not a photoreceptor model |
| Optic-flow proxy from tangential velocity, hit distance, and angular velocity | `OUR_ASSUMPTION` | No optic-flow neurons are directly identified by this layer |
| Gaussian odor field, sigma 0.28 m, bounded deterministic noise | `OUR_ASSUMPTION` | Local environmental field; airflow is not implemented |
| `150 Hz * bounded sensory signal` rate encoder | `OUR_ASSUMPTION` | Applies only to exact mapped `R8d` and `ORN_DA1` body IDs; luminance/center odor are the current scalar inputs |
| `R8d`, `ORN_DA1`, and `JO-B1_b` body IDs | `MALECNS_DATA` | Loaded from the generated official-ID mapping CSV |
| Contact, wind, and gravity-to-CNS stimulation | `OUR_ASSUMPTION` / unavailable | Exposed as debug observables; left unmapped rather than guessed |

Body motion, contact, and environmental coupling are now implemented at the
world/sensor boundary. Full sensory transduction, receptor-level modeling,
validated mechanosensory mappings, and two-fly experiments remain deferred.

## Market habitat signal provenance

The market layer is environmental scaffolding for the browser world, not a
replacement for MaleCNS data and not a direct actuator path.

| Element | Provenance | Current treatment |
|---|---|---|
| Pool token identities, swap timestamps, pool amount deltas, amount USD, and TVL returned by the configured Graph subgraph | observed provider data, not `MALECNS_DATA` | Preserved as `RawTokenObservation`/`RawSwapObservation` with `the-graph` provenance; not biological data |
| 5m/15m/1h windows, token-relative buy/sell classification, flow imbalance, transaction velocity/acceleration, liquidity delta, and volume/liquidity ratio | `OUR_ASSUMPTION` | Explicit signal-engine derivations documented in `MARKET_SIGNAL_ARCHITECTURE.md` |
| USD volume, count, liquidity, velocity, acceleration, and ratio tanh scales | `OUR_ASSUMPTION` | Bounded normalization constants; not learned and not copied from Shiu or MaleCNS |
| `importance`, `valence`, `confidence`, and `freshness` fields | `OUR_ASSUMPTION` | Explicit metadata; volume remains valence-neutral, flow imbalance carries direction |
| `holders`, `security`, `social`, and `lore` unavailable status | `OUR_ASSUMPTION` | No fabricated values until a provider supplies those domains |
| Physical brightness, motion, odor, particle activity, chaos, and danger proxy | `OUR_ASSUMPTION` | `HabitatEncoder` environmental proxies only; never a direct yaw/thrust command |

## Live Brian2 provider boundary

| Element | Provenance | Current treatment |
|---|---|---|
| Sensory IDs, flight-output IDs, edge direction, and raw weights in the cache | `MALECNS_DATA` | Copied from the official v1.0 Feather files |
| Three-hop source-reachable path to annotated flight outputs | `OUR_ASSUMPTION` | Explicit interactive analysis boundary recorded in `manifest.json`; not the full connectome |
| Persistent per-neuron PoissonGroup stream | `PUBLISHED_SHIU` adaptation | One reusable input neuron and one-to-one synapse per cached neuron; required because Brian2 `PoissonInput.rate` is construction-time/read-only |
| Per-fly deterministic seed offset | `OUR_ASSUMPTION` | Base `MALECNS_REALTIME_SEED` plus a stable fly-ID offset; no fly-to-fly neural edge |
| Browser window duration | `OUR_ASSUMPTION` | `MALECNS_REALTIME_WINDOW_MS`, default 50 ms |

The browser's developer-only manual controller is an explicit `OUR_ASSUMPTION`, not
published biology: it is a keyboard-only body diagnostic through the shared
actuator interface. The default `MALECNS` path receives no token coordinates or
hand-authored navigation command; a quiet decoder therefore remains a valid
neutral result.

The live provider returns the actual spike counts/rates from the cached Brian2
window. It does not guarantee a nonzero motor command: in the current direct
check, turning populations spiked while the selected DNg02 wing-amplitude
population remained quiet, so the decoder returned yaw but zero thrust. That
is an observed result of the current boundary, not a parameter adjustment.

## Flight motor decoder assumptions

| Element | Provenance | Current treatment |
|---|---|---|
| DNg02 body IDs and wing-amplitude role | `MALECNS_DATA` + `PUBLISHED_BIOLOGY` | Exact annotated IDs; used as an abstract nonnegative thrust drive |
| DNa15/DNb01/DNp03 body IDs and saccade role | `MALECNS_DATA` + `PUBLISHED_BIOLOGY` | Exact annotated IDs; left/right mean-rate difference is the yaw readout |
| DNp01 body IDs and escape/takeoff role | `MALECNS_DATA` + `PUBLISHED_BIOLOGY` | Exact annotated IDs; bounded additional takeoff drive |
| DNp06 and DNp07/DNp10 | `MALECNS_DATA` + `PUBLISHED_BIOLOGY` | Registered and logged; no independent torque/landing gain assigned |
| 20 Hz reference rate, population means, yaw sign, thrust formula | `OUR_ASSUMPTION` | Explicit normalization in `FlightMotorDecoder`; not a synaptic-weight modification |
| pitch, roll, stopping, vertical thrust, ordinary forward flight | `OUR_ASSUMPTION` / unavailable | No fabricated mapping; pitch/roll are zero, vertical actuator is hover-neutral, stop/forward gains deferred |
| world coordinates in decoder | design constraint | Decoder receives only rate/count mappings; target coordinates and privileged geometry are unavailable |

See [`FLIGHT_MOTOR_MAPPING.md`](FLIGHT_MOTOR_MAPPING.md) for exact body IDs,
literature evidence, and the live-provider boundary.

## Flybody steering-reference assumptions

The upstream Flybody `TwoLevelController` uses a steering observation block,
not only the WPG frequency action. NeuroSwarm's V1 adapter supplies the
7-dimensional `future_steps=0` form:

```text
[ref_displacement_cm_x, ref_displacement_cm_y, ref_displacement_cm_z,
 ref_root_quat_w, ref_root_quat_x, ref_root_quat_y, ref_root_quat_z]
```

The egocentric displacement and relative `[w, x, y, z]` quaternion semantics
are `FLYBODY_UPSTREAM`; the forward scale (0.5 cm), yaw scale (+/-0.35 rad),
and zero vertical/lateral/pitch/roll mapping are `OUR_ASSUMPTION` calibration
choices. These values are not claimed to be MaleCNS dimensions. See
[`FLYBODY_FLIGHT_AUDIT.md`](FLYBODY_FLIGHT_AUDIT.md).
