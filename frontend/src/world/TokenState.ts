export interface Signal {
  name: string
  value: number | string | null
  normalized: number
  importance: number
  valence: number
  confidence: number
  freshness: number
  source: string
  observedAtMs: number
}

export interface MarketState {
  priceInPair: number | null
  priceUsd?: number | null
  priceNative?: number | null
  marketCapUsd?: number | null
  fdvUsd?: number | null
  pairAgeHours?: number | null
  cmcId?: number | null
  cmcSlug?: string | null
  cmcRank?: number | null
  circulatingSupply?: number | null
  totalSupply?: number | null
  cmcPercentChange7d?: number | null
  cmcVolumeChange24h?: number | null
  marketCapDominance?: number | null
  volume5mUsd: number
  volume15mUsd: number
  volume1hUsd: number
  volume24hUsd?: number | null
}

export interface FlowState {
  buyCount5m: number
  sellCount5m: number
  buyUsd5m: number
  sellUsd5m: number
  flowImbalance: number
  txVelocity5m: number
  txAcceleration: number
}

export interface LiquidityState {
  liquidityUsd: number
  liquidityDeltaUsd: number | null
  volumeLiquidityRatio1h: number
  liquidityBase?: number | null
  liquidityQuote?: number | null
  marketCapToLiquidity?: number | null
  fdvToLiquidity?: number | null
  volume24hToMarketCap?: number | null
  volume24hToLiquidity?: number | null
}

export interface HoldersState {
  status: 'unavailable' | 'available'
  holderCount: number | null
  growth24h: number | null
  top10Concentration: number | null
}

export interface SecurityState {
  status: 'unavailable' | 'available'
  honeypot: boolean | null
  sellable?: boolean | null
  contractVerified: boolean | null
  ownerControl: string | null
  buyTaxBps?: number | null
  sellTaxBps?: number | null
  blacklistMechanic?: boolean | null
  mintCapability?: boolean | null
  proxy?: boolean | null
  securityFlags?: string[]
}

export interface SocialState {
  status: 'unavailable' | 'available'
  mentions: number | null
  sentiment: number | null
}

export interface LoreState {
  status: 'unavailable' | 'available'
  catalysts: string[]
}

/** The frontend copy of the provider-neutral token domain model. */
export interface TokenState {
  id: string
  label: string
  imageUrl?: string | null
  tokenAddress: string | null
  poolId: string | null
  chainId?: string
  dexId?: string
  pairAddress?: string | null
  dexscreenerUrl?: string | null
  observedAtMs: number
  market: MarketState
  flow: FlowState
  liquidity: LiquidityState
  holders: HoldersState
  security: SecurityState
  social: SocialState
  lore: LoreState
  signals: Signal[]
  provenance: Array<Record<string, unknown>>
  financial?: Record<string, unknown> | null
}
