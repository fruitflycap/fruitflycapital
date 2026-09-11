import { FlyActuators } from './FlyActuators'
import { FlyBody } from './FlyBody'
import type { FlyController } from './FlyController'
import { FlySensors, type OdorSampler } from './FlySensors'
import type { ActuatorCommand, SensorFrame } from '../networking/protocol'
import type { Vector3 } from 'three'

export type LandingState = 'cruise' | 'descending' | 'landed' | 'departing'
export type HabitatContactSampler = (position: Vector3) => boolean

// These are local sensory thresholds, not token-specific navigation commands.
// The former onset was high enough that a fly could pass through the readable
// part of the field without ever entering the approach state.
// Background plumes overlap across the large scene, but live market feeds can
// produce much quieter normalized odor values (the observed peak was ~0.16).
// Keep the threshold below that range so sensory approaches can actually
// enter descent and create a real contact/dwell window.
const LANDING_ODOR_ONSET = 0.14
// A habitat is not a permanent parking spot. A fly leaves when its local
// sensory signal fades or turns aversive, then resumes the same bounded
// search loop. This is driven by odor, not by an arbitrary departure timer.
// Keep release below the landing threshold. Otherwise a fly that lands on a
// quiet-but-valid plume would be told to depart on its very next frame.
const RELEASE_ODOR_THRESHOLD = 0.08

export class FlyAgent {
  readonly body = new FlyBody()
  readonly sensors = new FlySensors()
  readonly actuators = new FlyActuators()
  /** The command returned by the CNS before the local landing layer acts. */
  lastNeuralCommand: ActuatorCommand = neutralCommand()
  /** The command actually applied to the body after landing mechanics. */
  lastMotorCommand: ActuatorCommand = neutralCommand()
  landingState: LandingState = 'cruise'
  habitatContact = false
  // One hundred agents at 20 Hz would perform 40,000 eye raycasts per
  // second. Ten Hz is still faster than the default brain transport cadence
  // and keeps the fixed 120 Hz body integration independent of perception.
  private readonly sensorInterval = 1 / 10
  private sensorAccumulator = this.sensorInterval
  private flightTimeSeconds = 0
  private readonly searchPhase: number

  constructor(
    readonly id: string,
    private readonly controller: FlyController,
    spawnPosition?: Vector3,
  ) {
    this.searchPhase = Number(id.match(/(\d+)$/)?.[1] ?? 0) * 0.83
    if (spawnPosition) this.body.position.copy(spawnPosition)
  }

  get mode() {
    return this.controller.mode
  }

  snapshot() {
    return this.body.snapshot()
  }

  restore(snapshot: ReturnType<FlyBody['snapshot']>) {
    this.body.restore(snapshot)
    // A browser reload cannot restore the exact controller accumulator. Start
    // the body in cruise so a stale landed state cannot freeze the swarm.
    this.landingState = 'cruise'
    this.habitatContact = false
  }

  updateFixed(
    dt: number,
    bounds: Parameters<FlyBody['step']>[2],
    visualRoot: Parameters<FlySensors['update']>[1],
    odorSampler: OdorSampler,
    timeSeconds: number,
    habitatContactSampler: HabitatContactSampler = () => false,
  ) {
    this.flightTimeSeconds += dt
    this.sensorAccumulator += dt
    if (this.sensorAccumulator >= this.sensorInterval) {
      this.sensorAccumulator %= this.sensorInterval
      this.sensors.update(this.body, visualRoot, odorSampler, timeSeconds)
    }
    const frame = this.sensors.toFrame(this.body)
    const neuralCommand = this.controller.update({ frame, dt })
    this.lastNeuralCommand = { ...neuralCommand }
    const command = this.applyLandingMechanics(this.applySensoryFlightAssist(neuralCommand, frame), frame, dt)
    this.lastMotorCommand = { ...command }
    this.actuators.set(command)
    this.body.step(dt, this.actuators.get(), bounds)
    this.habitatContact = habitatContactSampler(this.body.position)
    this.updateLandingStateAfterStep(dt)
  }

  /**
   * Keep an unresponsive/offline brain feed visibly airborne and moving while
   * preserving the control boundary: this layer sees only the fly's odor and
   * motion sensors. It never receives a habitat ID, score, or target point.
   * Neural commands remain authoritative when they contain a stronger drive.
   */
  private applySensoryFlightAssist(command: ActuatorCommand, frame: SensorFrame) {
    const odor = frame.odor.concentration
    const odorGradient = frame.odor.rightAntenna - frame.odor.leftAntenna
    const searchWeight = Math.max(0.12, Math.min(1, 1 - odor * 3.2))
    const searchTurn = Math.sin(this.flightTimeSeconds * 0.62 + this.searchPhase) * 0.18 * searchWeight
    const odorTurn = Math.max(-0.9, Math.min(0.9, odorGradient * 120))
    // A fly with no decoded forward spikes still performs a bounded cruise;
    // otherwise a neutral websocket frame is visually indistinguishable from
    // a frozen simulation and it can never discover an odor source.
    const cruiseDrive = Math.max(0.42, Math.min(0.78, 0.48 + odor * 0.48))
    // A grounded explorer needs a short lift impulse to re-enter the air.
    // Once airborne, the neutral command is enough to maintain altitude.
    const cruiseLift = this.body.contact.ground ? 0.82 : 0.5
    return {
      ...command,
      forwardThrust: Math.max(command.forwardThrust, cruiseDrive),
      verticalThrust: Math.max(command.verticalThrust, cruiseLift),
      // The local bilateral signal gets priority over stale/noisy CNS frames
      // during discovery, while the neural yaw command remains a bounded
      // influence rather than being discarded.
      yawTorque: Math.max(-1, Math.min(1, command.yawTorque * 0.28 + odorTurn + searchTurn)),
    }
  }

