import { Object3D, PerspectiveCamera, Vector3 } from 'three'
import type { FlyAgent } from '../fly/FlyAgent'
import type { TokenHabitat } from '../world/TokenHabitat'
import { PRESENTATION_SCENE_HALF_EXTENT } from '../world/Arena'

export type PresentationCameraMode = 'overview' | 'token' | 'director'
type TradeEventSide = 'buy' | 'sell'

interface TradeEventFocus {
  flyId: string
  habitatId: string
  side: TradeEventSide
  expiresAtMs: number
}

export class PresentationCamera {
  readonly camera = new PerspectiveCamera(52, 1, 0.001, 100)
  private mode: PresentationCameraMode = 'overview'
  private readonly desired = new Vector3()
  private readonly target = new Vector3()
  private readonly center = new Vector3()
  private readonly orientation = new Object3D()
  private readonly forward = new Vector3()
  private readonly overviewDirection = new Vector3(0.58, 0.42, 0.7).normalize()
  private tradeEventFocus: TradeEventFocus | null = null
  private lastTradeEventFocusAtMs = Number.NEGATIVE_INFINITY

  constructor() {
    // Start cinematic mode from a clearly floor-facing establishing shot.
    // This also prevents a previous free-orbit pose from leaving the first
    // cinematic frames pointed at the star field.
    this.camera.position.set(1.65, 1.55, 1.85)
    this.camera.lookAt(0, 0.08, 0)
  }

  setMode(mode: PresentationCameraMode) {
    this.mode = mode
    if (mode !== 'director') this.tradeEventFocus = null
  }

  get currentMode() {
    return this.mode
  }

  /**
   * Request a restrained director cut for a fresh biological trade event.
   * The cooldown keeps a burst of simultaneous fly intents from turning the
   * cinematic view into a camera chase.
   */
  focusOnTradeEvent(flyId: string, habitatId: string, side: TradeEventSide) {
    const nowMs = performance.now()
    if (nowMs - this.lastTradeEventFocusAtMs < 16000) return false
    this.lastTradeEventFocusAtMs = nowMs
    this.tradeEventFocus = { flyId, habitatId, side, expiresAtMs: nowMs + (side === 'sell' ? 6500 : 7500) }
    return true
  }

