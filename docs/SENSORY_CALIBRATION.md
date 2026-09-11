# Sensory calibration

The matrix is in `config/sensory_mapping.v1.json`. Financial factor weights,
observation confidence, freshness, sensory gain, and fund risk limits remain
separate concepts.

| Factor | Resource | Motion | Odor A | Odor B | Light | Chaos |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| liquidity_quality | .34 | .05 | .18 | 0 | .08 | -.20 |
| market_quality | .20 | .12 | .10 | 0 | .16 | -.08 |
| activity | .12 | .38 | .10 | 0 | .24 | .12 |
| momentum | 0 | .22 | .08 | -.08 | .10 | .16 |
| flow | .04 | .18 | .18 | -.18 | .06 | .14 |
| holder_quality | .18 | .04 | .12 | 0 | .08 | -.10 |
| security_quality | .08 | 0 | .06 | -.12 | .04 | -.24 |
| social_signal | 0 | .08 | .05 | -.05 | .10 | .08 |
| risk_intensity | -.12 | .10 | -.08 | .24 | -.06 | .38 |
| novelty_activity_change | .02 | .16 | .06 | -.02 | .08 | .14 |

These coefficients are initial assumptions. Each factor contribution is capped
at `0.38`; each channel is capped by its configured envelope. No metric can
directly set a coordinate or motor command.

Run the offline tools with:

```bash
python -m malecns.calibration.sensory_sweep
python -m malecns.calibration.sensory_dominance
```

The sweep template and dominance audit explicitly report CNS response and
saturation as unavailable until connected to a live MaleCNS sweep. They do not
claim locomotion or profitability.

To add a provider, normalize its response into `RawTokenObservation` or an
additive provider-neutral domain section, attach provenance, and register the
feature. Add weights in a new versioned factor config; do not add
provider-specific logic to `HabitatEncoder`. A future learned model can
implement `FinancialFactorModel.evaluate()` and be injected into
`FinancialFactorEngine` without changing MaleCNS or the sensory interface.
