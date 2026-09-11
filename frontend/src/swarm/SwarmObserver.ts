import type { BehaviorTradeIntent, HabitatBehaviorTelemetry, TradeIntentReason } from '../networking/protocol'
import type { FlyAgent, LandingState } from '../fly/FlyAgent'
import type { TokenHabitat } from '../world/TokenHabitat'

export interface HabitatContactSample {
  contact: boolean
  habitatId: string | null
}

interface Track {
  flyId: string
  habitatId: string
  firstTimestampMs: number | null
  lastTimestampMs: number | null
  lastDistanceM: number | null
  inside: boolean
  contact: boolean
  approaching: boolean
  visits: number
  approaches: number
  departures: number
  dwellSeconds: number
  contactSeconds: number
  currentVisitDwellSeconds: number
  buyIssuedForVisit: boolean
  buyIssuedAtMs: number | null
  outsideSeconds: number
  departureCandidate: boolean
  lastLandingState: LandingState
  persistence: number
}

/**
 * Observes only primary CNS bodies and turns physical behavior into auditable
 * proposals. It never chooses a target, reads token scores, or talks to a
 * wallet. A buy is emitted only after genuine contact and dwell; a sell is
 * emitted when that same visit departs.
 */
export class SwarmObserver {
  private readonly tracks = new Map<string, Track>()
  private readonly pendingIntents: BehaviorTradeIntent[] = []
  private readonly activeCommitments = new Map<string, string>()
  private readonly lastIntentAtMs = new Map<string, number>()

  constructor(
    private readonly expectedAgents: number,
    private readonly minBuyDwellSeconds = 0.6,
    private readonly approachEpsilonM = 0.0005,
    private readonly departureDebounceSeconds = 0,
    private readonly minHoldSeconds = 0,
    private readonly intentCooldownSeconds = 0,
  ) {
    if (!Number.isInteger(expectedAgents) || expectedAgents < 1) throw new Error('expectedAgents must be positive')
  }

  observe(
    timestampMs: number,
    agents: readonly FlyAgent[],
    habitats: readonly TokenHabitat[],
    contactAt: (position: FlyAgent['body']['position']) => HabitatContactSample,
  ) {
    for (const agent of agents) {
      const contactSample = contactAt(agent.body.position)
      for (const habitat of habitats) {
        const habitatId = habitat.state.id
        const distanceM = agent.body.position.distanceTo(habitat.group.position)
        const radiusM = Math.max(0.001, habitat.properties.physicalRadiusM)
        const inside = distanceM <= radiusM
        const contact = contactSample.contact && contactSample.habitatId === habitatId
        const track = this.trackFor(agent.id, habitatId, agent.landingState)
        if (track.firstTimestampMs === null) track.firstTimestampMs = timestampMs
        const dtSeconds = track.lastTimestampMs === null
          ? 0
          : Math.min(2, Math.max(0, (timestampMs - track.lastTimestampMs) / 1000))
        const previousInside = track.inside
        const previousLandingState = track.lastLandingState

        if (inside && !previousInside) {
          const continuingHeldVisit = track.departureCandidate && track.buyIssuedForVisit
          if (!continuingHeldVisit) {
            track.visits += 1
            track.currentVisitDwellSeconds = 0
            track.buyIssuedForVisit = false
            track.buyIssuedAtMs = null
          } else {
            // A short boundary re-entry is part of the same held visit. Do
            // not turn geometry noise into a second BUY opportunity.
            track.departureCandidate = false
            track.outsideSeconds = 0
          }
        }
        if (inside) {
          track.dwellSeconds += dtSeconds
          track.currentVisitDwellSeconds += dtSeconds
          if (contact) track.contactSeconds += dtSeconds
        }
        if (previousInside && !inside) {
          track.departures += 1
          track.outsideSeconds = 0
          track.departureCandidate = track.buyIssuedForVisit
        }
        if (!inside) {
          track.outsideSeconds += dtSeconds
          if (
            track.departureCandidate &&
            track.buyIssuedForVisit &&
            track.buyIssuedAtMs !== null &&
            timestampMs - track.buyIssuedAtMs >= this.minHoldSeconds * 1000 &&
            track.outsideSeconds >= this.departureDebounceSeconds &&
            this.activeCommitments.get(track.flyId) === track.habitatId
          ) {
            this.emitIntent(track, 'sell', 'departure', timestampMs, distanceM, false)
            this.activeCommitments.delete(track.flyId)
            this.lastIntentAtMs.set(track.flyId, timestampMs)
            track.departureCandidate = false
            track.buyIssuedForVisit = false
            track.buyIssuedAtMs = null
            track.currentVisitDwellSeconds = 0
          } else if (!track.buyIssuedForVisit) {
            track.currentVisitDwellSeconds = 0
          }
        }

        const decreasing = track.lastDistanceM !== null && distanceM < track.lastDistanceM - this.approachEpsilonM
        if (!inside && decreasing && !track.approaching) {
          track.approaches += 1
        }
        track.approaching = Boolean(!inside && decreasing)

        if (
          contact &&
          agent.body.contact.ground &&
          agent.landingState === 'landed' &&
          track.currentVisitDwellSeconds >= this.minBuyDwellSeconds &&
          !track.buyIssuedForVisit &&
          this.activeCommitments.get(track.flyId) === undefined &&
          this.cooldownElapsed(track.flyId, timestampMs)
        ) {
          this.emitIntent(track, 'buy', 'dwell', timestampMs, distanceM, true)
          this.activeCommitments.set(track.flyId, track.habitatId)
          this.lastIntentAtMs.set(track.flyId, timestampMs)
          track.buyIssuedForVisit = true
          track.buyIssuedAtMs = timestampMs
        } else if (previousLandingState === 'landed' && agent.landingState === 'departing' && track.buyIssuedForVisit) {
          // Mark the departure, then wait for the same body to remain outside
          // the habitat for the debounce window before emitting SELL.
          track.departureCandidate = true
        }

        const activeSpan = track.firstTimestampMs === null ? 0 : Math.max(0, (timestampMs - track.firstTimestampMs) / 1000)
        track.persistence = Math.min(1, track.dwellSeconds / Math.max(activeSpan, track.dwellSeconds, 1e-9))
        track.inside = inside
        track.contact = contact
        track.lastLandingState = agent.landingState
        track.lastTimestampMs = timestampMs
        track.lastDistanceM = distanceM
      }
    }
  }

