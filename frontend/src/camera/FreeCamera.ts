import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { PerspectiveCamera, Vector3 } from 'three'
import { PRESENTATION_SCENE_HALF_EXTENT } from '../world/Arena'

/** Keep the observer inside the presentation world while preserving orbit. */
export const FREE_CAMERA_LIMITS = {
  floorY: 0.02,
  minPolarAngle: 0.18,
  maxPolarAngle: 1.48,
  minDistance: 0.04,
  maxDistance: 3.2,
  targetLimit: PRESENTATION_SCENE_HALF_EXTENT,
  sceneHalfExtent: PRESENTATION_SCENE_HALF_EXTENT,
} as const

export class FreeCamera {
  readonly camera = new PerspectiveCamera(54, 1, 0.001, 100)
  readonly controls: OrbitControls
  private readonly focusOffset = new Vector3()

  constructor(domElement: HTMLElement) {
    // Frame the population closely enough to be identifiable while retaining
    // enough room context for orbit/pan/zoom exploration.
    // Aim the opening view below the horizon so the room floor fills the
    // frame instead of exposing the scene background above its far edge.
    // Start just outside the street canyon and look down its floor. The
    // previous orbit point was inside a building volume in the supplied GLB,
    // which made the opening view look like a black wall with hidden habitats.
    this.camera.position.set(2.05, 1.32, 2.45)
    this.controls = new OrbitControls(this.camera, domElement)
    this.controls.target.set(0, 0.06, 0)
    this.controls.enableDamping = true
    // Orbit and zoom remain free, but panning could move the observer below
    // the floor or beyond the 6m presentation world.
    this.controls.enablePan = false
    this.controls.zoomToCursor = true
    this.controls.minDistance = FREE_CAMERA_LIMITS.minDistance
    this.controls.maxDistance = FREE_CAMERA_LIMITS.maxDistance
    this.controls.minPolarAngle = FREE_CAMERA_LIMITS.minPolarAngle
    this.controls.maxPolarAngle = FREE_CAMERA_LIMITS.maxPolarAngle
  }

  focusOn(position: Vector3) {
    // Preserve the current orbit direction and distance while moving the
    // orbit pivot, then move into an inspection distance. A real fly is only
    // millimetres long, so keeping the room-scale distance would make a
    // successful focus appear not to work.
    this.focusOffset.copy(this.camera.position).sub(this.controls.target)
    if (this.focusOffset.lengthSq() < this.controls.minDistance ** 2) {
      this.focusOffset.set(0.12, 0.06, 0.12)
    }
    this.focusOffset.setLength(Math.max(this.controls.minDistance * 5, Math.min(this.focusOffset.length(), 0.14)))
    this.controls.target.copy(position)
    this.camera.position.copy(position).add(this.focusOffset)
    this.controls.update()
  }

  frameBoundary(points: readonly Vector3[]) {
    if (points.length < 3) return
    const center = points.reduce((sum, point) => sum.add(point), new Vector3()).multiplyScalar(1 / points.length)
    const min = new Vector3(Infinity, 0, Infinity)
    const max = new Vector3(-Infinity, 0, -Infinity)
    points.forEach((point) => {
      min.x = Math.min(min.x, point.x)
      min.z = Math.min(min.z, point.z)
      max.x = Math.max(max.x, point.x)
      max.z = Math.max(max.z, point.z)
    })
    const radius = Math.max(0.12, Math.max(max.x - min.x, max.z - min.z) * 0.5)
    const distance = Math.max(this.controls.minDistance * 4, Math.min(this.controls.maxDistance * 0.82, radius / Math.tan((this.camera.fov * Math.PI / 180) / 2) * 1.35))
    const direction = this.camera.position.clone().sub(this.controls.target)
    if (direction.lengthSq() < 0.001) direction.set(0.7, 0.55, 0.7)
    direction.normalize().multiplyScalar(distance)
    this.controls.target.set(center.x, Math.max(FREE_CAMERA_LIMITS.floorY + 0.03, center.y + 0.02), center.z)
    this.camera.position.copy(this.controls.target).add(direction)
    this.camera.position.y = Math.max(FREE_CAMERA_LIMITS.floorY + 0.06, this.camera.position.y)
    this.controls.update()
  }

  update() {
    this.controls.target.x = clamp(this.controls.target.x, -FREE_CAMERA_LIMITS.targetLimit, FREE_CAMERA_LIMITS.targetLimit)
    this.controls.target.y = Math.max(FREE_CAMERA_LIMITS.floorY, this.controls.target.y)
    this.controls.target.z = clamp(this.controls.target.z, -FREE_CAMERA_LIMITS.targetLimit, FREE_CAMERA_LIMITS.targetLimit)
    this.controls.update()
    // OrbitControls can place the camera outside the authored 6m scene when
    // the user drags aggressively. Keep the actual eye point inside the same
    // box as the city; the next orbit update starts from this corrected pose.
    this.camera.position.x = clamp(this.camera.position.x, -FREE_CAMERA_LIMITS.sceneHalfExtent, FREE_CAMERA_LIMITS.sceneHalfExtent)
    this.camera.position.y = Math.max(FREE_CAMERA_LIMITS.floorY + 0.015, this.camera.position.y)
    this.camera.position.z = clamp(this.camera.position.z, -FREE_CAMERA_LIMITS.sceneHalfExtent, FREE_CAMERA_LIMITS.sceneHalfExtent)
  }
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, value))
}
