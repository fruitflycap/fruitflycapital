import './style.css'
import { resolveBrainWebSocketUrl } from '../networking/brainUrl'

type Portfolio = { fund?: Record<string, unknown>; demoData?: boolean }
const app = document.querySelector<HTMLElement>('#portfolio-app')!
const wsUrl = resolveBrainWebSocketUrl(import.meta.env.VITE_BRAIN_WS_URL)
const money = (value: unknown) => typeof value === 'number' ? `$${value.toFixed(2)}` : '—'
const percent = (value: unknown) => typeof value === 'number' ? `${value >= 0 ? '+' : ''}${value.toFixed(2)}%` : '—'
const isRealTxHash = (value: unknown): value is string => typeof value === 'string' && /^0x[a-fA-F0-9]{64}$/.test(value)
const nativeRaw = (value: unknown) => {
  if (typeof value !== 'string' || !/^\d+$/.test(value)) return '—'
  const whole = value.padStart(19, '0')
  const split = whole.length - 18
  return `${whole.slice(0, split)}.${whole.slice(split, split + 8)} ETH`
}
const mainnetExecutionCard = (item: Record<string, unknown>) => {
  const txHash = isRealTxHash(item.txHash) ? item.txHash : null
  if (!txHash) return ''
  const flyIds = Array.isArray(item.flyIds) ? item.flyIds.map(String).join(' · ') : '—'
  const side = String(item.side || '—').toUpperCase()
  const inputToken = String(item.inputToken || '')
  const input = inputToken === '0x0000000000000000000000000000000000000000' ? nativeRaw(item.inputAmount) : String(item.inputAmount || '—')
  const output = item.actualOutputAmount ?? item.expectedOutput ?? '—'
  const block = item.blockNumber ? `Block ${String(item.blockNumber)}` : 'Awaiting receipt'
  const gas = item.transactionFee ? nativeRaw(item.transactionFee) : '—'
  const status = String(item.status || 'PENDING')
  return `<article class="execution-card execution-${status.toLowerCase()}"><div class="execution-card-top"><strong>${flyIds}</strong><span>${status}</span></div><h3>${side} ${String(item.tokenSymbol || 'TOKEN')}</h3><div class="execution-route">${input} → ${String(output)} ${String(item.tokenSymbol || '')}</div><div class="execution-meta"><span>ROBINHOOD CHAIN</span><span>${block}</span><span>Gas ${gas}</span></div><a class="execution-link" href="https://robinhoodchain.blockscout.com/tx/${txHash}" target="_blank" rel="noopener noreferrer">VIEW ON BLOCKSCOUT ↗</a></article>`
}

