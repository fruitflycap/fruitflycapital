import { PerspectiveCamera, Vector3 } from 'three'
import { FlyAgent } from '../fly/FlyAgent'

export class SideCamera {
  readonly camera = new PerspectiveCamera(54, 1, 0.001, 100)
  private readonly target = new Vector3()

  constructor() {
    this.camera.position.set(1.3, 0.55, 0)
  }

  update(agent: FlyAgent) {
    this.target.copy(agent.body.position)
    this.camera.position.x = 1.3
    this.camera.position.y = Math.max(0.25, agent.body.position.y + 0.15)
    this.camera.position.z = agent.body.position.z
    this.camera.lookAt(this.target)
  }
}
