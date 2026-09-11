# Financial factors v1

The initial model is a documented engineering assumption, not a trained
return predictor. Definitions and weights live in
`config/financial_factors.v1.json`.

| Factor | Initial feature weights |
| --- | --- |
| security_quality | contractVerified .35, sellable .35, taxQuality .15, ownerRisk .15 |
| liquidity_quality | absolute .35, relative .25, stability .20, volumeRatio .20 |
| market_quality | volume5m .30, volume1h .30, txVelocity .20, volumeRatio .20 |
| momentum | flow imbalance .60, acceleration .40 |
| flow | USD imbalance .65, count imbalance .20, acceleration .15 |
| activity | volume5m .45, tx velocity .35, acceleration magnitude .20 |
| holder_quality | growth .35, concentration quality .35, churn quality .30 |
| onchain_quality | transfer velocity .50, unique wallet growth .50 |
| social_signal | sentiment .60, mention acceleration .40 |
| fundamental_quality | age .35, supply .35, protocol usage .30 |
| risk_intensity | liquidity stress .45, flow instability .35, volatility .20 |
| novelty_activity_change | volume shock .50, acceleration .50 |

Signed factors are `-1..1`; quality and intensity factors are `0..1`.
Missing inputs make a factor unavailable rather than zero-quality. Factor
confidence is separate from feature weight, freshness, sensory gain, and fund
risk limits.

## InvestabilityGuard

The guard is outside the CNS. Its v1 rules are:

- token, pool, and pair identity must be present;
- chain must be Ethereum, Base, or Robinhood;
- liquidity must be at least `$10,000` executable liquidity;
- confirmed honeypot, confirmed non-sellable token, or blacklist mechanics fail;
- buy or sell tax above `1,000` basis points fails;
- missing security evidence is a warning by default, or a failure when
  `require_security_evidence=True`.

The world may display an ineligible market for research, but allocation and
execution must reject it. Soft warnings do not silently become approvals.
