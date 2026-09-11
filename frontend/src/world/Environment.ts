import { AmbientLight, Color, DirectionalLight, Fog, Group, HemisphereLight, PointLight, Scene, SRGBColorSpace, TextureLoader, Vector3 } from 'three'
import { Arena } from './Arena'
import { MOCK_HABITAT_COLORS, MOCK_HABITAT_POSITIONS, MOCK_TOKEN_STATES } from './tokenFixtures'
import { TokenHabitat, type HabitatScenario } from './TokenHabitat'
import type { OdorFieldSample } from '../fly/FlySensors'
import type { EnvironmentUpdateMessage } from '../networking/protocol'
import { ParticleField } from './ParticleField'
import type { TokenState } from './TokenState'

// The city is a directory of the first 150 tracked markets. This is separate
// from the smaller deep-observer tier on the backend.
const WORLD_HABITAT_CAPACITY = 150
const HABITAT_PALETTE = [0x4bd6a0, 0x6ca8ff, 0xff6e80, 0xf5c84c, 0xa980ff, 0xff9b5c, 0x56d9d0, 0xff80b8]
const HABITAT_SCALE_STORAGE_KEY = 'ffc.habitatVisualScale.v2'

export class Environment {
  readonly group = new Group()
  readonly arena = new Arena()
  readonly bounds = this.arena.bounds
  private readonly habitatsById = new Map<string, TokenHabitat>()
  private readonly habitatList: TokenHabitat[] = []
  private readonly slotsById = new Map<string, number>()
  private lastVisualUpdateSeconds = Number.NEGATIVE_INFINITY
  private habitatVisualScale = readHabitatVisualScale()
  private worldBoundary: Vector3[] | null = null
  readonly particles: ParticleField
  get habitats() {
    return this.habitatList
  }
  private lastAppliedMarketObservedAtMs = 0
  scenario: HabitatScenario = 'live'

  constructor() {
    this.group.name = 'Environment'
    this.group.add(this.arena.group)
    this.particles = new ParticleField(this.habitatList, 24, WORLD_HABITAT_CAPACITY)
    this.group.add(this.particles.mesh)
    this.setHabitatScenario('live')
  }

  setHabitatScenario(scenario: HabitatScenario) {
    this.scenario = scenario
    if (scenario === 'live') this.lastAppliedMarketObservedAtMs = 0
    if (scenario !== 'live' && this.habitatList.length === 0) {
      MOCK_TOKEN_STATES.forEach((state, index) => this.addHabitat(
        state,
        MOCK_HABITAT_POSITIONS[index]!,
        MOCK_HABITAT_COLORS[index]!,
      ))
    }
    // Live Graph is an external-data mode. Keep fixture values hidden while
    // the backend is disabled, waiting, or returning an error; otherwise a
    // failed live feed looks like real market data in the scene.
    const appearanceScenario = scenario === 'live' ? 'off' : scenario
    this.habitatList.forEach((habitat) => {
      if (scenario !== 'live') habitat.resetIdentity()
      habitat.setScenario(appearanceScenario)
    })
    if (scenario === 'swapped') {
      this.habitatList.forEach((habitat, index) => habitat.setPosition(MOCK_HABITAT_POSITIONS[(index + 1) % MOCK_HABITAT_POSITIONS.length] ?? this.positionFor(habitat.state.id, index)))
    } else {
      this.habitatList.forEach((habitat) => habitat.resetPosition())
    }
  }

  getHabitatVisualScale() {
    return this.habitatVisualScale
  }

  setHabitatVisualScale(scale: number) {
    this.habitatVisualScale = clamp(scale, 0.5, 1.35)
    window.localStorage.setItem(HABITAT_SCALE_STORAGE_KEY, String(this.habitatVisualScale))
    this.habitatList.forEach((habitat) => habitat.setManualScale(this.habitatVisualScale))
  }

