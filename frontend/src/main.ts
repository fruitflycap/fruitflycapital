import './style.css'
import { BufferGeometry, Line, LineBasicMaterial, Mesh, MeshBasicMaterial, Object3D, Plane, Points, PointsMaterial, Raycaster, Scene, Shape, ShapeGeometry, Vector2, Vector3, WebGLRenderer } from 'three'
import { Environment } from './world/Environment'
import type { TokenHabitat } from './world/TokenHabitat'
import { World } from './world/World'
import { BrainSocket } from './networking/BrainSocket'
import type { FlyAgent } from './fly/FlyAgent'
import { FlyPopulation } from './fly/FlyPopulation'
import { DebugRenderer } from './rendering/DebugRenderer'
import { FreeCamera } from './camera/FreeCamera'
import { FollowCamera } from './camera/FollowCamera'
import { FirstPersonCamera } from './camera/FirstPersonCamera'
import { SideCamera } from './camera/SideCamera'
import { FlightLogger } from './networking/FlightLog'
import { BODIES_PER_BRAIN, SWARM_SIZE, VISUAL_FLY_COUNT } from './fly/SwarmConfig'
import { PostProcessingPipeline, type RenderQuality } from './rendering/PostProcessing'
import { PresentationCamera } from './camera/PresentationCamera'
import { isLiveBrainSource, vectorToWire } from './networking/protocol'
import { BrainActivityPanel } from './rendering/BrainActivityPanel'
import { SceneAtmosphere } from './rendering/SceneAtmosphere'
import type { TokenState } from './world/TokenState'
import { SwarmObserver } from './swarm/SwarmObserver'
import { PRESENTATION_SCENE_HALF_EXTENT } from './world/Arena'
import type { BehaviorTradeIntent } from './networking/protocol'
import { resolveBrainWebSocketUrl } from './networking/brainUrl'
import { SceneAudio } from './audio/SceneAudio'

// The public experience is intentionally autonomous. Manual actuation remains
// available only inside the controller module for isolated developer tests; it
// is not selectable from the product UI or environment configuration.
const app = document.querySelector<HTMLDivElement>('#app')
if (!app) throw new Error('Missing #app root')

const canvas = document.createElement('canvas')
canvas.className = 'world-canvas'
canvas.style.touchAction = 'none'
app.append(canvas)
const sceneAudio = new SceneAudio()

// Provider logos can be loaded by the browser as normal DOM images even when
// the provider does not opt into WebGL canvas CORS. Keep the Three.js logo as
// the depth-aware fallback, and place the real image above it when available.
// This makes logos visible without turning a failed cross-origin texture load
// into a blank habitat marker.
const tokenLogoOverlay = document.createElement('div')
tokenLogoOverlay.className = 'token-logo-overlay'
app.append(tokenLogoOverlay)
type TokenLogoEntry = {
  element: HTMLImageElement
  fallback: HTMLSpanElement
  button: HTMLButtonElement
  sources: string[]
  source: string
  failedSources: Set<string>
}
const tokenLogoElements = new Map<string, TokenLogoEntry>()
const fallbackLogoCache = new Map<string, string>()
const logoWorldPosition = new Vector3()
const logoEdgePosition = new Vector3()
const drawOverlay = document.createElementNS('http://www.w3.org/2000/svg', 'svg')
drawOverlay.classList.add('free-draw-overlay')
drawOverlay.setAttribute('aria-hidden', 'true')
drawOverlay.setAttribute('preserveAspectRatio', 'none')
const drawPath = document.createElementNS('http://www.w3.org/2000/svg', 'path')
drawPath.classList.add('free-draw-path')
drawOverlay.append(drawPath)
app.append(drawOverlay)
let draftScreenPoints: Array<[number, number]> = []

function resizeDrawOverlay() {
  drawOverlay.setAttribute('viewBox', `0 0 ${window.innerWidth} ${window.innerHeight}`)
}

resizeDrawOverlay()
window.addEventListener('resize', resizeDrawOverlay)

function updateTokenLogoOverlay() {
  const visibleIds = new Set<string>()
  const viewportWidth = window.innerWidth
  const viewportHeight = window.innerHeight
  // Projection happens before the renderer's next pass. Refresh the camera
  // matrices here so logos do not get classified as off-screen for one frame
  // after a cinematic/follow camera update.
  activeCamera.updateMatrixWorld(true)
  for (const habitat of environment.habitats) {
    const id = habitat.state.id
    visibleIds.add(id)
    const fallbackSource = fallbackLogoCache.get(id) ?? fallbackLogoUrl(habitat.state.label)
    fallbackLogoCache.set(id, fallbackSource)
    const sources = logoSources(habitat, fallbackSource)
    let entry = tokenLogoElements.get(id)
    if (!entry) {
      const button = document.createElement('button')
      button.className = 'token-logo-link'
      button.type = 'button'
      button.addEventListener('click', () => {
        const currentHabitat = environment.habitats.find((candidate) => candidate.state.id === id)
        if (currentHabitat) openTokenPopup(currentHabitat)
      })
      const element = document.createElement('img')
      element.className = 'token-logo-image'
      element.alt = `${habitat.state.label} logo`
      element.draggable = false
      element.loading = 'eager'
      element.referrerPolicy = 'no-referrer'
      const fallback = document.createElement('span')
      fallback.className = 'token-logo-fallback'
      fallback.textContent = logoSymbolFromLabel(habitat.state.label)
      fallback.hidden = true
      const nextEntry: TokenLogoEntry = { element, fallback, button, sources, source: sources[0]!, failedSources: new Set() }
      element.addEventListener('load', () => {
        element.hidden = false
        fallback.hidden = true
      })
      element.addEventListener('error', () => {
        // Provider images are optional. Try the next provider/address lookup
        // before falling back to the deterministic local mark.
        nextEntry.failedSources.add(nextEntry.source)
        const nextSource = nextEntry.sources.find((candidate) => !nextEntry.failedSources.has(candidate))
        if (nextSource && nextSource !== nextEntry.source) {
          nextEntry.source = nextSource
          element.src = nextSource
          element.hidden = false
          fallback.hidden = true
        } else {
          // A provider can fail or block both remote URLs. Keep the clickable
          // habitat identity visible as initials instead of exposing a broken
          // image icon.
          element.hidden = true
          fallback.hidden = false
        }
        button.hidden = false
      })
      button.append(element, fallback)
      tokenLogoOverlay.append(button)
      entry = nextEntry
      tokenLogoElements.set(id, entry)
      // The initial source used to be selected but never assigned to the
      // image, leaving every habitat with an empty/broken image element.
      element.src = nextEntry.source
    }
    entry.sources = sources
    entry.fallback.textContent = logoSymbolFromLabel(habitat.state.label)
    const source = sources.find((candidate) => !entry!.failedSources.has(candidate)) ?? fallbackSource
    if (entry.source !== source || !entry.element.src) {
      entry.source = source
      entry.button.hidden = false
      entry.element.hidden = false
      entry.fallback.hidden = true
      entry.element.src = source
    }
    entry.button.setAttribute('aria-label', `Open ${habitat.state.label} token details`)
    entry.button.tabIndex = 0
    // Project the same local anchor used by the Three.js logo sprite. Using
    // raw group coordinates here ignored the habitat's visual scale, which
    // made DOM logos float well above their plates during close cinematic
    // shots.
    logoWorldPosition.set(0, 0.17, 0)
    habitat.group.localToWorld(logoWorldPosition)
    logoEdgePosition.set(Math.max(0.04, habitat.properties.physicalRadiusM * 0.62), 0.17, 0)
    habitat.group.localToWorld(logoEdgePosition)
    logoWorldPosition.project(activeCamera)
    logoEdgePosition.project(activeCamera)
    const onScreen = logoWorldPosition.z >= -1 && logoWorldPosition.z <= 1
      && logoWorldPosition.x >= -1.15 && logoWorldPosition.x <= 1.15
      && logoWorldPosition.y >= -1.15 && logoWorldPosition.y <= 1.15
    if (!onScreen) {
      entry.button.hidden = true
      continue
    }
    const centerX = (logoWorldPosition.x * 0.5 + 0.5) * viewportWidth
    const centerY = (-logoWorldPosition.y * 0.5 + 0.5) * viewportHeight
    const projectedRadius = Math.abs(logoEdgePosition.x - logoWorldPosition.x) * 0.5 * viewportWidth
    // Give the logo enough presence to identify a habitat from the overview
    // while keeping a sensible cap for close cinematic shots.
    const size = clamp(projectedRadius * 1.72 * environment.getHabitatVisualScale(), 22, 72)
    entry.button.hidden = false
    entry.button.style.width = `${size}px`
    entry.button.style.height = `${size}px`
    entry.button.style.left = `${centerX}px`
    entry.button.style.top = `${centerY}px`
  }
  for (const [id, entry] of tokenLogoElements) {
    if (!visibleIds.has(id)) entry.button.hidden = true
  }
}

function fallbackLogoUrl(label: string) {
  const symbol = logoSymbolFromLabel(label)
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128"><defs><radialGradient id="g" cx="30%" cy="25%"><stop stop-color="#55766a"/><stop offset="1" stop-color="#0b171b"/></radialGradient></defs><circle cx="64" cy="64" r="59" fill="url(#g)" stroke="#dcebe2" stroke-width="2"/><text x="64" y="70" fill="#f4f7f4" font-family="Arial,sans-serif" font-size="${symbol.length > 3 ? 26 : 34}" font-weight="700" text-anchor="middle">${symbol}</text></svg>`
  return `data:image/svg+xml;charset=UTF-8,${encodeURIComponent(svg)}`
}

function logoSources(habitat: TokenHabitat, fallbackSource: string) {
  const sources: string[] = []
  const remoteSource = habitat.state.imageUrl ?? imageUrlFromProvenance(habitat.state.provenance)
  if (remoteSource) sources.push(normalizeImageUrl(remoteSource))

  // Lightweight Robinhood snapshots do not always carry the pair image URL.
  // DexScreener also exposes a token-address image path, which gives those
  // habitats a real provider logo without another API request or a
  // CORS-sensitive WebGL texture load.
  const tokenAddress = habitat.state.tokenAddress
  if (tokenAddress && /^0x[a-fA-F0-9]{40}$/.test(tokenAddress)) {
    const chain = habitat.state.chainId?.toLowerCase() === '4663'
      ? 'robinhood'
      : (habitat.state.chainId?.toLowerCase() || 'robinhood')
    sources.push(`https://dd.dexscreener.com/ds-data/tokens/${chain}/${tokenAddress}.png`)
  }

  sources.push(fallbackSource)
  return [...new Set(sources)]
}

function logoSymbolFromLabel(label: string) {
  const value = label.split('·')[0]?.trim() || label
  return value.replace(/[^a-z0-9]/gi, '').slice(0, 4).toUpperCase() || '?'
}

