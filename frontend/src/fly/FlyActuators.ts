import type { ActuatorCommand } from '../networking/protocol'

export const neutralActuators = (): ActuatorCommand => ({
  // Neutral means hover/idle. Forward flight is an explicit actuator input,
  // not an always-on default that can drive a fly into a wall.
  forwardThrust: 0,
  verticalThrust: 0.5,
  yawTorque: 0,
  pitchTorque: 0,
  rollTorque: 0,
})

export class FlyActuators {
  private current = neutralActuators()

  set(command: ActuatorCommand) {
    this.current = {
      forwardThrust: clamp(command.forwardThrust, 0, 1),
      verticalThrust: clamp(command.verticalThrust, 0, 1),
      yawTorque: clamp(command.yawTorque, -1, 1),
      pitchTorque: clamp(command.pitchTorque, -1, 1),
      rollTorque: clamp(command.rollTorque, -1, 1),
    }
  }

  get(): ActuatorCommand {
    return { ...this.current }
  }
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, Number.isFinite(value) ? value : 0))
}