  applyMarketHabitats(update: EnvironmentUpdateMessage['environment']) {
    // Some discovery-only/live adapters use 0 for the first observation. Do
    // not discard that initial non-empty snapshot before any habitats exist.
    if (this.habitatList.length > 0 && update.observedAtMs <= this.lastAppliedMarketObservedAtMs) return
    this.lastAppliedMarketObservedAtMs = update.observedAtMs
    // The market snapshot is authoritative. New IDs create new habitats,
    // existing IDs retain their position, and departed IDs are retired.
    const incomingIds = new Set<string>()
    const wasEmpty = this.habitatList.length === 0
    // The public world is Robinhood-only. Keep this client-side guard as a
    // safety net for an old/cached server snapshot during deployment rollout.
    const robinhoodHabitats = update.habitats.filter(isRobinhoodHabitat)
    // Older server snapshots were already restricted to Robinhood but did
    // not serialize chain metadata on each habitat. Keep the client-side
    // whitelist when metadata exists; otherwise preserve that server-filtered
    // snapshot rather than showing a token count with zero rendered places.
    const renderableHabitats = robinhoodHabitats.length > 0
      ? robinhoodHabitats
      : update.habitats.filter((state) => !hasChainMetadata(state))
    for (const state of renderableHabitats.slice(0, WORLD_HABITAT_CAPACITY)) {
      incomingIds.add(state.id)
      const nextState = tokenStateFromEnvironment(state)
      let habitat = this.habitatsById.get(state.id)
      if (!habitat) {
        habitat = this.addHabitat(nextState, this.positionFor(state.id, this.habitatList.length), this.colorFor(state.id))
      } else {
        habitat.setMarketState(nextState)
      }
      habitat.setPhysicalProperties({
        physicalRadiusM: state.physicalRadiusM,
        resourcePileRadiusM: state.resourcePileRadiusM,
        visualMotionIntensity: state.visualMotionIntensity,
        brightness: state.brightness,
        particleActivity: state.particleActivity,
        chaos: state.chaos,
        attractiveOdor: state.attractiveOdor,
        aversiveDanger: state.aversiveDanger,
        semanticType: state.semanticType === 'food' || state.semanticType === 'rot' || state.semanticType === 'trash' || state.semanticType === 'market'
          ? state.semanticType
          : 'market',
      })
    }
    for (let index = this.habitatList.length - 1; index >= 0; index -= 1) {
      const habitat = this.habitatList[index]!
      if (incomingIds.has(habitat.state.id)) continue
      this.group.remove(habitat.group)
      habitat.dispose()
      this.habitatsById.delete(habitat.state.id)
      this.slotsById.delete(habitat.state.id)
      this.habitatList.splice(index, 1)
    }
    if (wasEmpty && this.worldBoundary) this.spreadHabitatsWithinWorldBoundary()
    else this.constrainHabitatsToWorldBoundary()
  }

  setWorldBoundary(points: readonly Vector3[] | null) {
    this.worldBoundary = points && points.length >= 3
      ? points.map((point) => new Vector3(point.x, 0, point.z))
      : null
    if (this.worldBoundary) this.spreadHabitatsWithinWorldBoundary()
    else this.constrainHabitatsToWorldBoundary()
  }

  updateVisuals(timeSeconds: number) {
    // Physics and neural sampling run on their own fixed/update cadences.
    // Habitat glows and pooled particles do not need a full recalculation at
    // the display refresh rate, especially with up to 100 token places.
    if (timeSeconds - this.lastVisualUpdateSeconds < 1 / 30) return
    this.lastVisualUpdateSeconds = timeSeconds
    this.habitatList.forEach((habitat) => habitat.update(timeSeconds))
    this.particles.update(timeSeconds)
  }

  sampleOdorAt(position: Vector3, timeSeconds: number): OdorFieldSample {
    return this.habitatList.reduce(
      (total, habitat) => {
        const field = habitat.odorAt(position, timeSeconds)
        return {
          // A fly should smell the strongest nearby source, not a saturated
          // sum of 100 overlapping habitats. Max-preserving the field keeps a
          // spatial gradient so the autonomous controller can still approach
          // a particular token place.
          attractive: Math.max(total.attractive, field.attractive),
          aversive: Math.max(total.aversive, field.aversive),
        }
      },
      { attractive: 0, aversive: 0 },
    )
  }

  /**
   * Contact is evaluated after physics, outside the CNS sensory payload.
   * The brain receives odor and bilateral gradients; swarm telemetry may
   * identify which habitat was actually touched afterward.
   */
  habitatContactAt(position: Vector3) {
    let nearest: { habitatId: string; distanceM: number; radiusM: number } | null = null
    for (const habitat of this.habitatList) {
      const distanceM = position.distanceTo(habitat.group.position)
      const radiusM = Math.max(0.045, habitat.properties.physicalRadiusM * 0.55 + 0.025)
      if (!nearest || distanceM < nearest.distanceM) nearest = { habitatId: habitat.state.id, distanceM, radiusM }
    }
    return {
      contact: nearest !== null && nearest.distanceM <= nearest.radiusM,
      habitatId: nearest?.habitatId ?? null,
      distanceM: nearest?.distanceM ?? Number.POSITIVE_INFINITY,
      radiusM: nearest?.radiusM ?? 0,
    }
  }

