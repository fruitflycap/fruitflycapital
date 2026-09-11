# MaleCNS sensory and locomotor mapping

This document records the first annotation/evidence pass. It is intentionally
not a movement controller. The registry code only returns body IDs selected by
MaleCNS annotations and published biological evidence; it does not assign
movement gains or choose neurons by simulated activity.

## Evidence boundary

| Layer | Meaning in this document |
|---|---|
| `MALECNS_DATA` | Exact fields/body IDs in the official `male-cns:v1.0` annotations or weighted graph. |
| `PUBLISHED_BIOLOGY` | Functional evidence from Drosophila circuit papers; exact cell-type mapping to MaleCNS is treated separately. |
| `OUR_ASSUMPTION` | A transparent software choice required to expose a population or run a bounded experiment. |

The complete body-ID inventory for the named populations below is in
[`data/mappings/malecns_sensory_motor_ids.csv`](../data/mappings/malecns_sensory_motor_ids.csv).
The canonical `side` field uses `somaSide` and falls back to `rootSide` only
when `somaSide` is null. No side is inferred from a type or instance name.

## Sensory populations

| Population / body IDs | MaleCNS annotations | Biological function | Source/evidence | Confidence | Simulator use |
|---|---|---|---|---|---|
| Visual `R8d`: 76 cells; L=35, R=41. Exact IDs are in the inventory CSV. | `type=R8d`, `class=visual`, `superclass=ol_sensory`, side from `rootSide`; predicted transmitter: histamine (57), unclear (19). | Inner photoreceptor visual input; R8 is a real retinal input class, not a downstream visual projection class. | `MALECNS_DATA`; photoreceptor histamine identity and release are supported by [Sarthy 1991](https://onlinelibrary.wiley.com/doi/full/10.1111/j.1471-4159.1991.tb06378.x) and visual histamine receptor work ([Tango-Trace](https://pmc.ncbi.nlm.nih.gov/articles/PMC4126867/)). | HIGH for sensory identity; MEDIUM for any specific locomotor role. | `visual_left_ids()` / `visual_right_ids()`; the lateralized experiment uses this exact type. |
| Olfactory `ORN_DA1`: 204 cells; L=51, R=105, unknown=48. Exact IDs are in the inventory CSV. | `type=ORN_DA1`, `class=olfactory`, `superclass=cb_sensory`, `entryNerve=AN`; side uses `rootSide`, with unknown-side cells excluded from side-specific calls. | Antennal olfactory receptor-neuron input associated with one antennal-lobe glomerular type. | `MALECNS_DATA`; the MaleCNS source describes complete olfactory pathways and glomerular sensory types. | HIGH for olfactory sensory identity; MEDIUM for downstream behavioral interpretation. | `olfactory_ids(..., type_name="ORN_DA1")`; suitable for future pheromone/odor transduction without inventing CNS edges. |
| Auditory/mechanosensory `JO-B1_b`: 12 cells; L=7, R=5. Exact IDs are in the inventory CSV. | `type=JO-B1_b`, `class=mechanosensory`, `subclass=auditory` for 11 rows and `wind_gravity` for one, `superclass=cb_sensory`; side from `rootSide`. | Johnston's-organ mechanosensory input; the exact subclass is retained because not every JO row has the same functional label. | `MALECNS_DATA`; mechanosensory class/subclass. FeCO/JO function is corroborating biology, not a replacement for MaleCNS labels. | HIGH for mechanosensory identity; MEDIUM for interpreting this exact type as an auditory channel. | `mechanosensory_ids(..., type_name="JO-B1_b")`; generic tactile/proprioceptive families are also available by exact class/subclass. |

The broader official annotation counts are 6,091 `visual`, 2,639
`olfactory`, and 5,745 rows in the three explicitly mechanosensory classes
(`mechanosensory`, `mechanosensory_tactile`, and
`mechanosensory_proprioceptive`). The helpers do not include `unknown_sensory`,
gustatory, thermo-, or hygro-sensory cells when the caller asks for these
modalities.

## Locomotor output/readout populations

| Population / body IDs | MaleCNS annotations | Biological function | Source/evidence | Confidence | Simulator use |
|---|---|---|---|---|---|
| Turn candidates: `DNa01` = L 10442, R 10760; `DNa02` = L 523769, R 10360. | Exact types; all `superclass=descending_neuron`; `class` is null; `somaSide` is L/R. | DNa01/DNa02 are descending steering neurons. Their left/right side is used as an ipsilateral output/readout grouping. | MaleCNS type/side are `MALECNS_DATA`; [DNa01/DNa02 steering study](https://pmc.ncbi.nlm.nih.gov/articles/PMC12279373/) reports bilateral DNa02 differences related to rotational velocity and ipsilateral steering. | MEDIUM: strong published functional evidence, but the cited perturbation work is not itself a MaleCNS-v1.0 simulation. | `turn_left_output_ids()` and `turn_right_output_ids()` expose IDs only. No steering gain or spike-to-angle transform is implemented. |
| Forward candidates: `DNp09` = L 10783, R 11177; `DNp28` = L 519268, R 14501. | Exact types; all `superclass=descending_neuron`; side is L/R. | DNp09/P9 has forward-turning evidence; DNp28 is the MaleCNS exact type used as the cautious BPN/straight-forward candidate. | MaleCNS identity is `MALECNS_DATA`; forward walking evidence comes from [P9/BPN work](https://pmc.ncbi.nlm.nih.gov/articles/PMC9435592/). Exact MaleCNS equivalence for the functional labels is not asserted beyond the type-name mapping. | MEDIUM for DNp09; SPECULATIVE-to-MEDIUM for DNp28. | `forward_output_ids()` returns exact existing types, so downstream locomotion can be inspected before any movement mapping is chosen. |
| Stop: no body IDs returned. | No exact `FG`, `BB`, or `BRK` rows occur in the official annotation file. | Published halt/walk-OFF/brake neurons are not identifiable from the current MaleCNS v1.0 type table by exact names. | `MALECNS_DATA` negative finding; the [halting study](https://pmc.ncbi.nlm.nih.gov/articles/PMC11446846/) is supporting biology from another connectome/context. | UNAVAILABLE; no proxy is silently substituted. | `stop_output_ids()` returns `[]` by default. |
| Walking state: no body IDs returned. | MaleCNS has no dedicated exact `walking_state` annotation field/population in the loaded schema. | A walking state is a behavioral variable, not automatically a command neuron. | `MALECNS_DATA` schema finding. | UNAVAILABLE. | `walking_state_ids()` returns `[]`; DNa/DNp outputs remain readouts, not a fabricated state label. |

The dataset contains 1,314 rows with `superclass=descending_neuron` (plus the
two `descending_neuron_tbc` rows counted by the registry when present). The
registry requires that superclass for output candidates; names beginning with
`DN` alone are not sufficient.

## Left/right graph experiment

Command:

```bash
MPLBACKEND=Agg PYTHONPATH=src python experiments/lateralized_sensory_asymmetry.py
```

The experiment loads the official 151,856,684-edge weighted Feather and
retains only exact three-hop paths from `R8d` L/R populations to
`DNa01`/`DNa02`/`DNp09`/`DNp28`. Reverse reachability is only a computational
filter; retained edge weights remain official values. Results were run with
Shiu's LIF parameters, 150 Hz Poisson input, 500 ms duration, seed 17, and the
current transmitter-sign policy.

| Measure | Left stimulus | Right stimulus |
|---|---:|---:|
| Selected `R8d` sources | 35 | 41 |
| First-layer nodes | 154 | 197 |
| Second-layer nodes | 144 | 252 |
| Edges into target DN types | 201 | 331 |
| Stimulus-source spikes | 2,619 | 3,058 |
| First-layer spikes | 0 | 0 |
| Second-layer spikes | 0 | 0 |
| Target DN spikes | 0 | 0 |

The bounded union has 792 neurons and 2,061 official edges. 1,535 edges are
usable after sign handling: ACh-positive, GABA-negative, and the restricted
visual-photoreceptor-histamine negative adaptation documented in
`MODEL_ASSUMPTIONS.md`. The other 526 remain excluded.

Conclusion: bilateral structural reachability is present and not identical in
edge count, but functional left/right asymmetry does **not** survive as output
spiking in this first reference run. This is a failure to establish a motor
signal, not evidence of symmetry. The immediate cause is that the selected
R8d cells are histaminergic/unclear; under the evidence-based visual
histamine-negative rule they drive inhibition, while no layer-one cell reaches
threshold from rest. The plot therefore shows source spikes and an empty
descending raster. No positive fallback or movement gain was used to make the
result look successful.

Machine-readable results are in
[`results/lateralized_visual_asymmetry.json`](../results/lateralized_visual_asymmetry.json),
with the plot at
[`results/figures/lateralized_visual_asymmetry.png`](../results/figures/lateralized_visual_asymmetry.png).

## Next scientific check before movement

The next step should be a transmitter/receptor-aware visual pathway audit: map
the relevant MaleCNS postsynaptic receptor annotations, if available, and test
whether the selected R8d paths need additional visual cotransmission or
intermediate neurons beyond the three-hop boundary. Only after that audit
should an output be connected to a locomotor plant, and any such connection
must remain a documented interpretation layer rather than a new neural edge.