function imageUrlFromProvenance(provenance: Array<Record<string, unknown>>) {
  const imageUrl = provenance.find((item) => typeof item.imageUrl === 'string')?.imageUrl
  return typeof imageUrl === 'string' && imageUrl.length > 0 ? imageUrl : null
}

function normalizeImageUrl(url: string) {
  if (url.startsWith('ipfs://')) return `https://ipfs.io/ipfs/${url.slice('ipfs://'.length)}`
  if (url.startsWith('ipns://')) return `https://ipfs.io/ipns/${url.slice('ipns://'.length)}`
  return url
}

function updateDraftScreenPath() {
  if (draftScreenPoints.length === 0) {
    drawPath.setAttribute('d', '')
    return
  }
  const [first, ...rest] = draftScreenPoints
  const d = [`M ${first![0]} ${first![1]}`, ...rest.map(([x, y]) => `L ${x} ${y}`)]
  if (draftBoundaryClosed) d.push('Z')
  drawPath.setAttribute('d', d.join(' '))
}

// Keep the initial empty room out of view. The first frame is shown after the
// canonical Flybody scene is ready. Brain connection and motion are runtime
// states, not asset-loading prerequisites, so a quiet/late brain feed must not
// leave the entire app behind the loading screen.
const startupScreen = document.createElement('div')
startupScreen.className = 'startup-screen'
startupScreen.innerHTML = `
  <div class="startup-card">
    <div class="startup-title">Fruit Fly Capital</div>
    <div class="startup-message">LOADING CANONICAL FLYBODY</div>
    <div class="startup-detail">Preparing the fly bodies and first motion sample…</div>
    <div class="startup-progress"><span></span></div>
  </div>
`
app.append(startupScreen)
const startupMessage = startupScreen.querySelector<HTMLDivElement>('.startup-message')!
const startupDetail = startupScreen.querySelector<HTMLDivElement>('.startup-detail')!
const startupProgress = startupScreen.querySelector<HTMLSpanElement>('.startup-progress span')!

const hud = document.createElement('div')
hud.className = 'hud'
hud.innerHTML = `
  <a class="brand site-brand" href="/" aria-label="FruitFly Capital home"><img class="brand-logo" src="/fruitfly-logo.png" alt="" /> <span>FRUITFLY CAPITAL</span></a>
  <nav class="site-nav" aria-label="Primary navigation"><a class="is-active" href="/">Simulation</a><a href="/about/">About</a><a href="/portfolio/">Portfolio</a><a href="/#buy">Buy</a><a href="https://x.com/fruitflycap" target="_blank" rel="noreferrer">Community</a></nav>
  <div class="header-tools"><a class="social-link header-social" href="https://x.com/fruitflycap" target="_blank" rel="noreferrer" aria-label="FruitFly Capital on X"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18.9 2H22l-6.77 7.74L23.2 22h-6.24l-4.89-6.39L6.48 22H3.36l7.24-8.28L2.8 2h6.4l4.42 5.84L18.9 2Zm-1.1 17.7h1.73L8.28 4.2H6.42L17.8 19.7Z" /></svg><span>@fruitflycap</span></a><button class="audio-toggle" type="button" aria-pressed="false">SOUND OFF</button></div>
`
app.append(hud)
const audioToggle = hud.querySelector<HTMLButtonElement>('.audio-toggle')!

function renderAudioToggle() {
  audioToggle.textContent = sceneAudio.isEnabled ? 'SOUND ON' : 'SOUND OFF'
  audioToggle.setAttribute('aria-pressed', String(sceneAudio.isEnabled))
  audioToggle.setAttribute('aria-label', sceneAudio.isEnabled ? 'Mute scene audio' : 'Enable scene audio')
}

let audioToggleBusy = false
audioToggle.addEventListener('click', async () => {
  if (audioToggleBusy) return
  audioToggleBusy = true
  audioToggle.disabled = true
  try {
    await sceneAudio.toggle()
  } finally {
    audioToggleBusy = false
    audioToggle.disabled = false
    renderAudioToggle()
  }
})

// Web Audio is blocked until a user gesture. Start the ambient bed on the
// first interaction anywhere in the scene, while keeping a visible mute
// control for visitors who prefer a silent experience.
const unlockSceneAudio = (event: Event) => {
  // Let the sound button own its first click. Otherwise the global autoplay
  // unlock can enable audio just before the button handler toggles it back.
  if (event.target instanceof Element && event.target.closest('.audio-toggle')) return
  void sceneAudio.enable().then(renderAudioToggle)
  window.removeEventListener('pointerdown', unlockSceneAudio, true)
  window.removeEventListener('keydown', unlockSceneAudio, true)
}
window.addEventListener('pointerdown', unlockSceneAudio, true)
window.addEventListener('keydown', unlockSceneAudio, true)
renderAudioToggle()

const sceneFooter = document.createElement('footer')
sceneFooter.className = 'scene-footer'
sceneFooter.innerHTML = `<span>FRUITFLY CAPITAL</span><a href="/about/">ABOUT</a><a href="/portfolio/">PORTFOLIO</a><a href="https://x.com/fruitflycap" target="_blank" rel="noreferrer">X @FRUITFLYCAP</a>`
app.append(sceneFooter)

const portfolioSummary = document.createElement('section')
portfolioSummary.className = 'portfolio-summary'
portfolioSummary.setAttribute('aria-label', 'Live portfolio summary')
portfolioSummary.innerHTML = `
  <div class="portfolio-summary-heading"><span>FRUITFLY CAPITAL · PORTFOLIO</span><span class="portfolio-summary-actions"><a href="/portfolio/">OPEN FULL PORTFOLIO →</a><a data-portfolio-summary="wallet-link" href="https://robinhoodchain.blockscout.com/address/0xB2B6710B85BfFF84b68aA4a91e78532f4FA726a9" target="_blank" rel="noopener noreferrer">WATCH WALLET ↗</a></span></div>
  <div class="portfolio-summary-values"><div><small>WALLET</small><strong data-portfolio-summary="wallet">CONNECTING</strong></div><div><small>AVAILABLE</small><strong data-portfolio-summary="available">—</strong></div><div><small>POSITIONS</small><strong data-portfolio-summary="positions">—</strong></div><div class="portfolio-summary-return" data-portfolio-summary="return-field" hidden><small>RETURN</small><strong data-portfolio-summary="return"></strong></div></div>
  <div class="portfolio-summary-stats"><span>NAV <b data-portfolio-summary="nav">—</b></span><span>GAS <b data-portfolio-summary="gas">—</b></span><span>HELD FLIES <b data-portfolio-summary="held-flies">—</b></span><span>ON-CHAIN <b data-portfolio-summary="onchain">—</b></span></div>
  <div class="portfolio-summary-holdings" data-portfolio-summary="holdings">Waiting for live portfolio data…</div>
`
app.append(portfolioSummary)
const portfolioSummaryFields = {
  wallet: portfolioSummary.querySelector<HTMLElement>('[data-portfolio-summary="wallet"]')!,
  available: portfolioSummary.querySelector<HTMLElement>('[data-portfolio-summary="available"]')!,
  positions: portfolioSummary.querySelector<HTMLElement>('[data-portfolio-summary="positions"]')!,
  returnField: portfolioSummary.querySelector<HTMLElement>('[data-portfolio-summary="return-field"]')!,
  return: portfolioSummary.querySelector<HTMLElement>('[data-portfolio-summary="return"]')!,
  nav: portfolioSummary.querySelector<HTMLElement>('[data-portfolio-summary="nav"]')!,
  gas: portfolioSummary.querySelector<HTMLElement>('[data-portfolio-summary="gas"]')!,
  heldFlies: portfolioSummary.querySelector<HTMLElement>('[data-portfolio-summary="held-flies"]')!,
  onchain: portfolioSummary.querySelector<HTMLElement>('[data-portfolio-summary="onchain"]')!,
  holdings: portfolioSummary.querySelector<HTMLElement>('[data-portfolio-summary="holdings"]')!,
  walletLink: portfolioSummary.querySelector<HTMLAnchorElement>('[data-portfolio-summary="wallet-link"]')!,
}

const executionToast = document.createElement('aside')
executionToast.className = 'mainnet-execution-toast'
executionToast.setAttribute('aria-live', 'polite')
executionToast.hidden = true
app.append(executionToast)
const confirmedExecutionIds = new Set<string>()
let executionToastInitialized = false
let executionToastTimer: number | null = null

function updateExecutionToast() {
  const fund = brainSocket.portfolio()
  const autonomous = (fund?.autonomous || {}) as Record<string, unknown>
  const executions = Array.isArray(autonomous.mainnetExecutions) ? autonomous.mainnetExecutions as Record<string, unknown>[] : []
  if (!executionToastInitialized) {
    executions.filter((item) => item.status === 'CONFIRMED').forEach((item) => confirmedExecutionIds.add(String(item.executionId || item.txHash || '')))
    executionToastInitialized = true
    return
  }
  const confirmed = executions.find((item) => item.status === 'CONFIRMED' && !confirmedExecutionIds.has(String(item.executionId || item.txHash || '')))
  executions.filter((item) => item.status === 'CONFIRMED').forEach((item) => confirmedExecutionIds.add(String(item.executionId || item.txHash || '')))
  if (!confirmed) return
  const flyIds = Array.isArray(confirmed.flyIds) ? confirmed.flyIds.map(String).join(' · ') : 'FLY'
  const token = String(confirmed.tokenSymbol || 'TOKEN')
  const verb = String(confirmed.side || 'buy').toLowerCase() === 'sell' ? 'SOLD' : 'BOUGHT'
  const hash = typeof confirmed.txHash === 'string' && /^0x[a-fA-F0-9]{64}$/.test(confirmed.txHash) ? confirmed.txHash : null
  executionToast.innerHTML = `<strong>🪰 ${flyIds} ${verb} ${token}</strong><span>CONFIRMED ON ROBINHOOD CHAIN</span>${hash ? `<a href="https://robinhoodchain.blockscout.com/tx/${hash}" target="_blank" rel="noopener noreferrer">VIEW TX ↗</a>` : ''}`
  executionToast.hidden = false
  if (executionToastTimer !== null) window.clearTimeout(executionToastTimer)
  executionToastTimer = window.setTimeout(() => { executionToast.hidden = true }, 5500)
}