  private addHabitat(state: TokenState, position: Vector3, color: number) {
    const habitat = new TokenHabitat(state, position, color)
    habitat.setManualScale(this.habitatVisualScale)
    this.habitatsById.set(state.id, habitat)
    this.habitatList.push(habitat)
    this.group.add(habitat.group)
    this.constrainHabitatsToWorldBoundary()
    return habitat
  }

  private constrainHabitatsToWorldBoundary() {
    if (!this.worldBoundary || this.worldBoundary.length < 3) return
    const center = this.worldBoundary.reduce((sum, point) => sum.add(point), new Vector3()).multiplyScalar(1 / this.worldBoundary.length)
    for (const habitat of this.habitatList) {
      if (pointInPolygon(habitat.group.position, this.worldBoundary)) continue
      const nearest = closestPointOnPolygon(habitat.group.position, this.worldBoundary)
      const inward = center.clone().sub(nearest)
      if (inward.lengthSq() > 0) inward.normalize().multiplyScalar(0.02)
      const candidate = nearest.clone().add(inward)
      const next = pointInPolygon(candidate, this.worldBoundary) ? candidate : nearest
      habitat.setPosition(next)
      habitat.basePosition.copy(next)
    }
  }

  private spreadHabitatsWithinWorldBoundary() {
    if (!this.worldBoundary || this.worldBoundary.length < 3 || this.habitatList.length === 0) return
    const minX = Math.min(...this.worldBoundary.map((point) => point.x))
    const maxX = Math.max(...this.worldBoundary.map((point) => point.x))
    const minZ = Math.min(...this.worldBoundary.map((point) => point.z))
    const maxZ = Math.max(...this.worldBoundary.map((point) => point.z))
    const grid = 32
    const candidates: Vector3[] = []
    for (let row = 0; row < grid; row += 1) {
      const z = minZ + (row + 0.5) / grid * (maxZ - minZ)
      for (let column = 0; column < grid; column += 1) {
        const x = minX + (column + 0.5) / grid * (maxX - minX)
        const candidate = new Vector3(x, 0, z)
        if (pointInPolygon(candidate, this.worldBoundary)) candidates.push(candidate)
      }
    }
    if (candidates.length === 0) {
      const center = this.worldBoundary.reduce((sum, point) => sum.add(point), new Vector3()).multiplyScalar(1 / this.worldBoundary.length)
      candidates.push(center)
    }
    const count = this.habitatList.length
    this.habitatList.forEach((habitat, index) => {
      const candidateIndex = Math.min(candidates.length - 1, Math.floor((index + 0.5) * candidates.length / count))
      const next = candidates[candidateIndex]!
      habitat.setPosition(next)
      habitat.basePosition.copy(next)
    })
  }

  private colorFor(id: string) {
    return HABITAT_PALETTE[hashString(id) % HABITAT_PALETTE.length] ?? HABITAT_PALETTE[0]!
  }

  private positionFor(id: string, fallbackIndex: number) {
    const slot = this.slotFor(id, fallbackIndex)
    const columns = 10
    const rows = Math.ceil(WORLD_HABITAT_CAPACITY / columns)
    // Use a broad central field on the 6m floor. This keeps habitats visibly
    // spread out while ensuring the odor-searching swarm encounters a source
    // quickly instead of spending the opening minutes in empty corners.
    const x = -1.9 + (slot % columns) * (3.8 / (columns - 1))
    const z = -1.9 + Math.floor(slot / columns) * (3.8 / Math.max(1, rows - 1))
    return new Vector3(x, 0, z)
  }

