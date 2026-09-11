# DATA REPORT — MaleCNS v1.0 local load

Date: 2026-09-09

The repository now contains the official Janelia/Google MaleCNS v1.0 Feather
files in the ignored `data/raw` directory:

- `body-annotations-male-cns-v1.0-minconf-0.5.feather`
- `body-neurotransmitters-male-cns-v1.0.feather`
- `connectome-weights-male-cns-v1.0-minconf-0.5.feather`

The optional body-stats file is not local. The weighted graph file is the
official `male-cns:v1.0` connectivity file, not the old FlyWire graph.

## Validation output

The validation command loaded:

| Measure | Value |
|---|---:|
| Neurons | 211,577 |
| Weighted edges | 151,856,684 |
| Total synaptic weight | 311,833,243 |
| Sensory neurons | 17,937 |
| Descending neurons | 1,332 |
| Motor neurons | 815 |

Observed predicted-neurotransmitter distribution:

| Prediction | Count |
|---|---:|
| acetylcholine | 95,400 |
| dopamine | 4,447 |
| gaba | 20,348 |
| glutamate | 28,199 |
| histamine | 2,259 |
| octopamine | 125 |
| serotonin | 481 |
| unclear | 35,757 |

Observed canonical side distribution: L 82,991; R 84,829; M 392; unknown
414. Sensory/descending/motor counts use exact MaleCNS superclass/class label
sets; no DN/MN name inference is used.

## Expected but unavailable fields

- `nerve`: the source exposes `entryNerve` and `exitNerve`, which are retained
  separately; there is no single canonical nerve value.
- `hemilineage`: the source exposes `itoleeHl` and `trumanHl`, which are
  retained separately; there is no single canonical hemilineage value.
- `pre_count` and `post_count`: not loaded because the optional body-stats
  Feather is not present.

The source tables contain additional fields such as `rootSide`, `somaSide`,
`instance`, `receptorType`, neuromere, and source-specific identifiers; the
loader retains them. The canonical `side` field coalesces `somaSide` with
`rootSide` only when the former is null, which is important for the sensory
registry.
