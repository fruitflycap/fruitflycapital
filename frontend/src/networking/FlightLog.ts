import type { ActuatorCommand } from './protocol'
import type { BrainSocket } from './BrainSocket'
import type { MaleCNSSensoryStimulation, SensorFrame } from './protocol'
import type { FlyAgent } from '../fly/FlyAgent'

export interface FlightLogEntry {
  timestampSeconds: number
  sensoryInput: SensorFrame
  stimulatedBodyIds: number[]
  spikeCounts: Record<string, number>
  descendingRatesHz: Record<string, number>
  motorOutput: ActuatorCommand
  position: { x: number; y: number; z: number }
  rotation: { x: number; y: number; z: number; w: number }
  velocity: { x: number; y: number; z: number }
}

export class FlightLogger {
  readonly entries: FlightLogEntry[] = []

  record(agent: FlyAgent, socket: BrainSocket, timestampSeconds: number) {
    const stimulation = socket.stimulationFor(agent.id)
    const activity = socket.activityFor(agent.id)
    this.entries.push({
      timestampSeconds,
      sensoryInput: agent.sensors.toFrame(agent.body),
      stimulatedBodyIds: stimulatedBodyIds(stimulation),
      spikeCounts: activity?.spikeCounts ?? {},
      descendingRatesHz: activity?.descendingRates ?? {},
      motorOutput: { ...agent.actuators.get() },
      position: { x: agent.body.position.x, y: agent.body.position.y, z: agent.body.position.z },
      rotation: { x: agent.body.quaternion.x, y: agent.body.quaternion.y, z: agent.body.quaternion.z, w: agent.body.quaternion.w },
      velocity: { x: agent.body.velocity.x, y: agent.body.velocity.y, z: agent.body.velocity.z },
    })
  }

  download() {
    const blob = new Blob([JSON.stringify(this.entries, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `malecns-flight-${new Date().toISOString().replaceAll(':', '-')}.json`
    link.click()
    URL.revokeObjectURL(url)
  }
}

function stimulatedBodyIds(stimulation: MaleCNSSensoryStimulation | null) {
  if (!stimulation) return []
  return [...stimulation.visual, ...stimulation.olfactory, ...stimulation.mechanosensory].map((entry) => entry.bodyId)
}