const intentLogPanel = document.createElement('section')
intentLogPanel.className = 'intent-log-panel'
intentLogPanel.setAttribute('aria-label', 'Fly buy and sell log')
intentLogPanel.innerHTML = `
  <div class="intent-log-header">
    <div>
      <div class="intent-log-kicker">FRUITFLY CAPITAL · TRADING LOG</div>
      <div class="intent-log-title">BUY / SELL ACTIVITY</div>
    </div>
    <div class="intent-log-mode">RECORDED TRADES<br>BEHAVIOR INTENTS</div>
  </div>
  <div class="intent-log-summary"><span class="intent-buy-count">BUY 0</span><span class="intent-sell-count">SELL 0</span><span class="intent-log-live">LIVE</span></div>
  <div class="intent-log-motion">FLIGHT · CRUISE 0 · DESCENDING 0 · LANDED 0 · CLOSEST —</div>
  <div class="intent-log-holdings"><div class="intent-log-holdings-heading"><span>FUND HOLDINGS</span><a href="/portfolio/">FULL PORTFOLIO →</a></div><div class="intent-log-holdings-list">Waiting for live portfolio data…</div></div>
  <div class="intent-log-tabs" role="tablist" aria-label="Trading log view"><button type="button" class="intent-log-tab is-active" data-log-view="behavior" role="tab" aria-selected="true">BEHAVIOR INTENTS</button><button type="button" class="intent-log-tab" data-log-view="trades" role="tab" aria-selected="false">BUY / SELL</button></div>
  <label class="intent-log-search"><span>SEARCH LOG</span><input type="search" placeholder="Token, fly, buy or sell…" aria-label="Search recorded trades" /></label>
  <div class="intent-log-list"></div>
`
app.append(intentLogPanel)
const intentLogList = intentLogPanel.querySelector<HTMLDivElement>('.intent-log-list')!
const intentBuyCount = intentLogPanel.querySelector<HTMLSpanElement>('.intent-buy-count')!
const intentSellCount = intentLogPanel.querySelector<HTMLSpanElement>('.intent-sell-count')!
const intentLogLive = intentLogPanel.querySelector<HTMLSpanElement>('.intent-log-live')!
const intentLogMotion = intentLogPanel.querySelector<HTMLDivElement>('.intent-log-motion')!
const intentLogHoldingsList = intentLogPanel.querySelector<HTMLDivElement>('.intent-log-holdings-list')!
const intentLogSearch = intentLogPanel.querySelector<HTMLInputElement>('.intent-log-search input')!
const intentLogTabs = Array.from(intentLogPanel.querySelectorAll<HTMLButtonElement>('.intent-log-tab'))
const seenIntentIds = new Set<string>()
const intentHistory: BehaviorTradeIntent[] = []
let buyIntentCount = 0
let sellIntentCount = 0
let intentSearchTerm = ''
let intentLogView: 'trades' | 'behavior' = 'behavior'
let focusCinematicOnIntent: ((intent: BehaviorTradeIntent) => void) | null = null

intentLogTabs.forEach((button) => {
  button.addEventListener('click', () => {
    intentLogView = button.dataset.logView === 'trades' ? 'trades' : 'behavior'
    intentLogTabs.forEach((candidate) => {
      const active = candidate === button
      candidate.classList.toggle('is-active', active)
      candidate.setAttribute('aria-selected', String(active))
    })
    renderIntentLog()
  })
})

intentLogSearch.addEventListener('input', () => {
  intentSearchTerm = intentLogSearch.value.trim().toLowerCase()
  renderIntentLog()
})

function recordBehaviorIntents(intents: readonly BehaviorTradeIntent[]) {
  for (const intent of intents) {
    if (seenIntentIds.has(intent.intentId)) continue
    seenIntentIds.add(intent.intentId)
    intentHistory.push(intent)
    if (intent.side === 'buy') buyIntentCount += 1
    else sellIntentCount += 1
    const isFresh = Number.isFinite(intent.observedAtMs) && Date.now() - intent.observedAtMs < 1500
    if (isFresh) sceneAudio.playTradeCue(intent.side)
    // Replayed history should populate the log without making a page reload
    // trigger an old camera cut. Only fresh biological events can focus the
    // cinematic director.
    if (Date.now() - intent.observedAtMs < 12000) focusCinematicOnIntent?.(intent)
  }
  if (intents.length > 0) {
    while (intentHistory.length > 200) intentHistory.shift()
    renderIntentLog()
  }
}

function flyHasHeldPosition(flyId: string) {
  const holding = currentFlyHolding(flyId)
  if (!holding || typeof holding !== 'object') return false
  const state = String((holding as Record<string, unknown>).state || '').toUpperCase()
  const amount = Number((holding as Record<string, unknown>).heldAmount)
  return (state === 'HOLDING' || state === 'DEPARTING') && Number.isFinite(amount) && amount > 0
}

function reconcileServerIntentHistory() {
  const autonomous = (brainSocket.portfolio()?.autonomous || {}) as Record<string, unknown>
  const sharedIntents = autonomous && Array.isArray(autonomous.behaviorIntents)
    ? autonomous.behaviorIntents as BehaviorTradeIntent[]
    : []
  if (sharedIntents.length === 0) return
  recordBehaviorIntents(sharedIntents)
}

function currentFlyHolding(flyId: string) {
  const sources = [
    brainSocket.portfolio()?.autonomous,
    brainSocket.swarmDecision()?.autonomousTrading,
  ]
  for (const source of sources) {
    if (!source || typeof source !== 'object') continue
    const flies = (source as Record<string, unknown>).flies
    if (!Array.isArray(flies)) continue
    const fly = flies.find((candidate) => candidate && typeof candidate === 'object' && (candidate as Record<string, unknown>).flyId === flyId) as Record<string, unknown> | undefined
    if (fly) return fly
  }
  return null
}

function formatTokenAmount(value: unknown) {
  const amount = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(amount) ? amount.toLocaleString(undefined, { maximumSignificantDigits: 8 }) : '—'
}

const zeroAddress = '0x0000000000000000000000000000000000000000'

function tradeActivityRecords() {
  const fund = brainSocket.portfolio()
  const autonomous = (fund?.autonomous || {}) as Record<string, unknown>
  const records: Array<Record<string, unknown> & { source: string; side: 'BUY' | 'SELL'; token: string; tokenAddress: string; flyLabel: string; timeMs: number }> = []
  const seen = new Set<string>()
  const add = (item: Record<string, unknown>, source: string) => {
    const status = String(item.status || '').toUpperCase()
    const txHash = String(item.txHash || item.tx_hash || '')
    // This tab is intentionally on-chain-only. Biological proposals, queued
    // intents, simulation fills, and blocked attempts belong elsewhere.
    if (!/^0x[a-fA-F0-9]{64}$/.test(txHash)) return
    if (!['BROADCAST', 'PENDING', 'CONFIRMED', 'REVERTED'].includes(status)) return
    const rawSide = String(item.side || item.type || '').toLowerCase()
    const tokenIn = String(item.inputToken || item.token_in || '')
    const tokenOut = String(item.token_out || '')
    const side: 'BUY' | 'SELL' = rawSide.includes('sell') || tokenOut.toLowerCase() === zeroAddress ? 'SELL' : 'BUY'
    const tokenAddress = String(item.tokenAddress || (side === 'BUY' ? tokenOut : tokenIn) || '')
    const habitat = environment.habitats.find((candidate) => candidate.state.tokenAddress?.toLowerCase() === tokenAddress.toLowerCase())
    const token = String(item.tokenSymbol || habitat?.state.label || (tokenAddress ? `${tokenAddress.slice(0, 6)}…${tokenAddress.slice(-4)}` : 'TOKEN'))
    const flyIds = Array.isArray(item.flyIds)
      ? item.flyIds.map(String)
      : String(item.neuroswarm_decision_id || '').split(',').map((value) => value.trim()).filter(Boolean)
    const executionId = String(item.executionId || item.execution_id || item.trade_id || '')
    const timeMs = Number(item.timestamp || item.timestampMs || item.timestamp_ms || item.createdMs || autonomous.observedAtMs || 0)
    const key = txHash || executionId || `${timeMs}:${side}:${tokenAddress}:${flyIds.join(',')}`
    if (seen.has(key)) return
    seen.add(key)
    records.push({ ...item, source, side, token, tokenAddress, flyLabel: flyIds.length ? flyIds.join(' · ') : 'SWARM', timeMs })
  }
  const mainnet = Array.isArray(autonomous.mainnetExecutions) ? autonomous.mainnetExecutions as Record<string, unknown>[] : []
  const trades = Array.isArray(fund?.recentTrades) ? fund.recentTrades as Record<string, unknown>[] : []
  mainnet.forEach((item) => add(item, 'MAINNET'))
  // Runtime BUY/SELL events do not prove execution and are excluded here.
  trades.forEach((item) => add(item, 'LEDGER'))
  return records.sort((left, right) => right.timeMs - left.timeMs)
}

function formatTradeInput(item: Record<string, unknown>) {
  const raw = item.inputAmount ?? item.amountIn ?? item.amount_in
  const inputToken = String(item.inputToken || item.token_in || '')
  if (inputToken.toLowerCase() === zeroAddress && raw !== undefined) {
    const amount = Number(raw) / 1e18
    return Number.isFinite(amount) ? `${amount.toLocaleString(undefined, { maximumSignificantDigits: 8 })} ETH` : '—'
  }
  return formatTokenAmount(raw)
}

function formatTradeOutput(item: Record<string, unknown>) {
  return formatTokenAmount(item.actualOutputAmount ?? item.amountOut ?? item.amount_out ?? item.expectedOutput)
}

