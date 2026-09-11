import type { Quaternion, Vector3 } from 'three'

export type FlyMode = 'manual' | 'malecns' | 'off'

export function isLiveBrainSource(source: string | undefined): boolean {
  return source?.startsWith('brian2-malecns-v1-realtime-') ?? false
}

export interface EyeSample {
  direction: { x: number; y: number; z: number }
  azimuthRad: number
  elevationRad: number
  luminance: number
  contrast: number
  opticFlow: number
  objectAngularSizeRad: number
}

export interface EyeObservation {
  samples: EyeSample[]
  meanLuminance: number
  meanContrast: number
  meanOpticFlow: number
}

export interface OdorObservation {
  concentration: number
  leftAntenna: number
  rightAntenna: number
  aversiveConcentration: number
  temporalChange: number
  airflowImplemented: false
}

export interface MotionObservation {
  angularVelocity: { x: number; y: number; z: number }
  bodyVelocity: { x: number; y: number; z: number }
  translationalSpeed: number
  gravityAlignment: number
  windDirection: null
  windSpeed: 0
  windImplemented: false
}

export interface ContactObservation {
  ground: boolean
  obstacle: boolean
  wall: boolean
}

export interface ActuatorCommand {
  forwardThrust: number
  verticalThrust: number
  yawTorque: number
  pitchTorque: number
  rollTorque: number
}

export interface SensorFrame {
  leftEye: EyeObservation
  rightEye: EyeObservation
  odor: OdorObservation
  motion: MotionObservation
  contact: ContactObservation
  timestampMs: number
}

export interface StimulationEntry {
  bodyId: number
  rateHz: number
  population?: string
}

export interface MaleCNSSensoryStimulation {
  visual: StimulationEntry[]
  olfactory: StimulationEntry[]
  mechanosensory: StimulationEntry[]
  unimplemented: string[]
}

export interface FlightCommand {
  thrust: number
  yaw: number
  pitch: number
  roll: number
}

export interface LowLevelFlightCommand {
  forwardThrust: number
  verticalThrust: number
  yawTorque: number
  pitchTorque: number
  rollTorque: number
  wingbeatFrequencyHz?: number
  steeringReference7d?: {
    vector: number[]
    dimension: number
    futureSteps: number
    refDisplacementCm: [number, number, number]
    refRootQuatWxyz: [number, number, number, number]
    displacementFrame: string
    quaternionFrame: string
  }
}

export interface PhysicalFlightTelemetry {
  /** Present only when a native Flybody/MuJoCo worker reports these values. */
  flybodyJointAction?: number[]
  physicalVelocity?: { x: number; y: number; z: number }
  physicalPosition?: { x: number; y: number; z: number }
}

export interface BrainActivity extends PhysicalFlightTelemetry {
  flightCommand: FlightCommand
  maleCnsCommand?: FlightCommand
  steeringReference7d?: LowLevelFlightCommand['steeringReference7d']
  lowLevelFlightCommand?: LowLevelFlightCommand
  descendingRates: Record<string, number>
  spikeCounts: Record<string, number>
  source?: string
}

export interface BrainInputMessage {
  type: 'brain_input'
  flyId: string
  mode: FlyMode
  sensors: SensorFrame
  spikeRates?: Record<string, number>
  spikeCounts?: Record<string, number>
}

/** A behavioral proposal, not an executed trade or wallet instruction. */
export type TradeIntentSide = 'buy' | 'sell'
export type TradeIntentReason = 'approach' | 'contact' | 'dwell' | 'departure'

export interface BehaviorTradeIntent {
  intentId: string
  flyId: string
  habitatId: string
  side: TradeIntentSide
  reason: TradeIntentReason
  confidence: number
  observedAtMs: number
  portfolioWeight: number
  metrics: {
    distanceM: number
    visits: number
    approaches: number
    dwellSeconds: number
    repeatVisits: number
    departures: number
    contact: boolean
    persistence: number
  }
}

export interface HabitatBehaviorTelemetry {
  approaches: number
  visits: number
  departures: number
  dwellSeconds: number
  repeatVisits: number
  contactSeconds: number
  persistence: number
  approaching: boolean
}

export interface SwarmTelemetryMessage {
  type: 'swarm_telemetry'
  timestampMs: number
  agents: Array<{
    flyId: string
    timestampMs: number
    position: { x: number; y: number; z: number }
    habitats: Array<{
      habitatId: string
      distanceM: number
      radiusM: number
      contact?: boolean
      behavior?: HabitatBehaviorTelemetry
    }>
  }>
  /** New events since the previous telemetry message; never execution calls. */
  behaviorIntents?: BehaviorTradeIntent[]
}

