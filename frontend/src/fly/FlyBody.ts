import { Euler, Quaternion, Vector3 } from 'three'
import type { ActuatorCommand } from '../networking/protocol'

export interface WorldBounds {
  min: Vector3
  max: Vector3
}

export interface BodyContact {
  ground: boolean
  obstacle: boolean
  wall: boolean
}

export interface FlyBodySnapshot {
  position: { x: number; y: number; z: number }
  velocity: { x: number; y: number; z: number }
  quaternion: { x: number; y: number; z: number; w: number }
  angularVelocity: { x: number; y: number; z: number }
}

export class FlyBody {
  readonly position = new Vector3(0, 0.48, 0)
  readonly velocity = new Vector3()
  readonly quaternion = new Quaternion()
  readonly angularVelocity = new Vector3()
  readonly contact: BodyContact = { ground: false, obstacle: false, wall: false }

  readonly massKg = 0.001
  readonly inertia = new Vector3(0.0000012, 0.0000015, 0.0000011)
  // The previous force made a neutral/assist cruise settle around a barely
  // visible crawl. This remains a bounded millimetre-scale body force, but it
  // gives the 6m presentation scene enough travel to reach a habitat.
  readonly maxForwardForceN = 0.0026
  // Keep the same neutral hover ratio (~0.55), but increase the vertical
  // authority so an odor-triggered zero-lift command reaches the floor in a
  // few seconds instead of looking frozen for most of the demo.
  readonly maxVerticalForceN = 0.00016
  // Match the neutral 0.5 vertical command so an exploring fly does not
  // slowly sink onto the floor between habitat visits.
  readonly gravityN = 0.00008
  // The previous value made a boundary turn take many seconds at this
  // millimetre-scale inertia. This remains a small rigid-body torque, but it
  // gives the shared actuator interface enough authority to leave a wall
  // without the old high-rate spinning behaviour.
  readonly maxTorqueNm = 0.000006
  readonly maxSpeedMps = 0.68
  // A 6 rad/s hard cap made a held yaw command spin the body like a
  // turntable. This lower physical rate limit keeps heading changes visible
  // while preserving the same actuator interface for every controller.
  readonly maxAngularSpeedRadS = 2.2
  readonly linearDrag = 0.0032
  readonly angularDrag = 4.0
  // Approximate adult-fly collision radius in metres; the rendered mesh uses
  // the same physical scale rather than an arbitrary room-sized avatar.
  readonly collisionRadius = 0.0025

  snapshot(): FlyBodySnapshot {
    return {
      position: { x: this.position.x, y: this.position.y, z: this.position.z },
      velocity: { x: this.velocity.x, y: this.velocity.y, z: this.velocity.z },
      quaternion: { x: this.quaternion.x, y: this.quaternion.y, z: this.quaternion.z, w: this.quaternion.w },
      angularVelocity: { x: this.angularVelocity.x, y: this.angularVelocity.y, z: this.angularVelocity.z },
    }
  }

  restore(snapshot: FlyBodySnapshot) {
    this.position.set(snapshot.position.x, snapshot.position.y, snapshot.position.z)
    this.velocity.set(snapshot.velocity.x, snapshot.velocity.y, snapshot.velocity.z)
    this.quaternion.set(snapshot.quaternion.x, snapshot.quaternion.y, snapshot.quaternion.z, snapshot.quaternion.w).normalize()
    this.angularVelocity.set(snapshot.angularVelocity.x, snapshot.angularVelocity.y, snapshot.angularVelocity.z)
  }
  private readonly forward = new Vector3()
  private readonly up = new Vector3()
  private readonly force = new Vector3()
  private readonly localTorque = new Vector3()
  private readonly angularAcceleration = new Vector3()
  private readonly rotationAxis = new Vector3()
  private readonly rotationDelta = new Quaternion()
  private readonly smoothedCommand: ActuatorCommand = {
    forwardThrust: 0,
    verticalThrust: 0.5,
    yawTorque: 0,
    pitchTorque: 0,
    rollTorque: 0,
  }