function renderIntentLog() {
  const tradeRecords = tradeActivityRecords()
  const tradeBuyCount = tradeRecords.filter((item) => item.side === 'BUY').length
  const tradeSellCount = tradeRecords.filter((item) => item.side === 'SELL').length
  intentBuyCount.textContent = `BUY ${intentLogView === 'trades' ? tradeBuyCount : buyIntentCount}`
  intentSellCount.textContent = `SELL ${intentLogView === 'trades' ? tradeSellCount : sellIntentCount}`
  intentLogLive.textContent = brainSocket.getStatus() === 'connected' ? 'LIVE' : 'WAITING'
  const fund = brainSocket.portfolio()
  const positions = Array.isArray(fund?.positions) ? fund.positions as Record<string, unknown>[] : []
  const autonomous = (fund?.autonomous || {}) as Record<string, unknown>
  const observedPortfolio = Array.isArray(autonomous.actualWalletPortfolio) ? autonomous.actualWalletPortfolio as Record<string, unknown>[] : []
  const holdings = positions.length ? positions : observedPortfolio
  intentLogHoldingsList.replaceChildren()
  if (holdings.length === 0) {
    intentLogHoldingsList.textContent = 'No token positions held yet.'
  } else {
    for (const position of holdings.slice(0, 8)) {
      const item = document.createElement('span')
      const symbol = String(position.symbol || position.tokenSymbol || position.token_address || position.tokenAddress || 'TOKEN')
      const amount = formatTokenAmount(position.amount ?? position.observedAmount ?? position.balance)
      item.textContent = `${symbol} · ${amount}`
      intentLogHoldingsList.append(item)
    }
  }
  intentLogList.replaceChildren()
  if (intentLogView === 'behavior') {
    const visibleIntents = intentHistory.filter((intent) => {
      if (!intentSearchTerm) return true
      const habitat = environment.habitats.find((candidate) => candidate.state.id === intent.habitatId)
      return [intent.flyId, intent.side, intent.reason, intent.habitatId, habitat?.state.label].some((value) => String(value ?? '').toLowerCase().includes(intentSearchTerm))
    })
    if (visibleIntents.length === 0) {
      const empty = document.createElement('div')
      empty.className = 'intent-log-empty'
      empty.textContent = intentHistory.length === 0 ? 'No intents yet · contact + dwell creates BUY · departure creates SELL' : 'No matching intents.'
      intentLogList.append(empty)
      return
    }
    for (const intent of visibleIntents.slice(-40).reverse()) {
      const habitat = environment.habitats.find((candidate) => candidate.state.id === intent.habitatId)
      const token = habitat?.state.label || intent.habitatId
      const holding = currentFlyHolding(intent.flyId)
      const heldAmount = Number(holding?.heldAmount)
      const heldToken = String(holding?.tokenSymbol || token)
      const holdingDetails = Number.isFinite(heldAmount) && heldAmount > 0
        ? `HELD ${formatTokenAmount(heldAmount)} ${heldToken}`
        : intent.side === 'buy'
          ? `TARGET ${(intent.portfolioWeight * 100).toFixed(2)}% · AWAITING EXECUTION`
          : `SELL PROPOSAL · NO CONFIRMED HOLDING`
      const dwell = Number(intent.metrics?.dwellSeconds ?? 0)
      const distance = Number(intent.metrics?.distanceM ?? 0)
      const confidence = Math.round(Number(intent.confidence || 0) * 100)
      const row = document.createElement('div')
      row.className = `intent-log-row ${intent.side}`
      const time = new Date(intent.observedAtMs).toLocaleTimeString([], { hour12: false })
      row.innerHTML = '<div class="intent-log-row-top"><strong></strong><span></span><em>PROPOSAL</em></div><div class="intent-log-token"></div><div class="intent-log-holding"></div><div class="intent-log-details"></div>'
      row.querySelector('strong')!.textContent = `${intent.side.toUpperCase()} INTENT`
      row.querySelector('span')!.textContent = `${time} · ${intent.flyId}`
      row.querySelector('.intent-log-token')!.textContent = token
      row.querySelector('.intent-log-holding')!.textContent = holdingDetails
      row.querySelector('.intent-log-details')!.textContent = `${intent.reason.toUpperCase()} · dwell ${dwell.toFixed(2)}s · ${distance.toFixed(3)}m · confidence ${confidence}%`
      intentLogList.append(row)
    }
    return
  }
  const visibleTrades = tradeRecords.filter((item) => {
    if (!intentSearchTerm) return true
    return [item.side, item.token, item.tokenAddress, item.flyLabel, item.status, item.source].some((value) => String(value ?? '').toLowerCase().includes(intentSearchTerm))
  })
  if (visibleTrades.length === 0) {
    const empty = document.createElement('div')
    empty.className = 'intent-log-empty'
    empty.textContent = tradeRecords.length === 0 ? `No on-chain buys or sells recorded yet · ${buyIntentCount} BUY / ${sellIntentCount} SELL proposals in Behavior Intents.` : 'No matching buys or sells.'
    intentLogList.append(empty)
    return
  }
  for (const trade of visibleTrades.slice(0, 40)) {
    const row = document.createElement('div')
    row.className = `intent-log-row ${trade.side === 'SELL' ? 'sell' : 'buy'}`
    const time = trade.timeMs > 0 ? new Date(trade.timeMs).toLocaleTimeString([], { hour12: false }) : '—'
    const status = String(trade.status || (trade.source === 'MAINNET' ? 'BROADCAST' : 'RECORDED')).toUpperCase()
    row.innerHTML = '<div class="intent-log-row-top"><strong></strong><span></span><em></em></div><div class="intent-log-token"></div><div class="intent-log-holding"></div><div class="intent-log-details"></div>'
    row.querySelector('strong')!.textContent = `${trade.side} ${trade.token}`
    row.querySelector('span')!.textContent = `${time} · ${trade.flyLabel}`
    row.querySelector('em')!.textContent = `${trade.source} · ${status}`
    row.querySelector('.intent-log-token')!.textContent = `${formatTradeInput(trade)} → ${formatTradeOutput(trade)} ${trade.token}`
    row.querySelector('.intent-log-holding')!.textContent = trade.tokenAddress ? `${trade.tokenAddress.slice(0, 10)}…${trade.tokenAddress.slice(-6)}` : 'TOKEN ADDRESS PENDING'
    const details = row.querySelector('.intent-log-details')!
    const hash = String(trade.txHash || trade.tx_hash || '')
    if (/^0x[a-fA-F0-9]{64}$/.test(hash)) {
      const link = document.createElement('a')
      link.href = `https://robinhoodchain.blockscout.com/tx/${hash}`
      link.target = '_blank'
      link.rel = 'noopener noreferrer'
      link.textContent = `VIEW ON BLOCKSCOUT ↗ · ${hash.slice(0, 14)}…`
      details.replaceChildren(link)
    } else {
      details.textContent = 'On-chain hash unavailable'
    }
    intentLogList.append(row)
  }
}

const status = document.createElement('div')
status.className = 'socket-status debug-only'
app.append(status)
const logButton = document.createElement('button')
logButton.className = 'log-button debug-only'
logButton.textContent = 'DOWNLOAD SELECTED FLY LOG'
app.append(logButton)
const scene = new Scene()
const renderer = new WebGLRenderer({ canvas, antialias: false, powerPreference: 'high-performance' })
renderer.setPixelRatio(1)
renderer.setSize(window.innerWidth, window.innerHeight)
renderer.shadowMap.enabled = false
let mobileViewport = window.matchMedia?.('(max-width: 600px)').matches ?? false

const environment = new Environment()
environment.setupLighting(scene)
const atmosphere = new SceneAtmosphere()
scene.add(atmosphere.group)

const causalStatus = document.createElement('div')
causalStatus.className = 'causal-status debug-only'
causalStatus.textContent = 'CAUSE MAP · selecting a fly…'
app.append(causalStatus)

const populationStatus = document.createElement('div')
populationStatus.className = 'population-status debug-only'
populationStatus.innerHTML = `<strong>FRUITFLY CAPITAL</strong><br>VISUAL FLIES ${VISUAL_FLY_COUNT} · PRIMARY SIGNALS ${SWARM_SIZE} · BODIES / SIGNAL ${BODIES_PER_BRAIN}`
app.append(populationStatus)

const brainUrl = resolveBrainWebSocketUrl(import.meta.env.VITE_BRAIN_WS_URL)
const brainSocket = new BrainSocket(brainUrl)
const flightLog = new FlightLogger()
renderIntentLog()
const brainUpdateHz = Math.max(1, Number(import.meta.env.VITE_BRAIN_UPDATE_HZ ?? 2) || 2)
let selectedIndex = 0

function updatePortfolioSummary() {
  const fund = brainSocket.portfolio()
  if (!fund) return
  reconcileServerIntentHistory()
  const wallet = (fund.wallet || {}) as Record<string, unknown>
  const legacyPositions = Array.isArray(fund.positions) ? fund.positions as Record<string, unknown>[] : []
  const autonomous = (fund.autonomous || {}) as Record<string, unknown>
  const actualWalletPortfolio = Array.isArray(autonomous.actualWalletPortfolio)
    ? autonomous.actualWalletPortfolio as Record<string, unknown>[]
    : []
  const observedTokenPositions = actualWalletPortfolio.filter((position) => {
    const address = String(position.tokenAddress || position.token_address || '')
    const amount = Number(position.observedAmount ?? position.amount ?? 0)
    return /^0x[a-fA-F0-9]{40}$/.test(address)
      && address.toLowerCase() !== zeroAddress.toLowerCase()
      && Number.isFinite(amount)
      && amount > 0
  })
  const positions = legacyPositions.length ? legacyPositions : observedTokenPositions
  const available = typeof wallet.availableToTrade === 'number' ? `${wallet.availableToTrade.toFixed(6)} ETH` : '—'
  const walletTotal = typeof wallet.nativeBalance === 'number' ? `${wallet.nativeBalance.toFixed(6)} ETH` : '—'
  const returnPct = typeof autonomous.portfolioReturnPct === 'number'
    ? `${autonomous.portfolioReturnPct >= 0 ? '+' : ''}${autonomous.portfolioReturnPct.toFixed(2)}%`
    : null
  portfolioSummaryFields.wallet.textContent = walletTotal
  portfolioSummaryFields.available.textContent = available
  portfolioSummaryFields.positions.textContent = `${positions.length}`
  portfolioSummaryFields.returnField.hidden = returnPct === null
  if (returnPct !== null) portfolioSummaryFields.return.textContent = returnPct
  const walletAddress = String(wallet.address || fund.treasuryAddress || '')
  if (/^0x[a-fA-F0-9]{40}$/.test(walletAddress)) {
    portfolioSummaryFields.walletLink.href = `https://robinhoodchain.blockscout.com/address/${walletAddress}`
  }
  portfolioSummaryFields.holdings.textContent = positions.length
    ? positions.slice(0, 4).map((position) => String(position.symbol || position.tokenSymbol || position.token_address || position.tokenAddress || 'TOKEN')).join(' · ')
    : 'No token positions yet · proposals remain visible in the behavior log'
  updateExecutionToast()
  renderIntentLog()
}

// The pilot population is deliberately a numbered set of real CNS agents.
// Additional bodies are explicitly render-only followers of these primaries.
const population = new FlyPopulation({ brainSocket, brainUpdateHz, size: SWARM_SIZE })
const { agents, renderers: flyRenderers, followers } = population
const followerRenderers = followers.map((follower) => follower.renderer)
const visualRenderers = [...flyRenderers, ...followerRenderers]

const flyStateStorageKey = 'ffc.primaryFlyState.v1'
type StoredFlyState = Record<string, ReturnType<(typeof agents)[number]['snapshot']>>

function restorePrimaryFlyState() {
  try {
    const saved = JSON.parse(window.localStorage.getItem(flyStateStorageKey) ?? 'null') as StoredFlyState | null
    if (!saved || typeof saved !== 'object') return
    agents.forEach((agent) => {
      const snapshot = saved[agent.id]
      if (snapshot?.position && snapshot?.quaternion && snapshot?.velocity && snapshot?.angularVelocity) agent.restore(snapshot)
    })
  } catch {
    // A corrupt browser snapshot must never prevent the scene from starting.
  }
}

function persistPrimaryFlyState() {
  const saved = Object.fromEntries(agents.map((agent) => [agent.id, agent.snapshot()]))
  window.localStorage.setItem(flyStateStorageKey, JSON.stringify(saved))
}

restorePrimaryFlyState()

