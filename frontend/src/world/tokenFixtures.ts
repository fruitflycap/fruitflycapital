import { Vector3 } from 'three'
import type { TokenState } from './TokenState'

function signal(name: string, normalized: number, valence = 0): TokenState['signals'][number] {
  return { name, value: normalized, normalized, importance: 0.8, valence, confidence: 1, freshness: 1, source: 'mock-fixture', observedAtMs: 0 }
}

export const MOCK_TOKEN_STATES: TokenState[] = [
  {
    id: 'TOKEN-A',
    label: 'ACTIVE / HEALTHY',
    tokenAddress: null,
    poolId: null,
    observedAtMs: 0,
    market: { priceInPair: null, volume5mUsd: 0, volume15mUsd: 0, volume1hUsd: 0 },
    flow: { buyCount5m: 0, sellCount5m: 0, buyUsd5m: 0, sellUsd5m: 0, flowImbalance: 0.42, txVelocity5m: 0, txAcceleration: 0 },
    liquidity: { liquidityUsd: 0, liquidityDeltaUsd: null, volumeLiquidityRatio1h: 0 },
    holders: { status: 'unavailable', holderCount: null, growth24h: null, top10Concentration: null },
    security: { status: 'unavailable', honeypot: null, contractVerified: null, ownerControl: null },
    social: { status: 'unavailable', mentions: null, sentiment: null },
    lore: { status: 'unavailable', catalysts: [] },
    signals: [signal('market.volume5mUsd', 0.88), signal('flow.txVelocity5m', 0.88), signal('liquidity.usd', 0.92), signal('flow.imbalance', 0.71, 0.42)],
    provenance: [{ provider: 'mock-fixture' }],
  },
  {
    id: 'TOKEN-B',
    label: 'QUIET / STABLE',
    tokenAddress: null,
    poolId: null,
    observedAtMs: 0,
    market: { priceInPair: null, volume5mUsd: 0, volume15mUsd: 0, volume1hUsd: 0 },
    flow: { buyCount5m: 0, sellCount5m: 0, buyUsd5m: 0, sellUsd5m: 0, flowImbalance: 0.02, txVelocity5m: 0, txAcceleration: 0 },
    liquidity: { liquidityUsd: 0, liquidityDeltaUsd: null, volumeLiquidityRatio1h: 0 },
    holders: { status: 'unavailable', holderCount: null, growth24h: null, top10Concentration: null },
    security: { status: 'unavailable', honeypot: null, contractVerified: null, ownerControl: null },
    social: { status: 'unavailable', mentions: null, sentiment: null },
    lore: { status: 'unavailable', catalysts: [] },
    signals: [signal('market.volume5mUsd', 0.18), signal('flow.txVelocity5m', 0.18), signal('liquidity.usd', 0.86), signal('flow.imbalance', 0.51, 0.02)],
    provenance: [{ provider: 'mock-fixture' }],
  },
  {
    id: 'TOKEN-C',
    label: 'ACTIVE / DANGEROUS',
    tokenAddress: null,
    poolId: null,
    observedAtMs: 0,
    market: { priceInPair: null, volume5mUsd: 0, volume15mUsd: 0, volume1hUsd: 0 },
    flow: { buyCount5m: 0, sellCount5m: 0, buyUsd5m: 0, sellUsd5m: 0, flowImbalance: -0.25, txVelocity5m: 0, txAcceleration: 0 },
    liquidity: { liquidityUsd: 0, liquidityDeltaUsd: null, volumeLiquidityRatio1h: 0 },
    holders: { status: 'unavailable', holderCount: null, growth24h: null, top10Concentration: null },
    security: { status: 'unavailable', honeypot: null, contractVerified: null, ownerControl: null },
    social: { status: 'unavailable', mentions: null, sentiment: null },
    lore: { status: 'unavailable', catalysts: [] },
    signals: [signal('market.volume5mUsd', 0.84), signal('flow.txVelocity5m', 0.84), signal('liquidity.usd', 0.22), signal('flow.imbalance', 0.375, -0.25)],
    provenance: [{ provider: 'mock-fixture' }],
  },
]

// Keep a readable local market-city layout even before the market provider
// returns its first snapshot. These are fixture identities, not trading
// recommendations; a live environment_update replaces them.
MOCK_TOKEN_STATES.push(...[
  ['TOKEN-D', 'WETH / HIGH FLOW', 0.58],
  ['TOKEN-E', 'USDC / STABLE', 0.12],
  ['TOKEN-F', 'ARB / VOLATILE', -0.18],
  ['TOKEN-G', 'LINK / DEEP LIQUIDITY', 0.28],
  ['TOKEN-H', 'UNI / ACTIVE', 0.36],
].map(([id, label, flowImbalance], index) => {
  const base = MOCK_TOKEN_STATES[index % 3]!
  const flowValue = Number(flowImbalance)
  return {
    ...base,
    id: id as string,
    label: label as string,
    flow: { ...base.flow, flowImbalance: flowValue },
    signals: base.signals.map((item) => item.name === 'flow.imbalance'
      ? { ...item, normalized: (flowValue + 1) / 2, value: flowValue, valence: flowValue, source: 'mock-fixture-expanded' }
      : { ...item, source: 'mock-fixture-expanded' }),
    provenance: [{ provider: 'mock-fixture-expanded' }],
  }
}))

export const MOCK_HABITAT_POSITIONS = [
  new Vector3(-0.67, 0, -0.68),
  new Vector3(-0.04, 0, -0.72),
  new Vector3(0.64, 0, -0.68),
  new Vector3(-0.72, 0, -0.05),
  new Vector3(0, 0, -0.06),
  new Vector3(0.72, 0, -0.03),
  new Vector3(-0.48, 0, 0.62),
  new Vector3(0.48, 0, 0.62),
]

export const MOCK_HABITAT_COLORS = [0x4bd6a0, 0x6ca8ff, 0xff6e80, 0xf5c84c, 0xa980ff, 0xff9b5c, 0x56d9d0, 0xff80b8]
