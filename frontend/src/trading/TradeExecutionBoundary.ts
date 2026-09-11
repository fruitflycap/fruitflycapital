import type { BehaviorTradeIntent } from '../networking/protocol'

export type TradeExecutionMode = 'proposal-only' | 'wallet-ready'

export interface TradeProposal {
  intent: BehaviorTradeIntent
  status: 'proposal_only'
  executionMode: TradeExecutionMode
  reason: string
}

/**
 * The browser seam for fly-generated proposals.
 *
 * This deliberately does not connect a wallet, request a quote, sign, or
 * broadcast. The server runtime takes the proposal through market-route
 * validation, RiskGuard, Uniswap calldata, and the configured adapter without
 * changing the biological observer.
 */
export class TradeExecutionBoundary {
  readonly mode: TradeExecutionMode = 'wallet-ready'

  prepare(intent: BehaviorTradeIntent): TradeProposal {
    return {
      intent,
      status: 'proposal_only',
      executionMode: this.mode,
      reason: 'behavior event captured; server autonomous runtime owns execution',
    }
  }
}