  update(timeSeconds: number, agents: FlyAgent[], habitats: TokenHabitat[], selectedIndex: number) {
    const selected = agents[selectedIndex]
    const eventFocus = this.tradeEventFocus
    const eventAgent = eventFocus ? agents.find((agent) => agent.id === eventFocus.flyId) : undefined
    const eventHabitat = eventFocus ? habitats.find((habitat) => habitat.state.id === eventFocus.habitatId) : undefined
    const eventFocusActive = Boolean(this.mode === 'director' && eventFocus && performance.now() < eventFocus.expiresAtMs && eventAgent && eventHabitat)
    if (eventFocus && !eventFocusActive) this.tradeEventFocus = null
    if (eventFocusActive && eventAgent && eventHabitat) {
      // Aim between the fly and its habitat so the audience can read both the
      // biological source and the token place receiving the intent.
      this.target.copy(eventHabitat.group.position).lerp(eventAgent.body.position, 0.32)
      this.target.y = Math.max(0.055, Math.min(0.22, this.target.y))
      this.desired.copy(this.target).add(new Vector3(0.24, 0.16, 0.24))
    } else if (this.mode === 'token' && habitats.length > 0) {
      const habitat = habitats[Math.floor(timeSeconds / 8) % habitats.length]!
      this.target.copy(habitat.group.position).add(new Vector3(0, 0.045, 0))
      this.desired.copy(this.target).add(new Vector3(0.28, 0.18, 0.3))
    } else if (this.mode === 'director' && selected) {
      // Hold each shot long enough to read the behavior log. The director
      // still cuts between three shot types, but transitions are deliberately
      // slow and eased instead of snapping every few seconds.
      const phase = timeSeconds % 36
      if (phase < 18) {
        this.center.set(0, 0, 0)
        agents.forEach((agent) => this.center.add(agent.body.position))
        this.center.multiplyScalar(1 / Math.max(1, agents.length))
        this.target.copy(this.center)
        const wideDistance = 1.45 + (Math.floor(timeSeconds / 36) % 2) * 0.42
        this.desired.copy(this.center).add(new Vector3(0.58, 0.78, 0.72).normalize().multiplyScalar(wideDistance))
      } else if (phase < 28 && habitats.length > 0) {
        const habitat = habitats[Math.floor((timeSeconds - 18) / 10) % habitats.length]!
        this.target.copy(habitat.group.position).add(new Vector3(0, 0.045, 0))
        const mediumDistance = 0.46 + (Math.floor(timeSeconds / 36) % 3) * 0.12
        this.desired.copy(this.target).add(new Vector3(0.72, 0.42, 0.72).normalize().multiplyScalar(mediumDistance))
      } else {
        // The final shot is an occasional fly-eye view: close to the agent,
        // but still slightly above the floor so the subject remains visible.
        this.forward.set(0, 0, -1).applyQuaternion(selected.body.quaternion).normalize()
        // Flybody can briefly report a pitched/rolled orientation while it is
        // settling. Use only its horizontal heading for the camera so a
        // transient body rotation can never aim the shot into the sky or
        // below the floor.
        this.forward.y = 0
        if (this.forward.lengthSq() < 0.0001) this.forward.set(0, 0, -1)
        this.forward.normalize()
        this.target.copy(selected.body.position).addScaledVector(this.forward, 0.14).add(new Vector3(0, 0.035, 0))
        this.desired.copy(selected.body.position).addScaledVector(this.forward, -0.025).add(new Vector3(0, 0.11, 0))
      }
    } else {
      const swarmRadius = this.setSwarmCenter(agents)
      this.target.copy(this.center)
      // Keep the entire population in frame as agents spread through the
      // room. The overview is a camera fit, not a second simulation rule.
      const verticalFov = this.camera.fov * Math.PI / 180
      const fitDistance = swarmRadius / Math.tan(verticalFov / 2) * 1.35
      this.desired.copy(this.center).addScaledVector(this.overviewDirection, Math.max(0.95, Math.min(4, fitDistance)))
    }
    this.clampShot()
    this.camera.position.lerp(this.desired, 0.025)
    this.camera.position.y = Math.max(0.09, this.camera.position.y)
    this.orientation.position.copy(this.camera.position)
    this.orientation.lookAt(this.target)
    this.camera.quaternion.slerp(this.orientation.quaternion, 0.08)
    // Keep the camera's final aim authoritative. The target has already been
    // clamped above the floor, so this cannot drift into the sky during a
    // long cinematic transition.
    this.camera.lookAt(this.target)
  }

  private setSwarmCenter(agents: FlyAgent[]) {
    this.center.set(0, 0, 0)
    agents.forEach((agent) => this.center.add(agent.body.position))
    this.center.multiplyScalar(1 / Math.max(1, agents.length))
    return Math.max(0.12, ...agents.map((agent) => agent.body.position.distanceTo(this.center)))
  }

  private clampShot() {
    const limit = PRESENTATION_SCENE_HALF_EXTENT - 0.12
    this.target.x = Math.max(-limit, Math.min(limit, this.target.x))
    this.target.y = Math.max(0.035, Math.min(0.42, this.target.y))
    this.target.z = Math.max(-limit, Math.min(limit, this.target.z))
    this.desired.x = Math.max(-limit, Math.min(limit, this.desired.x))
    this.desired.y = Math.max(0.09, Math.min(1.8, this.desired.y))
    this.desired.z = Math.max(-limit, Math.min(limit, this.desired.z))
  }
}