const world = new World(scene, agents, environment)
visualRenderers.forEach((flyRenderer) => world.add(flyRenderer.group))
// Only the primary bodies enter this observer. Render followers are visual
// embodiments and must never become extra portfolio votes or trade events.
// A qualifying buy requires sustained contact, not a transient startup
// overlap. Keep this client threshold aligned with the server observer.
// Slow the proposal cadence: contact must persist for eight seconds, a held
// fly must remain outside for six seconds before SELL is logged, and each fly
// has one active commitment plus a five-minute post-intent cooldown. The
// trading runtime still applies its independent 120-second minimum hold.
const swarmObserver = new SwarmObserver(SWARM_SIZE, 8, 0.0005, 6, 120, 300)

function updateFlightMotionStatus() {
  const cruise = agents.filter((agent) => agent.landingState === 'cruise').length
  const descending = agents.filter((agent) => agent.landingState === 'descending').length
  const landed = agents.filter((agent) => agent.landingState === 'landed').length
  const ground = agents.filter((agent) => agent.body.contact.ground).length
  const averageAltitude = agents.reduce((total, agent) => total + agent.body.position.y, 0) / Math.max(1, agents.length)
  const averageSpeed = agents.reduce((total, agent) => total + agent.body.velocity.length(), 0) / Math.max(1, agents.length)
  const maxOdor = agents.reduce((maximum, agent) => Math.max(maximum, agent.sensors.odor.concentration), 0)
  let closest = Number.POSITIVE_INFINITY
  for (const agent of agents) {
    for (const habitat of environment.habitats) {
      const distance = agent.body.position.distanceTo(habitat.group.position)
      if (Number.isFinite(distance)) closest = Math.min(closest, distance)
    }
  }
  intentLogMotion.textContent = `FLIGHT · CRUISE ${cruise} · DESCENDING ${descending} · LANDED ${landed} · GROUND ${ground} · ALT ${averageAltitude.toFixed(2)}m · SPEED ${averageSpeed.toFixed(2)}m/s · ODOR ${maxOdor.toFixed(2)} · CLOSEST ${Number.isFinite(closest) ? `${closest.toFixed(3)}m` : '—'}`
}
updateFlightMotionStatus()

const bodyStatus = document.createElement('div')
bodyStatus.className = 'body-status debug-only'
bodyStatus.textContent = 'BODY · loading canonical Flybody XML + OBJ assets'
app.append(bodyStatus)
let canonicalBodiesReady = false
let canonicalReadyCount = 0
let canonicalFinishedCount = 0
// Do not make the product view wait for the full visual cohort. The loader
// shares the expensive template, but cloning every render-only follower can
// still take several frames on a browser. One canonical body is enough to
// release the scene; the rest become visible as they finish.
visualRenderers.forEach((flyRenderer) => {
  void flyRenderer.ready.then(() => {
    canonicalFinishedCount += 1
    if (flyRenderer.assetStatus === 'canonical') canonicalReadyCount += 1
    const firstRenderer = flyRenderers[0]
    if (!canonicalBodiesReady && flyRenderer.assetStatus === 'canonical') {
      canonicalBodiesReady = true
      bodyStatus.textContent = `BODY · canonical Flybody ready · ${firstRenderer?.meshCount ?? flyRenderer.meshCount} XML geoms · loading remaining copies…`
    }
    if (canonicalFinishedCount === visualRenderers.length) {
      const allCanonical = canonicalReadyCount === visualRenderers.length
      bodyStatus.textContent = `BODY · ${allCanonical ? `canonical Flybody loaded · ${firstRenderer?.meshCount ?? 0} XML geoms × ${VISUAL_FLY_COUNT} visual flies` : 'canonical Flybody asset error · see console'} · ${SWARM_SIZE} primary signals · ${BODIES_PER_BRAIN} bodies/signal`
    }
  })
})
// If an asset request is delayed by the local dev server, never block the
// playable scene indefinitely. The lightweight renderer fallback is already
// visible and the canonical mesh will replace it whenever it arrives.
window.setTimeout(() => {
  if (canonicalBodiesReady) return
  canonicalBodiesReady = true
  bodyStatus.textContent = `BODY · loading canonical Flybody in background · ${SWARM_SIZE} primary signals · ${BODIES_PER_BRAIN} bodies/signal`
}, 3500)

const debug = new DebugRenderer(app, 'FLY #001', 'right')
let debugPanelVisible = false
debug.setPanelVisible(debugPanelVisible)
world.add(debug.group)

const brainActivityPanel = new BrainActivityPanel(app)


const free = new FreeCamera(renderer.domElement)
const follow = new FollowCamera()
const firstPerson = new FirstPersonCamera()
const side = new SideCamera()
const presentation = new PresentationCamera()
const cameras = [free.camera, follow.camera, firstPerson.camera, side.camera, presentation.camera] as const
// Start in the user-controlled free orbit. Cinematic views remain opt-in via
// the camera panel; they should never take over the first view.
let cameraIndex = 0
let activeCamera = cameras[cameraIndex] ?? cameras[0]!
const cameraFocus = new Vector3()
const pipeline = new PostProcessingPipeline(renderer, scene, activeCamera)
let renderQuality: RenderQuality = mobileViewport ? 'performance' : 'demo'
const storedQuality = window.localStorage.getItem('ffc.renderQuality')
if (storedQuality === 'demo' || storedQuality === 'performance') renderQuality = storedQuality
pipeline.setQuality(renderQuality)
// The public scene opens with a slow director pass. The selector still lets
// visitors switch to overview, fly vision, or free orbit at any time.
presentation.setMode('director')

const performanceStatus = document.createElement('div')
performanceStatus.className = 'performance-status debug-only'
performanceStatus.textContent = 'PERF · measuring…'
app.append(performanceStatus)

// Keep the public view calm. Detailed telemetry remains in the DOM for
// developer inspection, but there is no user-facing debug switch.
app.classList.add('presentation-demo')

const cameraTargetPanel = document.createElement('div')
cameraTargetPanel.className = 'camera-target-panel'
cameraTargetPanel.setAttribute('aria-label', 'Camera controls')
let cinematicTimer: number | null = null
const cameraTargetLabel = document.createElement('span')
cameraTargetLabel.textContent = 'VIEW'
cameraTargetPanel.append(cameraTargetLabel)
const cameraModeSelect = document.createElement('select')
cameraModeSelect.setAttribute('aria-label', 'Camera view')
for (const [label, value] of [['CINEMATIC', 'cinematic'], ['OVERVIEW', 'overview'], ['FLY VISION', 'vision'], ['FREE ORBIT', 'free']] as Array<[string, string]>) {
  const option = document.createElement('option')
  option.value = value
  option.textContent = label
  cameraModeSelect.append(option)
}
cameraModeSelect.value = 'cinematic'
cameraModeSelect.addEventListener('change', () => {
  stopCinematic()
  if (cameraModeSelect.value === 'cinematic') {
    presentation.setMode('director')
    cameraIndex = 4
    cinematicTimer = window.setInterval(() => setSelectedFly((selectedIndex + 1) % agents.length, false), 12000)
  } else if (cameraModeSelect.value === 'overview') {
    presentation.setMode('overview')
    cameraIndex = 4
  } else if (cameraModeSelect.value === 'vision') {
    cameraIndex = 2
  } else {
    cameraIndex = 0
  }
})
cameraTargetPanel.append(cameraModeSelect)
cameraIndex = 4
cinematicTimer = window.setInterval(() => setSelectedFly((selectedIndex + 1) % agents.length, false), 12000)
const nextFlyButton = document.createElement('button')
nextFlyButton.textContent = 'NEXT FLY'
nextFlyButton.addEventListener('click', () => setSelectedFly((selectedIndex + 1) % agents.length, false))
cameraTargetPanel.append(nextFlyButton)
app.append(cameraTargetPanel)

focusCinematicOnIntent = (intent) => {
  if (cameraIndex !== 4 || cameraModeSelect.value !== 'cinematic') return
  const flyIndex = agents.findIndex((agent) => agent.id === intent.flyId)
  if (flyIndex >= 0) setSelectedFly(flyIndex, false)
  presentation.focusOnTradeEvent(intent.flyId, intent.habitatId, intent.side)
}

const sceneControls = document.createElement('aside')
sceneControls.className = 'scene-controls debug-only'
sceneControls.setAttribute('aria-label', 'Scene position controls')
sceneControls.innerHTML = `
  <div class="scene-controls-heading">PLAY SPACE</div>
  <div class="scene-controls-note">Floor only · 6m × 6m · saved automatically</div>
  <div class="scene-controls-note">Draw the complete playable scene. Habitats and flies stay inside it.</div>
  <div class="habitat-size-row"><span>ALL HABITATS</span><input type="range" min="0.5" max="1.35" step="0.05"><output></output></div>
  <div class="boundary-actions"><button class="boundary-draw" type="button">DRAW GAME SCENE</button><button class="boundary-clear" type="button">CLEAR SCENE</button></div>
  <div class="boundary-status">No custom fly area · default arena active</div>
`
app.append(sceneControls)
const habitatSizeInput = sceneControls.querySelector<HTMLInputElement>('.habitat-size-row input')!
const habitatSizeOutput = sceneControls.querySelector<HTMLOutputElement>('.habitat-size-row output')!
const boundaryDrawButton = sceneControls.querySelector<HTMLButtonElement>('.boundary-draw')!
const boundaryClearButton = sceneControls.querySelector<HTMLButtonElement>('.boundary-clear')!
const boundaryStatus = sceneControls.querySelector<HTMLDivElement>('.boundary-status')!
function renderSceneControls() {
  const habitatScale = environment.getHabitatVisualScale()
  habitatSizeInput.value = String(habitatScale)
  habitatSizeOutput.value = `${habitatScale.toFixed(2)}×`
}
renderSceneControls()

habitatSizeInput.addEventListener('input', () => {
  environment.setHabitatVisualScale(Number(habitatSizeInput.value))
  renderSceneControls()
})

// The editor draws in the same X/Z metre space used by the fly physics. The
// result is both a visible floor boundary and a real containment boundary for
// primary and follower bodies, so the tool changes the world rather than just
// decorating it.
const boundaryStorageKey = 'ffc.gameSceneBoundary.v2'
const boundaryPlane = new Plane(new Vector3(0, 1, 0), 0)
const boundaryRaycaster = new Raycaster()
const boundaryPointer = new Vector2()
const boundaryGroup = new Object3D()
boundaryGroup.name = 'ManualFlyBoundary'
scene.add(boundaryGroup)
let boundaryPoints = readBoundaryPoints()
let draftBoundary: Vector3[] = []
let draftBoundaryClosed = false
let drawingBoundary = false
let boundaryLine: Line | null = null
let boundaryFill: Mesh | null = null
let boundaryDots: Points | null = null
const DRAW_HALF_EXTENT = PRESENTATION_SCENE_HALF_EXTENT - 0.06
world.setFlyBoundary(boundaryPoints)
environment.setWorldBoundary(boundaryPoints)

