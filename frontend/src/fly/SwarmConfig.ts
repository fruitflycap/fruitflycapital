import { Vector3 } from 'three'

/** The strategy defaults to eight independent capital-bearing brains. */
const configuredSwarmSize = Number(import.meta.env.VITE_SWARM_SIZE)
export const SWARM_SIZE = Number.isInteger(configuredSwarmSize) && configuredSwarmSize >= 1 && configuredSwarmSize <= 100
  ? configuredSwarmSize
  : 8

// One canonical CNS controls one primary body plus this many render-only
// followers. Followers never sense, create brain runtimes, or cast consensus
// votes. This makes the demo visually read as a swarm without claiming that
// the browser is running 80 independent MaleCNS copies.
const configuredBodiesPerBrain = Number(import.meta.env.VITE_BODIES_PER_BRAIN)
// Keep the visual swarm dense by default: eight authoritative brains drive
// ten visible bodies each. The extra nine bodies are presentation followers,
// not additional strategy agents.
export const BODIES_PER_BRAIN = Number.isInteger(configuredBodiesPerBrain) && configuredBodiesPerBrain >= 1 && configuredBodiesPerBrain <= 12
  ? configuredBodiesPerBrain
  : 10
export const VISUAL_FLY_COUNT = SWARM_SIZE * BODIES_PER_BRAIN

/**
 * Shared initial condition. The small deterministic offsets stop the bodies
 * from spawning on top of one another while keeping the swarm visibly far
 * from the coin piles.
 */
// Launch in the middle of the actual city floor. The previous z=0.84 launch
// put most bodies beside the arena boundary, where a neural turn could look
// like a frozen swarm after the wall clamp engaged.
// Start closer to the street so the first approach/landing cycle is visible
// during a normal demo session while still leaving the flies clearly airborne.
export const SWARM_LAUNCH_CENTER = new Vector3(0, 0.38, 0)

export function swarmFlyId(index: number) {
  return `fly-${String(index + 1).padStart(3, '0')}`
}

export function swarmSpawnPosition(index: number) {
  const angle = index * 2.399963229728653
  const radius = 0.1 + (index % 5) * 0.025
  return new Vector3(
    SWARM_LAUNCH_CENTER.x + Math.cos(angle) * radius,
    SWARM_LAUNCH_CENTER.y + ((index % 7) - 3) * 0.012,
    SWARM_LAUNCH_CENTER.z + Math.sin(angle) * radius,
  )
}
