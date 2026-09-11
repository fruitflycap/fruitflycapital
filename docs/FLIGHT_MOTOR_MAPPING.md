# MaleCNS flight motor mapping

This document defines the evidence-constrained boundary between MaleCNS
activity and the browser's abstract flight actuator interface. The mapping
never reads a world coordinate, target position, or object identity. It
consumes recent firing rates or spike counts keyed by preserved MaleCNS body
IDs.

## Structural populations selected from MaleCNS v1.0

The IDs below were obtained from the local official annotation file
`body-annotations-male-cns-v1.0-minconf-0.5.feather`. The canonical type
identifier is `mancType` when present; a displayed `type` such as `DNg02_a`
is retained as an additional source annotation.

| Decoder population | MaleCNS annotation and body IDs | Biological evidence | Confidence | Simulator use |
|---|---|---|---|---|
| `wing_amplitude` | `mancType=DNg02`; 29 IDs: 17331, 18183, 19773, 20289, 20849, 20962, 21122, 22393, 22404, 22462, 23411, 25357, 25852, 26049, 26079, 28905, 30228, 31641, 33333, 33424, 35988, 37135, 177685, 225466, 262979, 295340, 302599, 516667, 525126; 15 L / 14 R | DNg02 is a descending population associated with visual-flight control and wingbeat-amplitude coding in the flight motor system. See [Namiki et al., 2022](https://pmc.ncbi.nlm.nih.gov/articles/PMC9206711/). | HIGH for the published wing-amplitude role; MEDIUM for this abstract-thrust adaptation | Mean rate is used as a nonnegative `thrust` drive. This is an actuator abstraction, not a claim that DNg02 directly equals Newtons or forward velocity. |
| `saccade_left` / `saccade_right` | `mancType` in {`DNa15`, `DNb01`, `DNp03`}; 6 IDs: 10654, 10752, 10759, 10837, 10884, 10989. Left/right subsets are derived from the official `side` annotation. | DNa15/DNb01 participate in rapid turning/saccade circuits; DNp03 is a flight saccade/looming-related descending pathway. See [Muijres et al., 2014](https://pmc.ncbi.nlm.nih.gov/articles/PMC6309624/), [Hampel et al., 2017](https://pubmed.ncbi.nlm.nih.gov/28178529/), and [flight saccade pathway work](https://pmc.ncbi.nlm.nih.gov/articles/PMC12977095/). | MEDIUM | The left/right rate difference provides the signed `yaw` drive after explicit normalization. The sign convention is a project convention, not an added biological label. |
| `escape_takeoff` | `mancType=DNp01`; 2 IDs: 10001, 10010 | Giant-fiber/escape pathways are associated with rapid takeoff and escape initiation. See [Tanouye and Wyman, 1980](https://pubmed.ncbi.nlm.nih.gov/18203989/) and [Holmes et al., 2006](https://pubmed.ncbi.nlm.nih.gov/17851667/). | HIGH for escape initiation; LOW for ordinary voluntary flight | Provides a bounded additional thrust drive. It is not interpreted as a general “fly forward” command. |
| `evasive_turn` | `mancType=DNp06`; 2 IDs: 10228, 10584 | DNp06 is reported in evasive flight maneuver circuitry. See [Henriques et al., 2023](https://www.nature.com/articles/s41467-023-42864-5). | MEDIUM | Registered and logged for analysis, but not currently given an independent torque gain. |
| `landing` | `mancType` in {`DNp07`, `DNp10`}; 4 IDs: 10425, 10433, 11513, 11704 | DNp07 and DNp10 are associated with landing and leg-extension control. See [Ache et al., 2019](https://pubmed.ncbi.nlm.nih.gov/31182867/). | HIGH for landing/leg extension; LOW for the current flight actuator interface | Logged as a downstream population. No landing torque or brake is asserted until a validated actuator-level mapping is available. |

Existing project readout candidates are retained for telemetry only:

- `DNa01`/`DNa02`: left readout IDs 10442, 523769; right readout IDs 10360,
  10760. These are not currently the yaw source because the flight decoder
  uses the more directly flight-saccade-labelled populations above.
- `DNp09`/`DNp28`: IDs 10783, 11177, 14501, 519268. These remain forward
  locomotor readout candidates from the earlier mapping, but are not assigned
  a thrust gain in this flight decoder.

## What is and is not decoded

The decoder's reference rate is `20 Hz`. For selected populations, it computes
the arithmetic mean of nonnegative recent rates, preserving missing IDs as
zero activity. The current equations are:

```text
yaw    = clip((mean(saccade_right) - mean(saccade_left)) / 20 Hz, -1, +1)
thrust = clip(max(mean(DNg02), mean(DNp01)) / 20 Hz, 0, +1)
pitch  = 0
roll   = 0
```

The `20 Hz` reference, the left/right sign, and using a population mean are
`OUR_ASSUMPTION`. They are documented normalization choices, not published
synaptic weights. No MaleCNS edge, neuron ID, or connection strength is
changed. The browser then converts the normalized command to forces and
torques using the existing rigid-body physics.

When the optional Flybody low-level worker is connected, the same normalized
neural command is also passed through `MaleCNSFlightAdapter` as a bounded
7-dimensional current steering reference:

```text
[forward displacement cm, 0, 0, relative yaw quaternion w, x, y, z]
```

This is a calibration boundary, not a claim that a MaleCNS firing rate has a
published centimetre/radian conversion. The low-level policy owns wingbeat
generation, joint actuation, lift, and stabilization. It does not select a
market or habitat. Exact semantics and the required `future_steps=0`
environment are documented in [FLYBODY_FLIGHT_AUDIT.md](FLYBODY_FLIGHT_AUDIT.md).

The following mappings are deliberately unimplemented:

| Output | Current status | Reason |
|---|---|---|
| pitch | zero command | No validated one-to-one MaleCNS population-to-pitch mapping selected. |
| roll | zero command | No validated one-to-one MaleCNS population-to-roll mapping selected. |
| stopping/braking | no proxy | No exact `FG`/`BB`/`BRK` population is asserted from the current annotation audit. |
| vertical flight / hover | fixed actuator neutral `0.5` | No selected vertical-thrust mapping; this avoids inventing gravity compensation biology. |
| ordinary forward flight | no decoder gain | `DNp09`/`DNp28` remain telemetry candidates only. |
| landing physics | no automatic landing command | DNp07/DNp10 evidence is for landing/leg extension, not a validated abstract torque mapping. |

## Required sensorimotor path

The intended data path is:

```text
3D world
  -> embodied eye / odor / contact observations
  -> exact MaleCNS sensory stimulation entries
  -> MaleCNS spike-rate provider
  -> exact descending-population rate window
  -> FlightMotorDecoder
  -> FlightActuators
  -> FlyBody forces and torques
  -> changed pose and changed sensory observations
```

The WebSocket protocol carries the encoded stimulation and recent
`spikeRates`/`spikeCounts` keyed by body ID. The adapter can invoke a
persistent Brian2 runtime over the explicit cached three-hop MaleCNS path.
When the cache is unavailable it returns zero decoded flight drive and marks
the source as `decoder-without-live-provider` rather than fabricating neural
activity. The live path is therefore a working sensor-to-spike-rate-to-decoder
integration, but not yet a claim of successful autonomous flight: the current
selected output populations do not provide validated pitch/roll/ordinary
forward mappings, and the first direct run produced yaw activity but no
DNg02 wing-amplitude spikes.

## Source and provenance notes

- `MALECNS_DATA`: official v1.0 body IDs, `mancType`, side, superclass, and
  preserved connectivity. The official dataset is documented at
  [MaleCNS](https://male-cns.janelia.org/) and its
  [download page](https://male-cns.janelia.org/download/).
- `PUBLISHED_BIOLOGY`: functional roles reported in the linked flight and
  landing studies. Literature labels do not overwrite MaleCNS annotations.
- `OUR_ASSUMPTION`: selecting a subset as telemetry/readout populations,
  rate averaging, 20 Hz normalization, yaw sign, and the abstract force/torque
  interface.

This mapping is intentionally conservative: a population can be biologically
relevant and still remain telemetry-only until its relation to a particular
actuator is supported by evidence.