  step(dt: number, command: ActuatorCommand, bounds: WorldBounds) {
    // Brain responses arrive at a much lower cadence than the render/physics
    // loop. Blend the motor command in the body, so each new neural window
    // produces continuous acceleration instead of visible 2 Hz jolts.
    const commandAlpha = 1 - Math.exp(-14 * dt)
    this.smoothedCommand.forwardThrust += (command.forwardThrust - this.smoothedCommand.forwardThrust) * commandAlpha
    this.smoothedCommand.verticalThrust += (command.verticalThrust - this.smoothedCommand.verticalThrust) * commandAlpha
    this.smoothedCommand.yawTorque += (command.yawTorque - this.smoothedCommand.yawTorque) * commandAlpha
    this.smoothedCommand.pitchTorque += (command.pitchTorque - this.smoothedCommand.pitchTorque) * commandAlpha
    this.smoothedCommand.rollTorque += (command.rollTorque - this.smoothedCommand.rollTorque) * commandAlpha

    const forward = this.forward.set(0, 0, -1).applyQuaternion(this.quaternion).normalize()
    const up = this.up.set(0, 1, 0).applyQuaternion(this.quaternion).normalize()
    const force = this.force.copy(forward).multiplyScalar(this.smoothedCommand.forwardThrust * this.maxForwardForceN)
    force.addScaledVector(up, this.smoothedCommand.verticalThrust * this.maxVerticalForceN)
    force.y -= this.gravityN
    this.removeOutwardBoundaryForce(force, bounds)
    force.addScaledVector(this.velocity, -this.linearDrag)
    this.velocity.addScaledVector(force, dt / this.massKg)
    this.velocity.multiplyScalar(Math.exp(-this.linearDrag * 2 * dt))
    if (this.velocity.lengthSq() > this.maxSpeedMps ** 2) this.velocity.setLength(this.maxSpeedMps)
    this.position.addScaledVector(this.velocity, dt)

    // Angular velocity is kept in the fly/body frame. With Three.js forward
    // defined as local -Z, a positive right-yaw command must rotate about -Y:
    // local -Z -> world +X. This keeps the keyboard D command, the decoder's
    // documented positive-right sign, the heading arrow, and the canonical
    // Flybody head direction consistent.
    const localTorque = this.localTorque.set(this.smoothedCommand.pitchTorque, -this.smoothedCommand.yawTorque, this.smoothedCommand.rollTorque)
    const angularAcceleration = this.angularAcceleration.set(
      (localTorque.x * this.maxTorqueNm) / this.inertia.x,
      (localTorque.y * this.maxTorqueNm) / this.inertia.y,
      (localTorque.z * this.maxTorqueNm) / this.inertia.z,
    )
    this.angularVelocity.addScaledVector(angularAcceleration, dt)
    this.angularVelocity.multiplyScalar(Math.exp(-this.angularDrag * dt))
    if (this.angularVelocity.lengthSq() > this.maxAngularSpeedRadS ** 2) this.angularVelocity.setLength(this.maxAngularSpeedRadS)
    const angle = this.angularVelocity.length() * dt
    if (angle > 0.0000001) {
      const delta = this.rotationDelta.setFromAxisAngle(this.rotationAxis.copy(this.angularVelocity).normalize(), angle)
      this.quaternion.multiply(delta).normalize()
    }
    this.resolveBounds(bounds)
  }

  private resolveBounds(bounds: WorldBounds) {
    this.contact.ground = false
    this.contact.obstacle = false
    this.contact.wall = false
    const minY = bounds.min.y + this.collisionRadius
    const maxY = bounds.max.y - this.collisionRadius
    if (this.position.x < bounds.min.x + this.collisionRadius) {
      this.contact.wall = true
      this.position.x = bounds.min.x + this.collisionRadius
      // Remove only the outward component. Reflecting it caused a repeated
      // bounce/thrust loop when the controller continued to command forward.
      if (this.velocity.x < 0) this.velocity.x = 0
    } else if (this.position.x > bounds.max.x - this.collisionRadius) {
      this.contact.wall = true
      this.position.x = bounds.max.x - this.collisionRadius
      if (this.velocity.x > 0) this.velocity.x = 0
    }
    if (this.position.z < bounds.min.z + this.collisionRadius) {
      this.contact.wall = true
      this.position.z = bounds.min.z + this.collisionRadius
      if (this.velocity.z < 0) this.velocity.z = 0
    } else if (this.position.z > bounds.max.z - this.collisionRadius) {
      this.contact.wall = true
      this.position.z = bounds.max.z - this.collisionRadius
      if (this.velocity.z > 0) this.velocity.z = 0
    }
    if (this.position.y < minY) {
      this.contact.ground = true
      this.position.y = minY
      this.velocity.y = Math.max(0, this.velocity.y) * 0.1
    } else if (this.position.y > maxY) {
      this.position.y = maxY
      this.velocity.y = -Math.abs(this.velocity.y) * 0.25
    }
  }

  private removeOutwardBoundaryForce(force: Vector3, bounds: WorldBounds) {
    const margin = this.collisionRadius + 0.001
    if (this.position.x <= bounds.min.x + margin && force.x < 0) force.x = 0
    if (this.position.x >= bounds.max.x - margin && force.x > 0) force.x = 0
    if (this.position.z <= bounds.min.z + margin && force.z < 0) force.z = 0
    if (this.position.z >= bounds.max.z - margin && force.z > 0) force.z = 0
  }

  getEuler() {
    return new Euler().setFromQuaternion(this.quaternion, 'YXZ')
  }
}
