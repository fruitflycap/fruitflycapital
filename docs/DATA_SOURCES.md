# Data sources

## Primary source: MaleCNS v1.0

- Official project: <https://male-cns.janelia.org/>
- Official download page: <https://male-cns.janelia.org/download/>
- neuPrint server: <https://neuprint.janelia.org/>
- neuPrint dataset: `male-cns:v1.0`
- Bulk storage prefix: `gs://flyem-male-cns/v1.0/connectome-data/flat-connectome/`
- License: CC-BY, as stated on the official download page.

Files used by this milestone:

| File | Role | Required |
|---|---|---|
| `body-annotations-male-cns-v1.0-minconf-0.5.feather` | curated body annotations: classes, types, sides, etc. | yes |
| `body-neurotransmitters-male-cns-v1.0.feather` | aggregate neuron-level neurotransmitter predictions | no |
| `body-stats-male-cns-v1.0-minconf-0.5.feather` | body summary statistics including synapse counts | no |
| `connectome-weights-male-cns-v1.0-minconf-0.5.feather` | full segment-to-segment weighted graph | yes |

The official page describes the connectivity table as the full connection
graph and the weight as segment-to-segment connection strength. The loader
keeps additional columns from all source files rather than discarding
biologically meaningful fields.

The synapse partner and synapse point tables are intentionally not required for
this milestone. They are much larger and are not needed for the unified edge
table, whose minimum contract is source body ID, target body ID, and weight.

## Historical model inspected, not adopted

`philshiu/Drosophila_brain_model` was inspected for model provenance:

- repository: <https://github.com/philshiu/Drosophila_brain_model>
- source model: `model.py`
- example: `example.ipynb`
- environment: `environment_full.yml`

That project uses FlyWire v630/v783 CSV/Parquet materializations, not MaleCNS
v1.0. Its Brian2 choices are documented in
[MODEL_ASSUMPTIONS.md](MODEL_ASSUMPTIONS.md) as historical context only.
