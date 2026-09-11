/**
 * Small TypeScript port of Flybody's WingBeatPatternGenerator interface.
 *
 * The canonical numerical source is vendored at third_party/flybody. This
 * bridge keeps the same control concept (218 Hz baseline, +/-5% frequency
 * modulation, phase-continuous updates) for the Three.js view. MuJoCo remains
 * the authoritative physics path when the optional backend is connected.
 */
export interface WingAngles {
  leftYaw: number
  leftRoll: number
  leftPitch: number
  rightYaw: number
  rightRoll: number
  rightPitch: number
}

export class WingBeatPatternGenerator {
  readonly baseBeatFrequencyHz: number
  readonly relativeFrequencyRange: number
  private phase = 0
  private frequencyHz: number
  private lastAngles: WingAngles = this.anglesAt(0)

  constructor(baseBeatFrequencyHz = 218, relativeFrequencyRange = 0.05) {
    this.baseBeatFrequencyHz = baseBeatFrequencyHz
    this.relativeFrequencyRange = relativeFrequencyRange
    this.frequencyHz = baseBeatFrequencyHz
  }

  reset(initialPhase = 0) {
    this.phase = initialPhase - Math.floor(initialPhase)
    this.lastAngles = this.anglesAt(this.phase)
    return this.lastAngles
  }

  step(dtSeconds: number, activity = 1) {
    const boundedActivity = Math.min(1, Math.max(0, activity))
    this.frequencyHz = this.baseBeatFrequencyHz * (1 + this.relativeFrequencyRange * (boundedActivity * 2 - 1))
    this.phase = (this.phase + dtSeconds * this.frequencyHz) % 1
    this.lastAngles = this.anglesAt(this.phase)
    return this.lastAngles
  }

  getLastAngles() {
    return this.lastAngles
  }

  private anglesAt(phase: number): WingAngles {
    const x = phase * Math.PI * 2
    // These are the same documented fallback waveform coefficients used by
    // Flybody when no measured one-cycle pattern is supplied.
    const yaw = 1.1 * Math.sin(x - Math.PI / 2) + 0.3
    const roll = 0.25 * Math.sin(1.5 * x) - 0.1
    const pitch = 1.35 * Math.sin(x) + 0.8
    return {
      leftYaw: yaw,
      leftRoll: roll,
      leftPitch: pitch,
      rightYaw: yaw,
      rightRoll: -roll,
      rightPitch: pitch,
    }
  }
}
