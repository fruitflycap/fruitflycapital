import { PerspectiveCamera, Vector3 } from 'three'
import { FlyAgent } from '../fly/FlyAgent'

export class FollowCamera {
  readonly camera = new PerspectiveCamera(58, 1, 0.001, 100)
  private readonly desired = new Vector3()
  private readonly target = new Vector3()
  private readonly forward = new Vector3()
  private readonly up = new Vector3()

  constructor() {
    this.camera.position.set(0, 0.52, 0.08)
  }

  update(agent: FlyAgent) {
    const forward = this.forward.set(0, 0, -1).applyQuaternion(agent.body.quaternion).normalize()
    const up = this.up.set(0, 1, 0).applyQuaternion(agent.body.quaternion).normalize()
    this.desired.copy(agent.body.position).addScaledVector(forward, -0.14).addScaledVector(up, 0.05)
    this.target.copy(agent.body.position).addScaledVector(forward, 0.018)
    this.camera.position.lerp(this.desired, 0.12)
    this.camera.lookAt(this.target)
  }
}
