# Market signal architecture

Fruit Fly Capital uses market data as an environmental source for the fly
world. It is not a direct brain command channel and it is not a claim that a
market metric has a biological equivalent.

## Data flow

```text
CoinMarketCap ranked context + DexScreener market discovery
    |
    v
MarketUniverse -> eligibility -> locked MarketRound
    |                         |
    |                         +--> up to 100 physical market habitats
    v
GraphProvider (up to 12 selected Ethereum/Uniswap deep observers)
    |
    v
RawTokenObservation
    |
    v
TokenSignalEngine
    |
    +--> TokenState
    |      market / flow / liquidity / holders / security / social / lore
    |
    +--> Signal[]
           value / normalized / importance / valence / confidence / freshness
    |
    v
FinancialFeatureRegistry -> contextual normalization -> FinancialState
                           -> InvestabilityGuard + FinancialFactorModel v1
                           -> capped sensory mapping
    |
    v
HabitatEncoder
    |
    v
PhysicalHabitatState
    |
    v
Three.js habitat -> embodied fly sensors -> MaleCNS input
```

DexScreener is the discovery provider, not a fly preference model. It builds
chain-aware `MarketCandidate` records and selects a small, quality-filtered
round for exposure. Its internal discovery score is not serialized into
`TokenState`, `Signal`, `HabitatEncoder`, sensors, motor control, or trading
logic. The habitat model does not depend on DexScreener's response shape, and
no raw market fields are forwarded to a fly.

The Graph remains the deeper observation provider for selected Robinhood /
Uniswap-compatible pairs. The round can contain up to 100 physically present markets,
while `NEUROSWARM_MARKET_DEEP_OBSERVER_COUNT` bounds the expensive Graph tier.
The other habitats receive lightweight state from the cached DexScreener row;
this preserves market identity and a coarse sensory field without pretending
that a DexScreener summary is a swap-level observation. A future holder,
security, social, or lore provider should add its own explicit observations and
provenance.

Financial factor weights and sensory mappings are versioned in
`config/financial_factors.v1.json` and `config/sensory_mapping.v1.json`; see
[`docs/FINANCIAL_SENSORY_PIPELINE.md`](FINANCIAL_SENSORY_PIPELINE.md).

## Ranked asset context and DexScreener discovery

The implementation is in
[`src/malecns/market/dexscreener_client.py`](../src/malecns/market/dexscreener_client.py)
[`src/malecns/market/coinmarketcap_client.py`](../src/malecns/market/coinmarketcap_client.py)
and [`src/malecns/market/universe.py`](../src/malecns/market/universe.py). The
optional CoinMarketCap client uses the classic latest-listings endpoint for a
broad ranked universe. Its rank, supply, market-cap, seven-day change, 24-hour
volume change, and dominance fields are metadata/context; they are not proof
of a tradable pool on Robinhood, Base, or any other chain. In the live
configuration, only the exact `robinhood` platform is accepted from CMC
(`CMC_ALLOWED_CHAINS=robinhood`); other CMC network rows are ignored. Only
listings with an exact accepted platform chain and token address seed
DexScreener resolution.
Symbol-only matches are rejected to avoid collisions. The discovery layer
uses the documented server-side public endpoints:

- `/token-profiles/latest/v1` and `/token-profiles/recent-updates/v1` provide
  provider-supplied token profile seeds;
- `/tokens/v1/{chainId}/{tokenAddresses}` resolves those seeds to pair
  candidates in batches of up to 30 addresses;
- `/token-pairs/v1/{chainId}/{tokenAddress}` is available for explicit
  per-token lookups.

The profile feeds are a discovery input, not a complete canonical list of all
Ethereum pools. For a reliable project-specific universe, add explicit seed
addresses through `NEUROSWARM_MARKET_DISCOVERY_TOKEN_ADDRESSES`; the provider
still resolves their actual pairs and statistics. Core and recent targets are
universe sizes, not numbers of habitats or brains. The default world round is
up to 100 tracked markets locked for ten minutes, with up to 12 of those
markets sent to the deep Graph observer. World inclusion does not require the
deep liquidity/volume thresholds, so a newly tracked market can be visible
without being treated as executable or investable. If fewer than 100 real
candidates are returned by the provider, the scene shows that smaller count;
the system does not invent token markets.