  private applyLandingMechanics(command: ActuatorCommand, frame: SensorFrame, dt: number) {
    const odor = frame.odor.concentration
    const safeOdor = odor >= frame.odor.aversiveConcentration * 0.9
    if (this.landingState === 'cruise' && odor >= LANDING_ODOR_ONSET && safeOdor) {
      this.landingState = 'descending'
    } else if (this.landingState === 'descending' && this.body.contact.ground && !this.habitatContact) {
      // Once an odor cue has started an approach, finish the descent instead
      // of oscillating back into cruise because one low-sample frame briefly
      // falls outside the plume. If the ground was reached away from a
      // habitat, resume searching from there on the next cycle.
      this.landingState = 'cruise'
    }

    if (this.landingState === 'descending') {
      // Odor is the only descent trigger. The CNS still owns left/right
      // steering; this layer only supplies a bounded vertical approach and
      // slightly reduces forward speed so the fly can reach the source.
      const landingTurn = Math.max(-0.92, Math.min(0.92, (frame.odor.rightAntenna - frame.odor.leftAntenna) * 125))
      return {
        ...command,
        forwardThrust: Math.min(command.forwardThrust, Math.max(0.14, 0.42 - odor * 0.34)),
        // Hover is approximately 0.5. Remove lift during an odor-triggered
        // approach so gravity performs a real, visible descent instead of a
        // barely changing altitude. This is still a motor-level command, not
        // a target-position shortcut.
        verticalThrust: 0,
        yawTorque: Math.max(-1, Math.min(1, command.yawTorque + landingTurn)),
        // Keep the descent corridor level; yaw remains available for the
        // bilateral odor gradient, while pitch/roll cannot cancel gravity.
        pitchTorque: 0,
        rollTorque: 0,
      }
    }

    if (this.landingState === 'landed') {
      if (odorReleaseRequested(frame)) this.landingState = 'departing'
    }

    if (this.landingState === 'landed') {
      return {
        ...command,
        forwardThrust: 0,
        verticalThrust: 0.5,
        yawTorque: command.yawTorque * 0.22,
        pitchTorque: 0,
        rollTorque: 0,
      }
    }

    if (this.landingState === 'departing') {
      return {
        ...command,
        forwardThrust: Math.max(0.22, command.forwardThrust),
        verticalThrust: Math.max(0.72, command.verticalThrust),
      }
    }

    // Keep the fixed-step loop responsive if the state changes on this tick.
    void dt
    return command
  }

  private dwellSeconds = 0

  private updateLandingStateAfterStep(dt: number) {
    if (this.landingState === 'descending' && this.body.contact.ground && this.habitatContact) {
      this.landingState = 'landed'
      this.dwellSeconds = 0
    }
    if (this.landingState === 'landed') {
      if (!this.habitatContact || !this.body.contact.ground) {
        this.landingState = 'cruise'
        this.dwellSeconds = 0
        return
      }
      this.dwellSeconds += dt
      // Landing is a hold state, not a permanent parking state. The fly can
      // leave from a genuine neural impulse or when its local plume signal
      // fades/turns aversive; the observer still applies the trade hold
      // window before it records a SELL.
      if (commandRequestsDeparture(this.lastNeuralCommand)) this.landingState = 'departing'
    }
    if (this.landingState === 'departing' && !this.body.contact.ground && this.body.position.y > 0.06) {
      this.landingState = 'cruise'
    }
  }
}

function neutralCommand(): ActuatorCommand {
  return { forwardThrust: 0, verticalThrust: 0.5, yawTorque: 0, pitchTorque: 0, rollTorque: 0 }
}

function commandRequestsDeparture(command: ActuatorCommand) {
  return command.forwardThrust >= 0.55
    || Math.abs(command.pitchTorque) >= 0.48
    || Math.abs(command.rollTorque) >= 0.48
    || Math.abs(command.yawTorque) >= 0.78
    || command.verticalThrust >= 0.72
}

function odorReleaseRequested(frame: SensorFrame) {
  return frame.odor.concentration < RELEASE_ODOR_THRESHOLD
    || frame.odor.aversiveConcentration > frame.odor.concentration + 0.06
    || frame.odor.temporalChange < -0.018
}
