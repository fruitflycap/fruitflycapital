# Token habitat experiment report

Seed: `20260909`  
Duration per scenario: `10.0` s  
Scenarios: `A_OFF`, `B_DIFFERENT`, `C_SWAPPED`

This run audits the embodied sensory fields only. The browser-side MaleCNS
adapter has no live Brian2 rate provider, so it supplies a neutral decoded
motor command and no movement behavior is claimed. `time_near`, entries, and
exits are therefore static-position baselines; they become behavioral metrics
once a validated neural provider is attached.

The OFF condition removes attractive odor, danger, brightness, and particle
activity. DIFFERENT places the three synthetic states at their default sites.
SWAPPED rotates the state/site assignment. Token state names are mock labels,
not live market data or real token identity.

The exact MaleCNS IDs stimulated by the current visual/olfactory encoder are
preserved in `summary.json` and `telemetry.parquet`. Aversive danger is shown
as a world/debug field but is explicitly listed as unimplemented in the
MaleCNS sensory adapter; it is not silently mapped to a receptor population.