function readBoundaryPoints() {
  try {
    const saved = JSON.parse(window.localStorage.getItem(boundaryStorageKey) ?? 'null') as Array<{ x?: number; z?: number }> | null
    if (!Array.isArray(saved) || saved.length < 3) return []
    return saved
      .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.z))
      .map((point) => new Vector3(clamp(point.x!, -DRAW_HALF_EXTENT, DRAW_HALF_EXTENT), 0, clamp(point.z!, -DRAW_HALF_EXTENT, DRAW_HALF_EXTENT)))
  } catch {
    return []
  }
}

function persistBoundary() {
  window.localStorage.setItem(boundaryStorageKey, JSON.stringify(boundaryPoints.map((point) => ({ x: point.x, z: point.z }))))
}

function setBoundary(points: readonly Vector3[]) {
  boundaryPoints = points.map((point) => new Vector3(clamp(point.x, -DRAW_HALF_EXTENT, DRAW_HALF_EXTENT), 0, clamp(point.z, -DRAW_HALF_EXTENT, DRAW_HALF_EXTENT)))
  draftBoundary = []
  draftBoundaryClosed = false
  draftScreenPoints = []
  updateDraftScreenPath()
  persistBoundary()
  world.setFlyBoundary(boundaryPoints)
  environment.setWorldBoundary(boundaryPoints)
  rebuildBoundaryVisual(boundaryPoints, true)
  cameraIndex = 0
  free.frameBoundary(boundaryPoints)
  renderBoundaryStatus()
}

function clearBoundary() {
  boundaryPoints = []
  draftBoundary = []
  draftBoundaryClosed = false
  draftScreenPoints = []
  updateDraftScreenPath()
  window.localStorage.removeItem(boundaryStorageKey)
  world.setFlyBoundary(null)
  environment.setWorldBoundary(null)
  rebuildBoundaryVisual([])
  renderBoundaryStatus()
}

function rebuildBoundaryVisual(points: readonly Vector3[], closed = false) {
  if (boundaryLine) {
    boundaryGroup.remove(boundaryLine)
    boundaryLine.geometry.dispose()
    ;(boundaryLine.material as LineBasicMaterial).dispose()
    boundaryLine = null
  }
  if (boundaryFill) {
    boundaryGroup.remove(boundaryFill)
    boundaryFill.geometry.dispose()
    ;(boundaryFill.material as MeshBasicMaterial).dispose()
    boundaryFill = null
  }
  if (boundaryDots) {
    boundaryGroup.remove(boundaryDots)
    boundaryDots.geometry.dispose()
    ;(boundaryDots.material as PointsMaterial).dispose()
    boundaryDots = null
  }
  const dotPoints = points.map((point) => new Vector3(point.x, 0.02, point.z))
  boundaryDots = new Points(new BufferGeometry().setFromPoints(dotPoints), new PointsMaterial({ color: 0xd9fff5, size: 0.026, sizeAttenuation: false, transparent: true, opacity: 1, depthTest: false }))
  boundaryDots.name = 'ManualFlyBoundaryPoints'
  boundaryDots.renderOrder = 31
  boundaryGroup.add(boundaryDots)
  if (points.length < 2) return
  const linePoints = points.map((point) => new Vector3(point.x, 0.014, point.z))
  if (closed && points.length >= 3) linePoints.push(linePoints[0]!.clone())
  boundaryLine = new Line(new BufferGeometry().setFromPoints(linePoints), new LineBasicMaterial({ color: 0x8ffff0, transparent: true, opacity: 1, depthTest: false }))
  boundaryLine.name = 'ManualFlyBoundaryOutline'
  boundaryLine.renderOrder = 30
  boundaryGroup.add(boundaryLine)
  if (!closed || points.length < 3) return
  const shape = new Shape()
  shape.moveTo(points[0]!.x, points[0]!.z)
  for (const point of points.slice(1)) shape.lineTo(point.x, point.z)
  shape.closePath()
  boundaryFill = new Mesh(new ShapeGeometry(shape), new MeshBasicMaterial({ color: 0x38d9b2, transparent: true, opacity: 0.08, depthWrite: false, depthTest: false, side: 2 }))
  boundaryFill.name = 'ManualFlyBoundaryFill'
  boundaryFill.rotation.x = Math.PI / 2
  boundaryFill.position.y = 0.011
  boundaryFill.renderOrder = 29
  boundaryGroup.add(boundaryFill)
}

function renderBoundaryStatus() {
  boundaryStatus.textContent = boundaryPoints.length >= 3
    ? `Game scene boundary active · ${boundaryPoints.length} points · saved`
    : 'No game scene boundary · default scene active'
}

function groundPointFromEvent(event: PointerEvent) {
  const bounds = canvas.getBoundingClientRect()
  boundaryPointer.set(
    ((event.clientX - bounds.left) / bounds.width) * 2 - 1,
    -((event.clientY - bounds.top) / bounds.height) * 2 + 1,
  )
  activeCamera.updateMatrixWorld(true)
  boundaryRaycaster.setFromCamera(boundaryPointer, activeCamera)
  const point = new Vector3()
  return boundaryRaycaster.ray.intersectPlane(boundaryPlane, point)
}

function closeDraftIfAtStart(event: PointerEvent, point: Vector3 | null) {
  const start = draftBoundary[0]
  const startScreen = draftScreenPoints[0]
  if (draftBoundaryClosed || !start || !startScreen || draftBoundary.length < 3 || !point) return false
  const screenDistance = Math.hypot(event.clientX - startScreen[0], event.clientY - startScreen[1])
  if (screenDistance > 24 && point.distanceTo(start) > 0.065) return false
  // Snap both representations to the exact first point. This prevents a
  // small final gap when the browser's last pointermove is not delivered
  // before pointerup.
  draftBoundary[draftBoundary.length - 1] = start.clone()
  draftScreenPoints[draftScreenPoints.length - 1] = [startScreen[0], startScreen[1]]
  draftBoundaryClosed = true
  rebuildBoundaryVisual(draftBoundary, true)
  updateDraftScreenPath()
  boundaryStatus.textContent = 'Line closed exactly at its start · release to save this game scene.'
  return true
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

function setBoundaryDrawing(enabled: boolean) {
  drawingBoundary = enabled
  if (!enabled && draftBoundaryClosed) {
    draftBoundary = []
    draftBoundaryClosed = false
    draftScreenPoints = []
  }
  boundaryDrawButton.textContent = enabled ? 'CLOSE & USE REGION' : 'DRAW GAME SCENE'
  boundaryDrawButton.setAttribute('aria-pressed', String(enabled))
  canvas.classList.toggle('drawing-boundary', enabled)
  if (!enabled) rebuildBoundaryVisual(draftBoundary.length >= 2 ? draftBoundary : boundaryPoints, draftBoundary.length >= 2 ? draftBoundaryClosed : true)
  updateDraftScreenPath()
  boundaryStatus.textContent = enabled
    ? 'Draw one line, return to its start, then release to close and save.'
    : boundaryPoints.length >= 3
      ? `Game scene boundary active · ${boundaryPoints.length} points · saved`
      : draftBoundary.length >= 2
        ? 'Line still open · drag again to continue, then return to its start.'
        : 'No game scene boundary · default scene active'
}

function closeDraftManually() {
  if (!drawingBoundary || draftBoundary.length < 3) {
    boundaryStatus.textContent = 'Draw at least three points before closing the region.'
    return
  }
  const start = draftBoundary[0]
  const startScreen = draftScreenPoints[0]
  if (!start || !startScreen) return
  draftBoundary[draftBoundary.length - 1] = start.clone()
  draftScreenPoints[draftScreenPoints.length - 1] = [startScreen[0], startScreen[1]]
  draftBoundaryClosed = true
  rebuildBoundaryVisual(draftBoundary, true)
  updateDraftScreenPath()
  setBoundary(draftBoundary)
  setBoundaryDrawing(false)
}

boundaryDrawButton.addEventListener('click', () => {
  if (drawingBoundary) {
    closeDraftManually()
    return
  }
  closeTokenPopup()
  setBoundaryDrawing(true)
})
boundaryClearButton.addEventListener('click', () => {
  setBoundaryDrawing(false)
  clearBoundary()
})
rebuildBoundaryVisual(boundaryPoints, true)
renderBoundaryStatus()

const tokenPopup = document.createElement('div')
tokenPopup.className = 'token-popup-backdrop'
tokenPopup.hidden = true
tokenPopup.innerHTML = `
  <section class="token-popup" role="dialog" aria-modal="true" aria-labelledby="token-popup-title">
    <button class="token-popup-close" type="button" aria-label="Close token details">CLOSE</button>
    <div class="token-popup-kicker">TOKEN HABITAT · LIVE SNAPSHOT</div>
    <h2 id="token-popup-title" class="token-popup-title"></h2>
    <div class="token-popup-subtitle"></div>
    <a class="token-popup-dex-link" target="_blank" rel="noopener noreferrer">OPEN IN DEXSCREENER ↗</a>
    <div class="token-popup-grid">
      <div><span>PRICE</span><strong data-token-metric="price">—</strong></div>
      <div><span>MARKET CAP</span><strong data-token-metric="marketCap">—</strong></div>
      <div><span>FDV</span><strong data-token-metric="fdv">—</strong></div>
      <div><span>LIQUIDITY</span><strong data-token-metric="liquidity">—</strong></div>
      <div><span>24H VOLUME</span><strong data-token-metric="volume24h">—</strong></div>
      <div><span>MCAP / LIQUIDITY</span><strong data-token-metric="marketCapToLiquidity">—</strong></div>
      <div><span>BUY / SELL 5M</span><strong data-token-metric="flow">—</strong></div>
      <div><span>ATTRACTIVE ODOR</span><strong data-token-metric="odor">—</strong></div>
    </div>
    <div class="token-popup-section-label">WHAT THE FLIES SENSE</div>
    <div class="token-popup-sense">
      <span data-token-sense="semantic"></span>
      <span data-token-sense="activity"></span>
      <span data-token-sense="risk"></span>
    </div>
    <div class="token-popup-footnote">The habitat is updated from the market feed. Fly behaviour is autonomous; this popup does not steer the swarm.</div>
  </section>
`
app.append(tokenPopup)
const tokenPopupElement = tokenPopup.querySelector<HTMLElement>('.token-popup')!
const tokenPopupTitle = tokenPopup.querySelector<HTMLElement>('.token-popup-title')!
const tokenPopupSubtitle = tokenPopup.querySelector<HTMLElement>('.token-popup-subtitle')!
const tokenPopupDexLink = tokenPopup.querySelector<HTMLAnchorElement>('.token-popup-dex-link')!
const tokenPopupClose = tokenPopup.querySelector<HTMLButtonElement>('.token-popup-close')!
const tokenPopupMetrics = Object.fromEntries(
  Array.from(tokenPopup.querySelectorAll<HTMLElement>('[data-token-metric]')).map((element) => [element.dataset.tokenMetric!, element]),
) as Record<string, HTMLElement>
const tokenPopupSense = Object.fromEntries(
  Array.from(tokenPopup.querySelectorAll<HTMLElement>('[data-token-sense]')).map((element) => [element.dataset.tokenSense!, element]),
) as Record<string, HTMLElement>

function closeTokenPopup() {
  tokenPopup.hidden = true
}

tokenPopupClose.addEventListener('click', closeTokenPopup)
tokenPopup.addEventListener('click', (event) => {
  if (event.target === tokenPopup) closeTokenPopup()
})
window.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeTokenPopup()
})