  private slotFor(id: string, fallbackIndex: number) {
    const existing = this.slotsById.get(id)
    if (existing !== undefined) return existing
    const occupied = new Set(this.slotsById.values())
    let slot = hashString(id) % WORLD_HABITAT_CAPACITY
    for (let attempt = 0; attempt < WORLD_HABITAT_CAPACITY; attempt += 1) {
      if (!occupied.has(slot)) {
        this.slotsById.set(id, slot)
        return slot
      }
      slot = (slot + 1) % WORLD_HABITAT_CAPACITY
    }
    const fallback = fallbackIndex % WORLD_HABITAT_CAPACITY
    this.slotsById.set(id, fallback)
    return fallback
  }

  setupLighting(scene: Scene) {
    // The image is a Three.js scene background, not a UI overlay. Keep a
    // Keep the floor and habitats readable against the star-field backdrop.
    scene.background = new Color(0x061017)
    const background = new TextureLoader().load('/design/fruit-fly-capital-canva-background.png', (texture) => {
      texture.colorSpace = SRGBColorSpace
      scene.background = texture
    })
    background.colorSpace = SRGBColorSpace
    // A close, blue-green night mist gives the floor depth without washing
    // out the token habitats or the star-field background.
    scene.fog = new Fog(0x102d35, 1.65, 7.4)
    scene.add(new HemisphereLight(0x92c4c3, 0x152227, 1.55))
    scene.add(new AmbientLight(0x3b6d70, 1.02))
    const key = new DirectionalLight(0xffcf92, 2.25)
    key.position.set(-1.5, 2.2, 1.1)
    key.castShadow = false
    scene.add(key)
    const fill = new DirectionalLight(0x83d9ed, 1.45)
    fill.position.set(1.2, 1.1, -1.3)
    scene.add(fill)
    const moon = new DirectionalLight(0x87b9ff, 0.68)
    moon.position.set(-1.8, 2.8, -2.2)
    scene.add(moon)
    // Low-intensity street pools sell the night scene without turning every
    // habitat into an overexposed glowing disk.
    for (const [x, z, color] of [[-1.8, -1.4, 0x37b8ff], [1.65, 0.9, 0xff8c48], [0.2, 1.75, 0x72f0bf]] as const) {
      const streetLight = new PointLight(color, 0.82, 1.7, 2)
      streetLight.position.set(x, 0.46, z)
      scene.add(streetLight)
    }
  }

}

function readHabitatVisualScale() {
  const saved = Number(window.localStorage.getItem(HABITAT_SCALE_STORAGE_KEY))
  return Number.isFinite(saved) ? clamp(saved, 0.5, 1.35) : 0.72
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}

function tokenStateFromEnvironment(state: EnvironmentUpdateMessage['environment']['habitats'][number]): TokenState {
  const numberSignal = (name: string, fallback: number | null = null) => {
    const value = state.signals?.find((signal) => signal.name === name)?.value
    return typeof value === 'number' && Number.isFinite(value) ? value : fallback
  }
  return {
    id: state.id,
    label: state.label,
    imageUrl: state.imageUrl ?? imageUrlFromProvenance(state.provenance),
    tokenAddress: state.tokenAddress ?? null,
    poolId: state.poolId ?? null,
    chainId: state.chainId ?? provenanceString(state.provenance, 'chainId'),
    dexId: state.dexId ?? provenanceString(state.provenance, 'dexId'),
    pairAddress: state.pairAddress ?? provenanceString(state.provenance, 'pairAddress'),
    dexscreenerUrl: state.dexscreenerUrl ?? provenanceString(state.provenance, 'url'),
    observedAtMs: 0,
    market: {
      priceInPair: null,
      priceUsd: numberSignal('market.priceUsd'),
      marketCapUsd: numberSignal('market.marketCapUsd'),
      fdvUsd: numberSignal('market.fdvUsd'),
      volume5mUsd: numberSignal('market.volume5mUsd', 0) ?? 0,
      volume15mUsd: numberSignal('market.volume15mUsd', 0) ?? 0,
      volume1hUsd: numberSignal('market.volume1hUsd', 0) ?? 0,
      volume24hUsd: numberSignal('market.volume24hUsd'),
    },
    flow: {
      buyCount5m: numberSignal('flow.buyCount5m', 0) ?? 0,
      sellCount5m: numberSignal('flow.sellCount5m', 0) ?? 0,
      buyUsd5m: numberSignal('flow.buyUsd5m', 0) ?? 0,
      sellUsd5m: numberSignal('flow.sellUsd5m', 0) ?? 0,
      flowImbalance: numberSignal('flow.imbalance', 0) ?? 0,
      txVelocity5m: numberSignal('flow.txVelocity5m', 0) ?? 0,
      txAcceleration: numberSignal('flow.txAcceleration', 0) ?? 0,
    },
    liquidity: {
      liquidityUsd: numberSignal('liquidity.usd', 0) ?? 0,
      liquidityDeltaUsd: numberSignal('liquidity.deltaUsd'),
      volumeLiquidityRatio1h: numberSignal('liquidity.volumeLiquidityRatio1h', 0) ?? 0,
      marketCapToLiquidity: numberSignal('liquidity.marketCapToLiquidity'),
      fdvToLiquidity: numberSignal('liquidity.fdvToLiquidity'),
      volume24hToMarketCap: numberSignal('liquidity.volume24hToMarketCap'),
      volume24hToLiquidity: numberSignal('liquidity.volume24hToLiquidity'),
    },
    holders: { status: 'unavailable', holderCount: null, growth24h: null, top10Concentration: null },
    security: { status: 'unavailable', honeypot: null, contractVerified: null, ownerControl: null },
    social: { status: 'unavailable', mentions: null, sentiment: null },
    lore: { status: 'unavailable', catalysts: [] },
    signals: (state.signals ?? []).map((signal) => ({
      ...signal,
      value: typeof signal.value === 'number' || typeof signal.value === 'string' || signal.value === null ? signal.value : null,
    })),
    provenance: state.provenance ?? [],
    financial: state.financialTrace ?? null,
  }
}

