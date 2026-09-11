import type { ActuatorCommand, FlyMode, SensorFrame } from '../networking/protocol'
import { BrainSocket } from '../networking/BrainSocket'
import { neutralActuators } from './FlyActuators'

export interface ControllerInput {
  frame: SensorFrame
  dt: number
}

export interface FlyController {
  readonly mode: FlyMode
  update(input: ControllerInput): ActuatorCommand
}

export class KeyboardState {
  private readonly pressed = new Set<string>()

  constructor(target: Window = window) {
    target.addEventListener('keydown', (event) => {
      this.pressed.add(event.code)
      if (['ShiftLeft', 'ShiftRight', 'ControlLeft', 'ControlRight', 'Space'].includes(event.code)) event.preventDefault()
    })
    target.addEventListener('keyup', (event) => this.pressed.delete(event.code))
    target.addEventListener('blur', () => this.pressed.clear())
  }

  isDown(...codes: string[]) {
    return codes.some((code) => this.pressed.has(code))
  }
}

export class ManualController implements FlyController {
  readonly mode = 'manual' as const

  constructor(
    private readonly keyboard: KeyboardState,
    private readonly enabled: () => boolean = () => true,
  ) {}

  update(): ActuatorCommand {
    if (!this.enabled()) return neutralActuators()
    const pitchTorque = (this.keyboard.isDown('KeyS') ? 1 : 0) - (this.keyboard.isDown('KeyW') ? 1 : 0)
    const yawTorque = (this.keyboard.isDown('KeyD') ? 1 : 0) - (this.keyboard.isDown('KeyA') ? 1 : 0)
    const rollTorque = (this.keyboard.isDown('KeyE') ? 1 : 0) - (this.keyboard.isDown('KeyQ') ? 1 : 0)
    const shift = this.keyboard.isDown('ShiftLeft', 'ShiftRight')
    const control = this.keyboard.isDown('ControlLeft', 'ControlRight')
    return {
      forwardThrust: clamp01((shift ? 0.7 : 0) - (control ? 0.22 : 0)),
      verticalThrust: clamp01(0.5 + (shift ? 0.12 : 0) - (control ? 0.48 : 0)),
      yawTorque,
      pitchTorque,
      rollTorque,
    }
  }
}

export class MaleCNSController implements FlyController {
  readonly mode = 'malecns' as const
  private elapsed = 0
  private readonly initialDelaySeconds: number

  constructor(
    private readonly socket: BrainSocket,
    private readonly flyId: string,
    private readonly brainUpdateHz = 20,
    initialDelaySeconds = 0,
  ) {
    this.initialDelaySeconds = Math.max(0, initialDelaySeconds)
  }

  update(input: ControllerInput): ActuatorCommand {
    this.elapsed += input.dt
    if (this.elapsed < this.initialDelaySeconds) return this.socket.commandsFor(this.flyId)
    if (this.elapsed >= 1 / this.brainUpdateHz) {
      this.elapsed = 0
      // The MaleCNS encoder consumes the eye summaries and odor values. Do
      // not send the 20 ray samples for every pilot agent on every update;
      // the full frame remains available to the selected debug view.
      this.socket.send({ type: 'brain_input', flyId: this.flyId, mode: this.mode, sensors: compactSensorFrame(input.frame) })
    }
    const command = this.socket.commandsFor(this.flyId)
    // The backend command already includes the low-level Flybody boundary.
    // Reading the activity here is intentionally diagnostic-only; this
    // controller never receives token identity, scores, or target positions.
    return command
  }
}

export class SwitchableController implements FlyController {
  private active: FlyController

  constructor(
    private readonly manual: ManualController,
    private readonly malecns: MaleCNSController,
  ) {
    this.active = malecns
  }

  get mode() {
    return this.active.mode
  }

  toggleMode() {
    this.active = this.active.mode === 'malecns' ? this.manual : this.malecns
  }

  setMode(mode: 'manual' | 'malecns') {
    this.active = mode === 'manual' ? this.manual : this.malecns
  }

  update(input: ControllerInput) {
    return this.active.update(input)
  }
}

function clamp01(value: number) {
  return Math.min(1, Math.max(0, value))
}

function compactSensorFrame(frame: ControllerInput['frame']): ControllerInput['frame'] {
  return {
    ...frame,
    leftEye: { ...frame.leftEye, samples: [] },
    rightEye: { ...frame.rightEye, samples: [] },
  }
}