function openTokenPopup(habitat: Environment['habitats'][number]) {
  const state = habitat.state
  tokenPopupTitle.textContent = state.label || state.id
  tokenPopupSubtitle.textContent = [state.chainId?.toUpperCase(), state.dexId, state.pairAddress ?? state.id]
    .filter(Boolean)
    .join(' · ')
  const dexscreenerUrl = state.dexscreenerUrl ?? buildDexscreenerUrl(state)
  tokenPopupDexLink.href = dexscreenerUrl ?? '#'
  tokenPopupDexLink.hidden = !dexscreenerUrl
  setPopupMetric('price', formatUsd(signalNumber(state, 'market.priceUsd', state.market.priceUsd)))
  setPopupMetric('marketCap', formatUsd(signalNumber(state, 'market.marketCapUsd', state.market.marketCapUsd)))
  setPopupMetric('fdv', formatUsd(signalNumber(state, 'market.fdvUsd', state.market.fdvUsd)))
  setPopupMetric('liquidity', formatUsd(signalNumber(state, 'liquidity.usd', state.liquidity.liquidityUsd)))
  setPopupMetric('volume24h', formatUsd(signalNumber(state, 'market.volume24hUsd', state.market.volume24hUsd)))
  setPopupMetric('marketCapToLiquidity', formatRatio(signalNumber(state, 'liquidity.marketCapToLiquidity', state.liquidity.marketCapToLiquidity)))
  setPopupMetric('flow', `${state.flow.buyCount5m} / ${state.flow.sellCount5m}`)
  setPopupMetric('odor', `${Math.round(habitat.properties.attractiveOdor * 100)}%`)
  tokenPopupSense.semantic!.textContent = `SOURCE: ${habitat.properties.semanticType.toUpperCase()}`
  tokenPopupSense.activity!.textContent = `ACTIVITY: ${Math.round(habitat.properties.visualMotionIntensity * 100)}%`
  tokenPopupSense.risk!.textContent = `RISK / CHAOS: ${Math.round(habitat.properties.chaos * 100)}%`
  tokenPopup.hidden = false
  tokenPopupClose.focus()
}

function buildDexscreenerUrl(state: TokenState) {
  const chainId = state.chainId?.trim().toLowerCase()
  const address = state.pairAddress ?? state.tokenAddress
  if (!chainId || !address) return null
  return `https://dexscreener.com/${encodeURIComponent(chainId)}/${encodeURIComponent(address)}`
}

function setPopupMetric(name: string, value: string) {
  const element = tokenPopupMetrics[name]
  if (element) element.textContent = value
}

function signalNumber(state: TokenState, name: string, fallback: number | null | undefined) {
  const value = state.signals.find((signal) => signal.name === name)?.value
  return typeof value === 'number' ? value : fallback
}

function formatUsd(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  if (Math.abs(value) >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`
  if (Math.abs(value) >= 1_000) return `$${(value / 1_000).toFixed(1)}K`
  if (Math.abs(value) >= 1) return `$${value.toFixed(2)}`
  return `$${value.toPrecision(4)}`
}

function formatRatio(value: number | null | undefined) {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${value.toFixed(2)}×`
}

const tokenPicker = new Raycaster()
const tokenPointer = new Vector2()
let tokenPointerDown: { x: number; y: number } | null = null
canvas.addEventListener('pointerdown', (event) => {
  if (drawingBoundary) {
    const point = groundPointFromEvent(event)
    if (point) {
      const next = new Vector3(clamp(point.x, -DRAW_HALF_EXTENT, DRAW_HALF_EXTENT), 0, clamp(point.z, -DRAW_HALF_EXTENT, DRAW_HALF_EXTENT))
      if (draftBoundary.length === 0 || draftBoundaryClosed) {
        draftBoundary = [next]
        draftBoundaryClosed = false
        draftScreenPoints = [[event.clientX, event.clientY]]
      } else if (draftBoundary[draftBoundary.length - 1]!.distanceTo(next) >= 0.005) {
        draftBoundary.push(next)
        draftScreenPoints.push([event.clientX, event.clientY])
      }
      rebuildBoundaryVisual(draftBoundary, draftBoundaryClosed)
      updateDraftScreenPath()
      canvas.setPointerCapture(event.pointerId)
    }
    event.preventDefault()
    return
  }
  tokenPointerDown = { x: event.clientX, y: event.clientY }
})
canvas.addEventListener('pointermove', (event) => {
  if (!drawingBoundary || draftBoundary.length === 0) return
  const point = groundPointFromEvent(event)
  const next = point && new Vector3(clamp(point.x, -DRAW_HALF_EXTENT, DRAW_HALF_EXTENT), 0, clamp(point.z, -DRAW_HALF_EXTENT, DRAW_HALF_EXTENT))
  const last = draftBoundary[draftBoundary.length - 1]
  if (!next || !last) return
  if (closeDraftIfAtStart(event, next)) return
  if (next.distanceTo(last) < 0.005) return
  draftBoundary.push(next)
  draftScreenPoints.push([event.clientX, event.clientY])
  rebuildBoundaryVisual(draftBoundary, false)
  updateDraftScreenPath()
})
canvas.addEventListener('pointerup', (event) => {
  if (drawingBoundary) {
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId)
    closeDraftIfAtStart(event, groundPointFromEvent(event))
    if (draftBoundaryClosed && draftBoundary.length >= 3) {
      setBoundary(draftBoundary)
      setBoundaryDrawing(false)
    } else {
      boundaryStatus.textContent = 'Line still open · return to the starting point before releasing to save.'
    }
    return
  }
  if (!tokenPointerDown) return
  const moved = Math.hypot(event.clientX - tokenPointerDown.x, event.clientY - tokenPointerDown.y)
  tokenPointerDown = null
  if (moved > 7 || tokenPopup.hidden === false) return
  const bounds = canvas.getBoundingClientRect()
  tokenPointer.set(
    ((event.clientX - bounds.left) / bounds.width) * 2 - 1,
    -((event.clientY - bounds.top) / bounds.height) * 2 + 1,
  )
  tokenPicker.setFromCamera(tokenPointer, activeCamera)
  const hit = tokenPicker.intersectObjects(environment.habitats.map((habitat) => habitat.group), true)[0]
  const habitatId = hit ? habitatIdFromObject(hit.object) : null
  const habitat = habitatId ? environment.habitats.find((candidate) => candidate.state.id === habitatId) : undefined
  if (habitat) openTokenPopup(habitat)
})
canvas.addEventListener('pointercancel', (event) => {
  if (!drawingBoundary) return
  if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId)
  if (draftBoundaryClosed && draftBoundary.length >= 3) {
    setBoundary(draftBoundary)
    setBoundaryDrawing(false)
  } else {
    boundaryStatus.textContent = 'Line still open · return to the starting point before releasing to save.'
  }
})

function habitatIdFromObject(object: Object3D) {
  let current: Object3D | null = object
  while (current) {
    const id = current.userData.tokenHabitatId
    if (typeof id === 'string') return id
    current = current.parent
  }
  return null
}

function setSelectedFly(index: number, focus: boolean) {
  selectedIndex = population.select(index)
  debug.setLabel(`FLY #${String(selectedIndex + 1).padStart(3, '0')}`)
  if (focus && cameraIndex === 0) free.focusOn(cameraTargetPosition())
}

function stopCinematic() {
  if (cinematicTimer !== null) {
    window.clearInterval(cinematicTimer)
    cinematicTimer = null
  }
}

function cameraTargetPosition() {
  return cameraFocus.copy(agents[selectedIndex]!.body.position)
}

function cameraTargetAgent() {
  return agents[selectedIndex]!
}

let debugVectorsVisible = false
debug.setVectorsVisible(debugVectorsVisible)

function resize() {
  renderer.setSize(window.innerWidth, window.innerHeight)
  pipeline.resize(window.innerWidth, window.innerHeight)
  const nextMobileViewport = window.matchMedia?.('(max-width: 600px)').matches ?? false
  if (nextMobileViewport !== mobileViewport) {
    mobileViewport = nextMobileViewport
    pipeline.setQuality(renderQuality)
  }
  for (const camera of cameras) {
    camera.aspect = window.innerWidth / window.innerHeight
    camera.updateProjectionMatrix()
  }
}
window.addEventListener('resize', resize)

brainSocket.onStatusChange((next) => {
  status.innerHTML = `<span class="status-dot ${next}"></span> brain socket ${next} <span class="socket-url">${brainUrl}</span>`
  intentLogLive.textContent = next === 'connected' ? (brainSocket.telemetryRole() === 'producer' ? 'LIVE · PRODUCER' : 'LIVE · VIEW ONLY') : 'WAITING'
  if (next === 'connected') {
    brainSocket.requestEnvironment()
    brainSocket.requestPortfolio()
  }
})
brainSocket.onSwarmRoleChange((role) => {
  intentLogLive.textContent = role === 'producer' ? 'LIVE · PRODUCER' : role === 'observer' ? 'LIVE · VIEW ONLY' : 'WAITING'
})
brainSocket.connect()
window.setInterval(() => brainSocket.requestEnvironment(), 15000)
window.setInterval(() => brainSocket.requestPortfolio(), 3000)

logButton.addEventListener('click', () => flightLog.download())