When a configured Graph client supports the `pools` query, the discovery
provider also asks it for high-TVL pool IDs and enriches those IDs through
DexScreener's pair endpoint. This is a bootstrap/indexing path only; Graph
does not select a fly preference. If that optional bootstrap fails, profile or
explicit-seed discovery remains available.

The public eligibility configuration is explicit: Robinhood, all DexScreener
venues unless a DEX allowlist is supplied, at least $1,000 liquidity, at least
$1,000 24-hour volume, and a pair age of at least 30 minutes.
They are operational quality filters for arena inclusion, not safety,
profitability, or biological claims. The separate `InvestabilityGuard` applies
the `$10,000` executable-liquidity and hard security rules before execution.

## TokenState

The Python model is in
[`src/malecns/market/models.py`](../src/malecns/market/models.py). It contains:

- `market`: pair-relative price, and USD volume over 5 minutes, 15 minutes,
  1 hour, and 24 hours, plus optional CMC rank, circulating/total supply,
  seven-day price change, 24-hour volume change, and market-cap dominance;
- `flow`: token-relative buy/sell counts and USD amounts over 5 minutes, flow
  imbalance, transaction velocity, and transaction acceleration;
- `liquidity`: pool TVL in USD, change since the previous poll, and the 1-hour
  volume/liquidity ratio;
- `holders`, `security`, `social`, and `lore`: explicit domain sections whose
  status is currently `unavailable` because this provider does not supply
  those facts;
- `signals`: the derived, provenance-bearing signal list;
- `provenance`: provider, pool, represented token, and observation time.

An unavailable field is not a zero measurement. It is a statement that this
provider has not observed that domain. The encoder therefore does not invent
holder growth, contract safety, sentiment, or narrative catalysts.

## Signal contract

Every `Signal` includes:

| Field | Meaning |
| --- | --- |
| `value` | The derived value in its native units, such as USD or a count. |
| `normalized` | A bounded 0..1 representation used by the habitat encoder. |
| `importance` | How much this signal is allowed to contribute to an encoded habitat field. |
| `valence` | Signed interpretation where one is positive and minus one is negative; magnitude-only signals are neutral. |
| `confidence` | Confidence that the provider supplied enough data for this value. |
| `freshness` | Freshness at observation time, currently 1 for a successful poll. |
| `source` | The provider that produced the observation, such as `the-graph`. |
| `observedAtMs` | Provider observation time. |

The current signal list is intentionally small and inspectable:

```text
market.volume5mUsd
market.volume15mUsd
market.volume1hUsd
market.volume24hUsd (when supplied by discovery/deep-provider enrichment)
flow.buyCount5m
flow.sellCount5m
flow.buyUsd5m
flow.sellUsd5m
flow.imbalance
flow.txVelocity5m
flow.txAcceleration
liquidity.usd
liquidity.deltaUsd
liquidity.volumeLiquidityRatio1h
market.priceUsd
market.marketCapUsd
market.fdvUsd
market.pairAgeHours
liquidity.marketCapToLiquidity
liquidity.fdvToLiquidity
liquidity.volume24hToMarketCap
liquidity.volume24hToLiquidity
```

### DexScreener valuation and depth fields

The discovery payload preserves the optional `marketCap`, `fdv`, `priceUsd`,
`priceNative`, `liquidity.base`, `liquidity.quote`, `txns.h24`, `boosts.active`,
and `pairCreatedAt` fields documented by DexScreener. From them it derives:

- `marketCapToLiquidity`: circulating market cap divided by current pool LP
  liquidity;
- `fdvToLiquidity`: fully diluted valuation divided by LP liquidity;
- `volume24hToMarketCap`: 24-hour turnover relative to circulating market cap;
- `volume24hToLiquidity`: 24-hour turnover relative to current LP liquidity;
- `pairAgeHours`: elapsed age of the pair at observation time.

