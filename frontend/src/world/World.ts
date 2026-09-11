import { Object3D, Scene, Vector3 } from 'three'
import { FlyAgent, type HabitatContactSampler } from '../fly/FlyAgent'
import { Environment } from './Environment'

export class World {
  readonly fixedDt = 1 / 120
  readonly environment: Environment
  readonly scene: Scene
  readonly agents: FlyAgent[]
  readonly agent: FlyAgent
  elapsedSeconds = 0
  private accumulator = 0
  private flyBoundary: Vector3[] | null = null

  constructor(scene: Scene, agents: FlyAgent | FlyAgent[], environment: Environment) {
    this.scene = scene
    this.agents = Array.isArray(agents) ? agents : [agents]
    this.agent = this.agents[0]!
    this.environment = environment
    this.scene.add(this.environment.group)
  }

  add(object: Object3D) {
    this.scene.add(object)
  }

  setFlyBoundary(points: readonly Vector3[] | null) {
    this.flyBoundary = points && points.length >= 3 ? points.map((point) => new Vector3(point.x, 0, point.z)) : null
  }

  update(realDeltaSeconds: number, habitatContactSampler: HabitatContactSampler = () => false) {
    this.accumulator += Math.min(realDeltaSeconds, 0.1)
    let steps = 0
    // Keep the interactive loop real-time. If a tab wakes up or a heavy asset
    // frame stalls rendering, do not run an unbounded backlog of physics steps
    // that makes the next frame even slower.
    while (this.accumulator >= this.fixedDt && steps < 6) {
      for (const agent of this.agents) {
        agent.updateFixed(
          this.fixedDt,
          this.environment.bounds,
          this.environment.group,
          (position, timeSeconds) => this.environment.sampleOdorAt(position, timeSeconds),
          this.elapsedSeconds,
          habitatContactSampler,
        )
        if (this.flyBoundary) constrainToBoundary(agent.body.position, agent.body.velocity, this.flyBoundary)
      }
      this.elapsedSeconds += this.fixedDt
      this.accumulator -= this.fixedDt
      steps += 1
    }
    if (steps === 6) this.accumulator = 0
    return steps
  }
}

function constrainToBoundary(position: Vector3, velocity: Vector3, boundary: readonly Vector3[]) {
  if (insideBoundary(position.x, position.z, boundary)) return
  let bestDistanceSq = Number.POSITIVE_INFINITY
  let bestX = position.x
  let bestZ = position.z
  for (let index = 0; index < boundary.length; index += 1) {
    const start = boundary[index]!
    const end = boundary[(index + 1) % boundary.length]!
    const dx = end.x - start.x
    const dz = end.z - start.z
    const lengthSq = dx * dx + dz * dz
    const t = lengthSq > 0 ? Math.max(0, Math.min(1, ((position.x - start.x) * dx + (position.z - start.z) * dz) / lengthSq)) : 0
    const x = start.x + dx * t
    const z = start.z + dz * t
    const distanceSq = (position.x - x) ** 2 + (position.z - z) ** 2
    if (distanceSq < bestDistanceSq) {
      bestDistanceSq = distanceSq
      bestX = x
      bestZ = z
    }
  }
  position.x = bestX
  position.z = bestZ
  velocity.x *= 0.2
  velocity.z *= 0.2
}

function insideBoundary(x: number, z: number, boundary: readonly Vector3[]) {
  let inside = false
  for (let index = 0, previous = boundary.length - 1; index < boundary.length; previous = index++) {
    const current = boundary[index]!
    const prior = boundary[previous]!
    const crosses = (current.z > z) !== (prior.z > z)
    if (crosses && x < ((prior.x - current.x) * (z - current.z)) / (prior.z - current.z) + current.x) inside = !inside
  }
  return inside
}