function isRobinhoodHabitat(state: EnvironmentUpdateMessage['environment']['habitats'][number]) {
  const chainId = state.chainId ?? provenanceString(state.provenance, 'chainId')
  const network = provenanceString(state.provenance, 'network')
  const chain = provenanceString(state.provenance, 'chain')
  const identifiers = [chainId, network, chain]
    .filter((value) => value !== null && value !== undefined)
    .map((value) => String(value).trim().toLowerCase())
  return identifiers.some((value) => value === '46630' || value.includes('robinhood'))
}

function hasChainMetadata(state: EnvironmentUpdateMessage['environment']['habitats'][number]) {
  return state.chainId !== null && state.chainId !== undefined
    || provenanceString(state.provenance, 'chainId') !== undefined
    || provenanceString(state.provenance, 'network') !== undefined
    || provenanceString(state.provenance, 'chain') !== undefined
}

function provenanceString(provenance: Array<Record<string, unknown>> | undefined, key: string) {
  const value = provenance?.find((item) => typeof item[key] === 'string')?.[key]
  return typeof value === 'string' && value.length > 0 ? value : undefined
}

function imageUrlFromProvenance(provenance: Array<Record<string, unknown>> | undefined) {
  const imageUrl = provenance?.find((item) => typeof item.imageUrl === 'string')?.imageUrl
  return typeof imageUrl === 'string' && imageUrl.length > 0 ? imageUrl : null
}

function hashString(value: string) {
  let hash = 2166136261
  for (let index = 0; index < value.length; index += 1) hash = Math.imul(hash ^ value.charCodeAt(index), 16777619)
  return hash >>> 0
}

function pointInPolygon(position: Vector3, polygon: readonly Vector3[]) {
  let inside = false
  for (let index = 0, previous = polygon.length - 1; index < polygon.length; previous = index++) {
    const current = polygon[index]!
    const prior = polygon[previous]!
    const intersects = (current.z > position.z) !== (prior.z > position.z)
      && position.x < ((prior.x - current.x) * (position.z - current.z)) / (prior.z - current.z) + current.x
    if (intersects) inside = !inside
  }
  return inside
}

function closestPointOnPolygon(position: Vector3, polygon: readonly Vector3[]) {
  let closest = polygon[0]!.clone()
  let closestDistance = Number.POSITIVE_INFINITY
  for (let index = 0; index < polygon.length; index += 1) {
    const start = polygon[index]!
    const end = polygon[(index + 1) % polygon.length]!
    const edge = end.clone().sub(start)
    const denominator = edge.lengthSq()
    const t = denominator > 0 ? clamp(position.clone().sub(start).dot(edge) / denominator, 0, 1) : 0
    const candidate = start.clone().add(edge.multiplyScalar(t))
    const distance = candidate.distanceToSquared(position)
    if (distance < closestDistance) {
      closestDistance = distance
      closest = candidate
    }
  }
  return closest
}
