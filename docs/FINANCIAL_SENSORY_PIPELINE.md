# Financial data to sensory pipeline

Fruit Fly Capital intentionally uses financial priors. The goal is a serious
investment research system, not a claim that the representation is neutral.
Financial facts determine what information is emphasized; the MaleCNS still
receives only a multidimensional sensory environment and determines the
behavioral response. Fund rules remain the final execution boundary.

```text
providers -> RawTokenObservation -> TokenState
          -> contextual features -> FinancialState
          -> InvestabilityGuard + financial factors
          -> capped sensory matrix -> PhysicalHabitatState
          -> FlySensors -> MaleCNS -> swarm observation -> risk guard -> execution
```

The implementation is split into `market/features/`: `registry.py` defines
features, `models.py` defines runtime features/factors/guard results,
`normalization.py` provides bounded transforms, `factors.py` evaluates the
versioned rule model, `guard.py` holds hard execution rules, `sensory.py`
applies the matrix, and `pipeline.py` provides evaluation and ablation.

`HabitatEncoder` uses `financial-sensory-v1` by default. Pass
`encoding_mode="legacy"` for the previous prototype mapping, or set the
explicit `NEUROSWARM_ENCODING_MODE=legacy` environment variable for comparison
tests. Neither mode creates a target coordinate or a buy/sell command.

Currently populated: five-minute, fifteen-minute, one-hour, and (when
supplied) 24-hour volume; USD price; market cap; FDV; pair age;
token-relative buy/sell counts and USD flow; transaction velocity and
acceleration; liquidity; liquidity change when a previous poll exists; and
volume/liquidity ratio. Derived market-cap/LP, FDV/LP, volume/market-cap, and
volume/LP ratios are also available. Derived risk-stress and activity-shock
features come from those observations.

Holder, security, onchain wallet, social, lore, and fundamental features are
registered but unavailable until a provider supplies them. Unavailable is not
converted into positive or negative evidence.

Every habitat can carry `financialTrace` with factor contributions, channel
strengths, and mapping version. Runtime features keep source, timestamp,
confidence, freshness, and provenance. The trace is diagnostics only and is
not sent as a CNS input.