const clock = performance.now()
let previous = clock
let nextLogAt = 0
let nextCausalUiAt = 0
let nextSwarmTelemetryAt = 0
let nextIntentMotionUiAt = 0
let nextFlyPersistenceAt = 0
let nextPortfolioUiAt = 0
let nextTraceRotationAt = 0
let traceIndex = 0
let startupReleased = false
let nextPerfUiAt = 0
function animate(now: number) {
  const delta = (now - previous) / 1000
  previous = now
  world.update(delta, (position) => environment.habitatContactAt(position).contact)
  if (world.elapsedSeconds >= nextFlyPersistenceAt) {
    persistPrimaryFlyState()
    nextFlyPersistenceAt = world.elapsedSeconds + 0.5
  }
  followers.forEach((follower) => follower.update(delta, world.elapsedSeconds))
  environment.updateVisuals(world.elapsedSeconds)
  atmosphere.update(world.elapsedSeconds)
  updateStartupGate()
  if (world.elapsedSeconds >= nextIntentMotionUiAt) {
    updateFlightMotionStatus()
    nextIntentMotionUiAt += 0.25
  }
  const marketEnvironment = brainSocket.environmentUpdate()
  if (marketEnvironment?.status === 'ok') environment.applyMarketHabitats(marketEnvironment)
  if (world.elapsedSeconds >= nextPortfolioUiAt) {
    updatePortfolioSummary()
    nextPortfolioUiAt = world.elapsedSeconds + 1
  }

  const isTelemetryProducer = brainSocket.telemetryRole() === 'producer'
  if (isTelemetryProducer) {
    swarmObserver.observe(
      Date.now(),
      agents,
      environment.habitats,
      (position) => {
        const contact = environment.habitatContactAt(position)
        return { contact: contact.contact, habitatId: contact.habitatId }
      },
    )
  }

  if (isTelemetryProducer && world.elapsedSeconds >= nextSwarmTelemetryAt) {
    // The server derives the authoritative BUY/SELL stream from this one
    // producer's observations. Never display a local second decision stream.
    swarmObserver.drainIntents()
    brainSocket.sendSwarmTelemetry({
      type: 'swarm_telemetry',
      timestampMs: Date.now(),
      agents: agents.map((agent) => ({
        flyId: agent.id,
        timestampMs: Date.now(),
        position: vectorToWire(agent.body.position),
        habitats: environment.habitats.map((habitat) => {
          const contact = environment.habitatContactAt(agent.body.position)
          return {
            habitatId: habitat.state.id,
            distanceM: agent.body.position.distanceTo(habitat.group.position),
            radiusM: habitat.properties.physicalRadiusM,
            contact: contact.contact && contact.habitatId === habitat.state.id,
            behavior: swarmObserver.telemetryFor(agent.id, habitat.state.id),
          }
        }),
      })),
    })
    nextSwarmTelemetryAt += 0.25
  }

  if (world.elapsedSeconds >= nextLogAt) {
    flightLog.record(agents[selectedIndex]!, brainSocket, world.elapsedSeconds)
    nextLogAt += 0.1
  }

  flyRenderers.forEach((flyRenderer, index) => {
    flyRenderer.setSelected(index === selectedIndex)
    flyRenderer.update(agents[index]!, world.elapsedSeconds)
  })
  const selectedAgent = agents[selectedIndex]!
  // Diagnostics are intentionally not part of the product view. Avoid doing
  // hidden DOM/raster work or ArrowHelper math on every frame when the panels
  // are disabled; this matters with 80 canonical Flybody renderers.
  if (debugPanelVisible || debugVectorsVisible) {
    debug.update(selectedAgent, world.elapsedSeconds, brainSocket.getStatus(), brainSocket.stimulationFor(selectedAgent.id), brainSocket.activityFor(selectedAgent.id))
  }
  // Rotate the detailed trace across all independent brains so the product
  // view does not imply that fly-001 is the whole swarm. Prefer live agents;
  // if a backend is late, keep the panel useful by showing the next primary.
  if (world.elapsedSeconds >= nextTraceRotationAt) {
    traceIndex = (traceIndex + 1) % agents.length
    nextTraceRotationAt = world.elapsedSeconds + 4
  }
  const liveTraceIndices = agents
    .map((agent, index) => isLiveBrainSource(brainSocket.activityFor(agent.id)?.source) ? index : -1)
    .filter((index) => index >= 0)
  const tracePool = liveTraceIndices.length > 0 ? liveTraceIndices : agents.map((_, index) => index)
  const traceAgentIndex = tracePool[traceIndex % tracePool.length] ?? 0
  const traceAgent = agents[traceAgentIndex] ?? agents[0]!
  brainActivityPanel.update(traceAgent, brainSocket.activityFor(traceAgent.id), brainSocket.stimulationFor(traceAgent.id), world.elapsedSeconds)
  brainActivityPanel.animate(world.elapsedSeconds)
  if (debugPanelVisible && world.elapsedSeconds >= nextCausalUiAt) {
    updateCausalStatus(selectedAgent)
    nextCausalUiAt += 0.25
  }
  if (debugPanelVisible) {
    const liveBrains = agents.reduce((count, agent) => count + (isLiveBrainSource(brainSocket.activityFor(agent.id)?.source) ? 1 : 0), 0)
    const cnsActive = agents.reduce((count, agent) => {
      const activity = brainSocket.activityFor(agent.id)
      return count + (activity !== null && isLiveBrainSource(activity.source) && Object.values(activity.spikeCounts).some((count) => count > 0) ? 1 : 0)
    }, 0)
    const cnsMotorControlled = agents.reduce((count, agent) => {
      if (agent.mode !== 'malecns') return count
      const activity = brainSocket.activityFor(agent.id)
      const command = agent.actuators.get()
      const nonNeutral = command.forwardThrust > 0 || Math.abs(command.yawTorque) > 0 || Math.abs(command.pitchTorque) > 0 || Math.abs(command.rollTorque) > 0
      return count + (isLiveBrainSource(activity?.source) && nonNeutral ? 1 : 0)
    }, 0)
    const movingAgents = agents.reduce((count, agent) => count + (agent.body.velocity.length() > 0.002 ? 1 : 0), 0)
    populationStatus.innerHTML = `<strong>FRUITFLY CAPITAL</strong><br>VISIBLE FLIES ${VISUAL_FLY_COUNT} · PRIMARY SIGNALS ${SWARM_SIZE} · BODIES / SIGNAL ${BODIES_PER_BRAIN}<br>CNS RUNTIMES ${liveBrains}/${SWARM_SIZE} · CNS ACTIVE ${cnsActive}/${SWARM_SIZE} · MOVING ${movingAgents}/${SWARM_SIZE}<br>MALECNS DRIVE ${cnsMotorControlled}/${SWARM_SIZE}`
  }
  activeCamera = cameras[cameraIndex] ?? cameras[0]!
  if (cameraIndex === 0) free.update()
  const followedAgent = cameraTargetAgent()
  if (cameraIndex === 1) follow.update(followedAgent)
  if (cameraIndex === 2) firstPerson.update(followedAgent)
  if (cameraIndex === 3) side.update(followedAgent)
  if (cameraIndex === 4) presentation.update(world.elapsedSeconds, agents, environment.habitats, selectedIndex)

  visualRenderers.forEach((flyRenderer, index) => {
    const distance = flyRenderer.group.position.distanceTo(activeCamera.position)
    const selectedPrimary = index < flyRenderers.length && index === selectedIndex
    flyRenderer.setSelected(selectedPrimary)
    const lod = selectedPrimary || (!mobileViewport && distance < 0.42)
      ? 'full'
      : distance < (mobileViewport ? 0.8 : 1.15) ? 'medium' : 'low'
    flyRenderer.setLod(lod)
  })

  updateTokenLogoOverlay()
  pipeline.render(delta, activeCamera)
  if (debugPanelVisible && world.elapsedSeconds >= nextPerfUiAt) {
    const lodCounts = visualRenderers.reduce((counts, flyRenderer) => {
      const lod = flyRenderer.currentLod
      counts[lod] += 1
      return counts
    }, { full: 0, medium: 0, low: 0 })
    const fps = delta > 0 ? Math.round(1 / delta) : 0
    performanceStatus.textContent = `PERF · ${fps} FPS · ${renderer.info.render.calls} calls · ${renderer.info.render.triangles} tris · LOD full/med/low ${lodCounts.full}/${lodCounts.medium}/${lodCounts.low} · particles ${environment.particles.count} · brain ${brainUpdateHz} Hz · ${renderQuality.toUpperCase()}`
    nextPerfUiAt += 0.25
  }
  requestAnimationFrame(animate)
}

function updateStartupGate() {
  if (startupReleased) return
  const movingAgents = agents.reduce((count, agent) => count + (agent.body.velocity.length() > 0.002 ? 1 : 0), 0)
  const habitatsReady = environment.habitats.length > 0
  if (!canonicalBodiesReady) {
    startupMessage.textContent = 'LOADING FLY BODIES'
    startupDetail.textContent = 'Preparing the canonical fly bodies…'
    startupProgress.style.width = '35%'
  } else if (!habitatsReady) {
    startupMessage.textContent = 'LOADING TOKEN HABITATS'
    startupDetail.textContent = 'Waiting for the live token places to appear…'
    startupProgress.style.width = '70%'
  } else if (brainSocket.getStatus() !== 'connected') {
    startupMessage.textContent = 'TOKEN HABITATS READY'
    startupDetail.textContent = 'Waiting for the autonomous brain feed…'
    startupProgress.style.width = '100%'
  } else if (movingAgents === 0) {
    startupMessage.textContent = 'TOKEN HABITATS READY'
    startupDetail.textContent = 'Brains connected · waiting for the first motor update…'
    startupProgress.style.width = '100%'
  } else {
    startupMessage.textContent = 'SWARM IN MOTION'
    startupDetail.textContent = 'Autonomous flight feed active.'
    startupProgress.style.width = '100%'
  }

  // Do not reveal an empty floor. Both the fly assets and the first non-empty
  // live token snapshot must be ready before the loading screen can clear.
  if (canonicalBodiesReady && habitatsReady) {
    startupReleased = true
    startupScreen.classList.add('is-ready')
    window.setTimeout(() => startupScreen.remove(), 500)
  }
}

function updateCausalStatus(agent: FlyAgent) {
  const stimulation = brainSocket.stimulationFor(agent.id)
  const activity = brainSocket.activityFor(agent.id)
  const frame = agent.sensors.getFrame()
  const command = agent.actuators.get()
  const brainStep = activity !== null && isLiveBrainSource(activity.source)
    ? `Brian2 output · DN ${Object.values(activity.descendingRates).some((rate) => rate > 0) ? 'active' : 'quiet'}`
    : activity
      ? 'decoder-only output · no live Brian2 provider'
      : 'waiting for this fly\'s brain output'
  causalStatus.innerHTML = [
    `<strong>CAUSE MAP · ${agent.id}</strong> · ${brainStep}`,
    `senses: vision L/R ${frame.leftEye.meanLuminance.toFixed(2)}/${frame.rightEye.meanLuminance.toFixed(2)} · odor ${frame.odor.concentration.toFixed(2)} · wall ${frame.contact.wall}`,
    `spikes/DN: ${stimulation ? `${stimulation.visual.length} visual + ${stimulation.olfactory.length} odor` : 'not encoded yet'} → decoded MaleCNS output → command ${command.forwardThrust.toFixed(2)} thrust · ${command.yawTorque.toFixed(2)} yaw · ${command.pitchTorque.toFixed(2)} pitch`,
    `landing: ${agent.landingState} · habitat contact ${environment.habitatContactAt(agent.body.position).contact ? 'true' : 'false'} · neural/motor ${agent.lastNeuralCommand.verticalThrust.toFixed(2)}/${agent.lastMotorCommand.verticalThrust.toFixed(2)} vertical`,
  ].join('<br>')
}

requestAnimationFrame(animate)
