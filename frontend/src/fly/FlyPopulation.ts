import { BrainSocket } from '../networking/BrainSocket'
import { FlyAgent } from './FlyAgent'
import { MaleCNSController } from './FlyController'
import { FlyRenderer } from '../rendering/FlyRenderer'
import { SWARM_SIZE, swarmFlyId, swarmSpawnPosition } from './SwarmConfig'
import { BODIES_PER_BRAIN } from './SwarmConfig'
import { VisualFlyFollower } from './VisualFlyFollower'
import { Vector3 } from 'three'

export interface FlyPopulationOptions {
  brainSocket: BrainSocket
  brainUpdateHz: number
  size?: number
}

/**
 * Owns the population boundary. There are no decorative members here:
 * each entry has its own body, sensor state, controller, renderer, and
 * flyId-backed server runtime.
 */
export class FlyPopulation {
  readonly agents: FlyAgent[] = []
  readonly controllers: MaleCNSController[] = []
  readonly renderers: FlyRenderer[] = []
  readonly followers: VisualFlyFollower[] = []
  private _selectedIndex = 0

  constructor(options: FlyPopulationOptions) {
    const size = options.size ?? SWARM_SIZE
    if (!Number.isInteger(size) || size < 1) throw new Error('FlyPopulation size must be a positive integer')

    for (let index = 0; index < size; index += 1) {
      const id = swarmFlyId(index)
      const controller = new MaleCNSController(options.brainSocket, id, options.brainUpdateHz, index * 0.05)
      this.controllers.push(controller)
      const agent = new FlyAgent(id, controller, swarmSpawnPosition(index))
      // Independent agents do not share an initial heading. This is an
      // initial-condition difference, not a hidden navigation policy: after
      // spawn, every heading change still comes only from that fly's actuator
      // command. Without it, identical far-field sensory frames make a
      // healthy population look like one cloned trajectory.
      agent.body.quaternion.setFromAxisAngle(new Vector3(0, 1, 0), -0.72 + index * 0.31)
      this.agents.push(agent)
      this.renderers.push(new FlyRenderer())
      for (let slot = 1; slot < BODIES_PER_BRAIN; slot += 1) {
        this.followers.push(new VisualFlyFollower(agent, slot - 1, index))
      }
    }
  }

  get size() {
    return this.agents.length
  }

  get selectedIndex() {
    return this._selectedIndex
  }

  get selectedAgent() {
    return this.agents[this._selectedIndex]!
  }

  select(index: number) {
    this._selectedIndex = Math.min(this.size - 1, Math.max(0, Math.floor(index)))
    return this._selectedIndex
  }
}