These are research features, not standalone trade signals. Market cap and FDV
are nullable because DexScreener may not provide them for every pair. The raw
facts, derived ratios, provider, and observation time are persisted in the
Supabase market cache and carried into `financialTrace` for lightweight
DexScreener habitats.

## Graph metrics

The provider requests up to 1 hour of swaps, sorted newest first, and the
signal engine derives all windows from the returned observations. For a poll
time `t`, a window of duration `d` contains swaps in `[t-d, t]`.

- `volume5m`, `volume15m`, and `volume1h` are sums of absolute `amountUSD`.
- `buyCount5m` and `sellCount5m` count swaps classified for the represented
  token.
- `buyUsd5m` and `sellUsd5m` sum the absolute USD amount of those swaps.
- `flowImbalance` is `(buyUsd5m - sellUsd5m) / (buyUsd5m + sellUsd5m)`, or
  zero when there were no classified trades.
- `txVelocity5m` is the number of unique transaction IDs in the 5-minute
  window divided by 5, giving transactions per minute.
- `txAcceleration` is the current 5-minute transaction velocity minus the
  preceding 5-minute interval's velocity.
- `liquidityDeltaUsd` is current pool TVL minus the previous observed TVL. It
  is unavailable on the first poll.
- `volumeLiquidityRatio1h` is 1-hour volume divided by current pool TVL, or
  zero when TVL is not positive.

### Buy/sell direction

The habitat configuration must include `tokenAddress`. The provider verifies
that it is one of the pool's `token0` or `token1` addresses. Classification
then uses the corresponding Uniswap pool amount: a negative pool balance
delta means the pool sent the represented token out (buy), and a positive
delta means the pool received it (sell). This follows the official Uniswap v3
pool action interface and event definitions:

- [Uniswap v3 pool actions](https://github.com/Uniswap/v3-core/blob/main/contracts/interfaces/pool/IUniswapV3PoolActions.sol)
- [Uniswap v3 pool events](https://github.com/Uniswap/v3-core/blob/main/contracts/interfaces/pool/IUniswapV3PoolEvents.sol)

The old shortcut of always interpreting `amount0` is therefore not used.

The Graph client uses a GraphQL `first` limit, timestamp filter, and
timestamp ordering. The provider default is 1,000 swaps over the 1-hour
lookback; these are query bounds, not a claim that the pool had only 1,000
swaps. See [The Graph GraphQL API documentation](https://thegraph.com/docs/en/subgraphs/querying/graphql-api/).

## Normalization and assumptions

The following are `OUR_ASSUMPTION`, not MaleCNS data or published Shiu model
parameters:

- USD volume normalization uses tanh scales of $10,000 for 5 minutes,
  $25,000 for 15 minutes, and $100,000 for 1 hour;
- transaction count normalization uses a scale of 10 transactions;
- transaction velocity and acceleration use a scale of 10 transactions per
  minute;
- liquidity normalization uses a $1,000,000 scale;
- ratio normalization uses a scale of 1.0;
- successful observations currently receive confidence 1 and freshness 1;
- `HabitatEncoder` turns activity, transaction velocity, liquidity, and flow
  valence into brightness, motion, odor, particle activity, and a bounded
  danger proxy.

The last item is an environmental visualization proxy. In particular,
`danger` is not a security audit and must not be presented as honeypot or
contract-risk truth. Security signals will only be added after a provider
supplies them with their own provenance.

The encoder does not directly compute thrust, yaw, pitch, or roll. The output
is physical habitat stimulation; the existing fly sensor and MaleCNS pathway
remains the only route from the habitat to a motor command.

## Provider roadmap

The next providers should be additive rather than changing the discovery or
Graph layers:

1. holder and contract-security providers for their explicit domains;
2. social and lore providers for narrative observations;
3. richer multi-chain deep observers where a compatible subgraph is configured.

Each addition must preserve source, observed time, confidence, and the
distinction between observed data, published assumptions, and project
assumptions. Until then, the live Graph mode is limited to onchain pool,
swap, flow, and liquidity signals.