function render(data: Portfolio | null, status = 'CONNECTING') {
  const fund = data?.fund || {}
  const legacyPositions = Array.isArray(fund.positions) ? fund.positions as Record<string, unknown>[] : []
  const trades = Array.isArray(fund.recentTrades) ? fund.recentTrades as Record<string, unknown>[] : []
  const chains = Array.isArray(fund.allocationByChain) ? fund.allocationByChain as Record<string, unknown>[] : []
  const security = (fund.security || {}) as Record<string, unknown>
  const wallet = (fund.wallet || {}) as Record<string, unknown>
  const allocation = (fund.allocation || {}) as Record<string, unknown>
  const autonomous = (fund.autonomous || {}) as Record<string, unknown>
  const flies = Array.isArray(autonomous.flies) ? autonomous.flies as Record<string, unknown>[] : []
  const target = Array.isArray(autonomous.biologicalTargetPortfolio) ? autonomous.biologicalTargetPortfolio as Record<string, unknown>[] : []
  const actual = Array.isArray(autonomous.actualWalletPortfolio) ? autonomous.actualWalletPortfolio as Record<string, unknown>[] : []
  const mainnetExecutions = Array.isArray(autonomous.mainnetExecutions) ? autonomous.mainnetExecutions as Record<string, unknown>[] : []
  const pendingExecution = Array.isArray(autonomous.pendingExecution) ? autonomous.pendingExecution as Record<string, unknown>[] : []
  const confirmedExecutionEvents = mainnetExecutions.filter((item) => {
    const status = String(item.status || '').toUpperCase()
    return isRealTxHash(item.txHash) && ['BROADCAST', 'PENDING', 'CONFIRMED', 'REVERTED'].includes(status)
  })
  const native = (value: unknown) => typeof value === 'number' ? `${value.toFixed(6)} ETH` : '—'
  const observedTokenPositions = actual.filter((item) => {
    const address = String(item.tokenAddress || item.token_address || '')
    const amount = Number(item.observedAmount ?? item.amount ?? 0)
    return /^0x[a-fA-F0-9]{40}$/.test(address)
      && !/^0x0{40}$/i.test(address)
      && Number.isFinite(amount)
      && amount > 0
  })
  const positions = legacyPositions.length
    ? legacyPositions
    : observedTokenPositions.map((item) => ({
      symbol: item.tokenSymbol,
      token_address: item.tokenAddress,
      chain_id: item.chainId,
      amount: item.observedAmount,
      value_usd: item.observedValueUsd,
      unrealized_pnl_usd: null,
    }))
  const observedTokenValueUsd = observedTokenPositions.reduce((sum, item) => {
    const value = Number(item.observedValueUsd)
    return Number.isFinite(value) ? sum + value : sum
  }, 0)
  const walletAddress = String(wallet.address || fund.treasuryAddress || 'not configured')
  const walletExplorerLink = /^0x[a-fA-F0-9]{40}$/.test(walletAddress) ? `<a class="explorer-button" href="https://robinhoodchain.blockscout.com/address/${walletAddress}" target="_blank" rel="noopener noreferrer">WATCH WALLET ON BLOCKSCOUT ↗</a>` : ''
  const walletStatus = wallet.status === 'error' ? `RPC ERROR · ${String(wallet.error || 'unable to read balance')}` : wallet.configured ? 'RPC BALANCE LIVE' : 'WALLET NOT CONFIGURED'
  const walletChain = String(wallet.chainId || fund.chainId || '—')
  const displayedNav = typeof fund.navUsd === 'number' && fund.navUsd > 0
    ? money(fund.navUsd)
    : observedTokenValueUsd > 0
      ? money(observedTokenValueUsd)
    : typeof wallet.nativeBalance === 'number'
      ? `${wallet.nativeBalance.toFixed(6)} ${String(wallet.nativeSymbol || 'ETH')}`
      : money(fund.navUsd)
  const displayedReturn = typeof autonomous.portfolioReturnPct === 'number'
    ? percent(autonomous.portfolioReturnPct)
    : null
  app.innerHTML = `<header class="site-header"><a class="portfolio-brand site-brand" href="/" aria-label="FruitFly Capital home"><img src="/fruitfly-logo.png" alt="" /> <span>FRUITFLY CAPITAL</span></a><nav class="site-nav" aria-label="Primary navigation"><a href="/">Simulation</a><a href="/about/">About</a><a class="is-active" href="/portfolio/">Portfolio</a><a href="/#buy">Buy</a><a href="https://x.com/fruitflycap" target="_blank" rel="noreferrer">Community</a></nav><a class="social-link header-social" href="https://x.com/fruitflycap" target="_blank" rel="noreferrer" aria-label="FruitFly Capital on X"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18.9 2H22l-6.77 7.74L23.2 22h-6.24l-4.89-6.39L6.48 22H3.36l7.24-8.28L2.8 2h6.4l4.42 5.84L18.9 2Zm-1.1 17.7h1.73L8.28 4.2H6.42L17.8 19.7Z" /></svg><span>@fruitflycap</span></a></header><div class="portfolio-title"><h1>FRUITFLY CAPITAL</h1><p>AUTONOMOUS BIOLOGICAL FUND</p></div>
    <section class="notice">${data?.demoData ? 'DEMO DATA · NOT A LIVE PORTFOLIO' : 'ROBINHOOD WALLET · UNISWAP EXECUTION RUNTIME'} · ${walletStatus} · ${String(autonomous.executionAdapter || 'adapter pending')}</section>
    <section class="metrics">${[['WALLET TOTAL', native(wallet.nativeBalance)], ['AVAILABLE TO TRADE', native(wallet.availableToTrade)], ['GAS RESERVE', native(wallet.gasReserve)], ['PER FLY BUDGET', native(allocation.perFlyBudget)], ['TOTAL FUND NAV', displayedNav], ...(displayedReturn !== null ? [['FUND RETURN', displayedReturn]] : [])].map(([label, value]) => `<article><small>${label}</small><strong>${value}</strong></article>`).join('')}</section>
    <section class="panel wallet-summary"><div><small>ROBINHOOD WALLET</small><code>${walletAddress}</code></div><div><small>NATIVE BALANCE</small><strong>${native(wallet.nativeBalance)}</strong></div><div><small>AVAILABLE AFTER GAS RESERVE</small><strong>${native(wallet.availableToTrade)}</strong></div><div><small>CHAIN</small><strong>Robinhood · ${walletChain}</strong></div><div><small>RPC STATUS</small><strong class="wallet-status ${wallet.status === 'error' ? 'is-error' : ''}">${walletStatus}</strong></div>${walletExplorerLink}</section>
    <section class="panel"><h2>FLY ALLOCATION STATE</h2><div class="table"><div class="thead"><span>FLY</span><span>STATE</span><span>TOKEN</span><span>VALUE</span><span>REALIZED</span><span>UNREALIZED</span></div>${flies.map(item => `<div class="tr"><span>${String(item.flyId || '—')}</span><span>${String(item.state || '—')}</span><span>${String(item.tokenSymbol || item.tokenAddress || 'EXPLORING')}</span><span>${money(item.currentValueUsd)}</span><span>${money(item.realizedPnlUsd)}</span><span>${money(item.unrealizedPnlUsd)}</span></div>`).join('') || '<p class="muted">No fly state received yet.</p>'}</div></section>
    <section class="grid"><article class="panel"><h2>BIOLOGICAL TARGET PORTFOLIO</h2>${target.length ? target.map(item => `<div class="row"><span>${String(item.tokenAddress || '—')}</span><b>${typeof item.allocationPercent === 'number' ? item.allocationPercent.toFixed(2) : '0.00'}%</b></div>`).join('') : '<p class="muted">No fly is holding a token.</p>'}</article><article class="panel"><h2>ACTUAL WALLET PORTFOLIO</h2>${actual.length ? actual.map(item => `<div class="trade"><b>${String(item.tokenSymbol || item.tokenAddress || '—')}</b><span>planned ${String(item.intendedAmount ?? '—')}</span><span>observed ${String(item.observedAmount ?? '—')}</span><span>${String(item.reconciliation || item.observationError || 'pending')}</span></div>`).join('') : '<p class="muted">No token balances observed yet.</p>'}</article></section>
    <section class="grid"><article class="panel"><h2>PORTFOLIO ALLOCATION BY CHAIN</h2>${chains.length ? chains.map(item => `<div class="row"><span>CHAIN ${item.chainId}</span><b>${typeof item.weight === 'number' ? (item.weight * 100).toFixed(1) : '—'}%</b></div>`).join('') : '<p class="muted">No priced positions recorded.</p>'}</article>
      <article class="panel"><h2>WALLET &amp; EXECUTION</h2><div class="kv"><span>Wallet</span><code>${walletAddress}</code><span>Chain</span><b>Robinhood · ${walletChain}</b><span>Fly allocation</span><b>${typeof allocation.perFlyPercent === 'number' ? allocation.perFlyPercent.toFixed(2) : '—'}% · ${String(allocation.flyCount || '—')} flies</b><span>Execution</span><b>${String(fund.executionBoundary || '—').toUpperCase()}</b><span>Trade limit</span><b>${money(security.autonomousTradeLimitUsd)}</b></div></article></section>
    <section class="panel"><h2>POSITIONS</h2><div class="table"><div class="thead"><span>ASSET</span><span>CHAIN</span><span>AMOUNT</span><span>VALUE</span><span>P&L</span></div>${positions.length ? positions.map(item => `<div class="tr"><span>${String(item.symbol || item.token_address || '—')}</span><span>${String(item.chain_id || '—')}</span><span>${String(item.amount ?? '—')}</span><span>${money(item.value_usd)}</span><span>${money(item.unrealized_pnl_usd)}</span></div>`).join('') : '<p class="muted">No positions recorded yet.</p>'}</div></section>
    <section class="panel"><h2>RECENT FRUITFLY CAPITAL TRADES</h2>${trades.filter(item => isRealTxHash(item.tx_hash) && ['BROADCAST', 'PENDING', 'CONFIRMED', 'REVERTED'].includes(String(item.status || '').toUpperCase())).length ? trades.filter(item => isRealTxHash(item.tx_hash) && ['BROADCAST', 'PENDING', 'CONFIRMED', 'REVERTED'].includes(String(item.status || '').toUpperCase())).map(item => `<div class="trade"><b>${String(item.status || '—').toUpperCase()}</b><span>chain ${String(item.chain_id || '—')}</span><span>${money(item.usd_value)}</span><a href="https://robinhoodchain.blockscout.com/tx/${item.tx_hash}" target="_blank" rel="noopener noreferrer">VIEW TX ↗</a></div>`).join('') : '<p class="muted">No on-chain trades recorded yet.</p>'}</section>
    <section class="panel mainnet-executions"><h2>MAINNET EXECUTED · ROBINHOOD CHAIN</h2>${mainnetExecutions.length ? mainnetExecutions.map(mainnetExecutionCard).join('') : '<p class="muted">No real mainnet transaction hashes recorded.</p>'}</section>
    <section class="grid"><article class="panel"><h2>BUY / HOLD / SELL EVENTS</h2>${confirmedExecutionEvents.length ? confirmedExecutionEvents.slice(0, 20).map(item => `<div class="trade"><b>${String(item.side || '—').toUpperCase()}</b><span>${Array.isArray(item.flyIds) ? item.flyIds.map(String).join(', ') : String(item.flyIds || '—')}</span><span>${String(item.status || '—')}</span><span>${String(item.tokenSymbol || item.tokenAddress || '—')}</span><span>${String(item.actualInputAmount || item.inputAmount || '—')} → ${String(item.actualOutputAmount || item.expectedOutput || '—')}</span><a href="https://robinhoodchain.blockscout.com/tx/${item.txHash}" target="_blank" rel="noopener noreferrer">VIEW TX ↗</a></div>`).join('') : '<p class="muted">No confirmed or broadcast buys/sells yet.</p>'}</article><article class="panel"><h2>PENDING EXECUTION</h2>${pendingExecution.filter((item) => isRealTxHash(item.txHash)).length ? pendingExecution.filter((item) => isRealTxHash(item.txHash)).map(item => `<div class="trade"><b>${String(item.status || '—')}</b><span>${String(item.side || '—').toUpperCase()} ${String(item.tokenSymbol || 'TOKEN')}</span><span>${Array.isArray(item.flyIds) ? item.flyIds.map(String).join(', ') : String(item.flyIds || '—')}</span><a href="https://robinhoodchain.blockscout.com/tx/${item.txHash}" target="_blank" rel="noopener noreferrer">VIEW TX ↗</a></div>`).join('') : '<p class="muted">No pending on-chain execution.</p>'}</article></section>
    <footer><a href="./">FRUITFLY CAPITAL</a><button id="refresh">REFRESH</button><span>FruitFly Capital · MaleCNS · Flybody · The Graph</span></footer>`
  document.querySelector('#refresh')?.addEventListener('click', request)
}
function request() {
  render(null, 'CONNECTING')
  const socket = new WebSocket(wsUrl)
  socket.addEventListener('open', () => socket.send(JSON.stringify({ type: 'portfolio_request' })))
  socket.addEventListener('message', event => { try { const message = JSON.parse(event.data); if (message.type === 'portfolio_update') render(message, 'CONNECTED') } catch { render(null, 'ERROR') } })
  socket.addEventListener('error', () => render(null, 'OFFLINE'))
}
render(null)
request()