  drainIntents(): BehaviorTradeIntent[] {
    return this.pendingIntents.splice(0, this.pendingIntents.length)
  }

  telemetryFor(flyId: string, habitatId: string): HabitatBehaviorTelemetry | undefined {
    const track = this.tracks.get(this.key(flyId, habitatId))
    if (!track) return undefined
    return {
      approaches: track.approaches,
      visits: track.visits,
      departures: track.departures,
      dwellSeconds: round(track.dwellSeconds),
      repeatVisits: Math.max(0, track.visits - 1),
      contactSeconds: round(track.contactSeconds),
      persistence: round(track.persistence),
      approaching: track.approaching,
    }
  }

  /** Useful for a compact product/debug counter without exposing internals. */
  pendingIntentCount() {
    return this.pendingIntents.length
  }

  private trackFor(flyId: string, habitatId: string, landingState: LandingState) {
    const key = this.key(flyId, habitatId)
    let track = this.tracks.get(key)
    if (!track) {
      track = {
        flyId,
        habitatId,
        firstTimestampMs: null,
        lastTimestampMs: null,
        lastDistanceM: null,
        inside: false,
        contact: false,
        approaching: false,
        visits: 0,
        approaches: 0,
        departures: 0,
        dwellSeconds: 0,
        contactSeconds: 0,
        currentVisitDwellSeconds: 0,
        buyIssuedForVisit: false,
        buyIssuedAtMs: null,
        outsideSeconds: 0,
        departureCandidate: false,
        lastLandingState: landingState,
        persistence: 0,
      }
      this.tracks.set(key, track)
    }
    return track
  }

  private emitIntent(
    track: Track,
    side: BehaviorTradeIntent['side'],
    reason: TradeIntentReason,
    observedAtMs: number,
    distanceM: number,
    contact: boolean,
  ) {
    const repeatVisits = Math.max(0, track.visits - 1)
    const confidence = Math.min(1, Math.max(0,
      0.45 * Math.min(1, track.currentVisitDwellSeconds / 3) +
      0.25 * Math.min(1, track.contactSeconds / 3) +
      0.15 * Math.min(1, (track.approaches + repeatVisits) / 4) +
      0.15 * track.persistence,
    ))
    this.pendingIntents.push({
      intentId: `${track.flyId}:${track.habitatId}:${side}:${track.visits}:${observedAtMs}`,
      flyId: track.flyId,
      habitatId: track.habitatId,
      side,
      reason,
      confidence: round(confidence),
      observedAtMs,
      // Preserve the former sixteen-brain 6.25% capital ceiling when the
      // active population is reduced to eight.
      portfolioWeight: Math.min(1 / this.expectedAgents, 0.0625),
      metrics: {
        distanceM: round(distanceM),
        visits: track.visits,
        approaches: track.approaches,
        dwellSeconds: round(track.currentVisitDwellSeconds),
        repeatVisits,
        departures: track.departures,
        contact,
        persistence: round(track.persistence),
      },
    })
  }

  private key(flyId: string, habitatId: string) {
    return `${flyId}\u0000${habitatId}`
  }

  private cooldownElapsed(flyId: string, timestampMs: number) {
    const lastIntentAtMs = this.lastIntentAtMs.get(flyId)
    return lastIntentAtMs === undefined || timestampMs - lastIntentAtMs >= this.intentCooldownSeconds * 1000
  }
}

function round(value: number) {
  return Math.round(value * 1000) / 1000
}