export interface SwarmUpdateMessage {
  type: 'swarm_update'
  decision: Record<string, unknown>
}

export interface SwarmRoleMessage {
  type: 'swarm_role'
  role: 'producer' | 'observer' | 'available'
}

export interface FundStatusUpdateMessage { type: 'fund_status_update'; fund: Record<string, unknown>; demoData: boolean }
export interface PortfolioUpdateMessage { type: 'portfolio_update'; fund: Record<string, unknown>; demoData: boolean }
export interface TradeHistoryUpdateMessage { type: 'trade_history_update'; trades: Record<string, unknown>[]; demoData: boolean }

export interface BrainOutputMessage {
  type: 'brain_output'
  flyId: string
  commands: ActuatorCommand
  timestampMs: number
  source?: string
  stimulation?: MaleCNSSensoryStimulation
  flightCommand?: FlightCommand
  maleCnsCommand?: FlightCommand
  steeringReference7d?: LowLevelFlightCommand['steeringReference7d']
  lowLevelFlightCommand?: LowLevelFlightCommand
  flybodyJointAction?: number[]
  physicalVelocity?: { x: number; y: number; z: number }
  physicalPosition?: { x: number; y: number; z: number }
  descendingRates?: Record<string, number>
  spikeCounts?: Record<string, number>
  spikeRates?: Record<string, number>
}

export interface EnvironmentUpdateMessage {
  type: 'environment_update'
  environment: {
    source: string
    status: 'disabled' | 'discovery_only' | 'empty' | 'ok' | 'error'
    observedAtMs: number
    habitats: Array<{
      id: string
      label: string
      imageUrl?: string | null
      tokenAddress?: string | null
      poolId?: string | null
      chainId?: string | null
      dexId?: string | null
      pairAddress?: string | null
      dexscreenerUrl?: string | null
      physicalRadiusM: number
      resourcePileRadiusM: number
      visualMotionIntensity: number
      brightness: number
      particleActivity: number
      chaos: number
      attractiveOdor: number
      aversiveDanger: number
      semanticType?: 'food' | 'rot' | 'trash' | 'market' | string
      signals?: Array<{
        name: string
        value: unknown
        normalized: number
        importance: number
        valence: number
        confidence: number
        freshness: number
        source: string
        observedAtMs: number
      }>
      financialTrace?: Record<string, unknown> | null
      provenance?: Array<Record<string, unknown>>
    }>
    rawMarketFieldsForwardedToFly: false
    discovery?: {
      universe?: Record<string, unknown> | null
      round?: Record<string, unknown>
      lastError?: string | null
    }
    reason?: string
    error?: string
  }
}

export interface BrainHelloMessage {
  type: 'hello'
  protocol: 'male-cns-fly-world'
  version: 1
}

export type BrainMessage = BrainInputMessage | BrainOutputMessage | BrainHelloMessage | EnvironmentUpdateMessage | SwarmTelemetryMessage | SwarmUpdateMessage | SwarmRoleMessage | FundStatusUpdateMessage | PortfolioUpdateMessage | TradeHistoryUpdateMessage

export function vectorToWire(vector: Vector3) {
  return { x: vector.x, y: vector.y, z: vector.z }
}

export function quaternionToWire(quaternion: Quaternion) {
  return { x: quaternion.x, y: quaternion.y, z: quaternion.z, w: quaternion.w }
}

export function isBrainOutputMessage(value: unknown): value is BrainOutputMessage {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<BrainOutputMessage>
  const commands = candidate.commands
  return (
    candidate.type === 'brain_output' &&
    typeof candidate.flyId === 'string' &&
    !!commands &&
    typeof commands.forwardThrust === 'number' &&
    typeof commands.verticalThrust === 'number' &&
    typeof commands.yawTorque === 'number' &&
    typeof commands.pitchTorque === 'number' &&
    typeof commands.rollTorque === 'number'
  )
}

export function isEnvironmentUpdateMessage(value: unknown): value is EnvironmentUpdateMessage {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<EnvironmentUpdateMessage>
  return candidate.type === 'environment_update' && !!candidate.environment && typeof candidate.environment === 'object'
}

export function isSwarmUpdateMessage(value: unknown): value is SwarmUpdateMessage {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<SwarmUpdateMessage>
  return candidate.type === 'swarm_update' && !!candidate.decision && typeof candidate.decision === 'object'
}

export function isSwarmRoleMessage(value: unknown): value is SwarmRoleMessage {
  if (!value || typeof value !== 'object') return false
  const candidate = value as Partial<SwarmRoleMessage>
  return candidate.type === 'swarm_role' && ['producer', 'observer', 'available'].includes(candidate.role ?? '')
}
