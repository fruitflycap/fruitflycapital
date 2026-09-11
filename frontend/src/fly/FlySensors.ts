import { Color, Material, Mesh, Object3D, Quaternion, Raycaster, Vector3 } from 'three'
import type {
  ContactObservation,
  EyeObservation,
  EyeSample,
  MotionObservation,
  OdorObservation,
  SensorFrame,
} from '../networking/protocol'
import { vectorToWire } from '../networking/protocol'
import { FlyBody } from './FlyBody'

// Low-resolution compound-eye sampling keeps the browser responsive while
// retaining separate left/right, azimuth, and elevation channels.
const EYE_AZIMUTH = [-0.85, -0.42, 0, 0.42, 0.85]
const EYE_ELEVATION = [-0.3, 0.3]
const WORLD_UP = new Vector3(0, 1, 0)
const AMBIENT_LUMINANCE = 0.12
const raycastTargetCache = new WeakMap<Object3D, { targets: Mesh[]; refreshedAt: number }>()

export class FlySensors {
  readonly forward = new Vector3(0, 0, -1)
  readonly up = new Vector3(0, 1, 0)
  readonly velocity = new Vector3()
  readonly leftEye: EyeObservation = emptyEye()
  readonly rightEye: EyeObservation = emptyEye()
  readonly odor: OdorObservation = { concentration: 0, leftAntenna: 0, rightAntenna: 0, aversiveConcentration: 0, temporalChange: 0, airflowImplemented: false }
  readonly motion: MotionObservation = {
    angularVelocity: vectorToWire(new Vector3()),
    bodyVelocity: vectorToWire(new Vector3()),
    translationalSpeed: 0,
    gravityAlignment: 1,
    windDirection: null,
    windSpeed: 0,
    windImplemented: false,
  }
  readonly contact: ContactObservation = { ground: false, obstacle: false, wall: false }
  private readonly raycaster = new Raycaster()
  private raycastTargets: Mesh[] = []
  private readonly inverseQuaternion = new Quaternion()
  private readonly localDirection = new Vector3()
  private readonly worldDirection = new Vector3()
  private readonly tangentVelocity = new Vector3()
  private readonly eyeOrigin = new Vector3()
  private readonly antennaOrigin = new Vector3()
  private lastRaycastRoot: Object3D | null = null
  private lastRaycastRefresh = Number.NEGATIVE_INFINITY
  private previousOdor = 0
  private currentTimeSeconds = 0

  update(body: FlyBody, visualRoot: Object3D, odorSampler: OdorSampler, timeSeconds: number) {
    this.currentTimeSeconds = timeSeconds
    this.forward.set(0, 0, -1).applyQuaternion(body.quaternion).normalize()
    this.up.set(0, 1, 0).applyQuaternion(body.quaternion).normalize()
    this.velocity.copy(body.velocity)
    this.inverseQuaternion.copy(body.quaternion).invert()
    this.collectRaycastTargets(visualRoot, timeSeconds)
    this.leftEye.samples = this.sampleEye(body, -1)
    this.rightEye.samples = this.sampleEye(body, 1)
    updateEyeSummary(this.leftEye)
    updateEyeSummary(this.rightEye)
    this.updateOdor(body, odorSampler)
    this.updateMotion(body)
    this.contact.ground = body.contact.ground
    this.contact.obstacle = body.contact.obstacle
    this.contact.wall = body.contact.wall
  }

  toFrame(_body: FlyBody): SensorFrame {
    return {
      leftEye: cloneEye(this.leftEye),
      rightEye: cloneEye(this.rightEye),
      odor: { ...this.odor },
      motion: {
        ...this.motion,
        angularVelocity: { ...this.motion.angularVelocity },
        bodyVelocity: { ...this.motion.bodyVelocity },
      },
      contact: { ...this.contact },
      timestampMs: performance.now(),
    }
  }

  getObstacleDistance() {
    const samples = [...this.leftEye.samples, ...this.rightEye.samples]
    const nearestAngularSize = Math.max(...samples.map((sample) => sample.objectAngularSizeRad))
    return nearestAngularSize > 0 ? 1 / nearestAngularSize : 1
  }

  getOdorLevel() {
    return this.odor.concentration
  }

  getFrame() {
    return { leftEye: this.leftEye, rightEye: this.rightEye, odor: this.odor, motion: this.motion, contact: this.contact }
  }

  private sampleEye(body: FlyBody, side: -1 | 1): EyeSample[] {
    const samples: EyeSample[] = []
    for (const elevation of EYE_ELEVATION) {
      for (const azimuthOffset of EYE_AZIMUTH) {
        const azimuth = azimuthOffset + side * 0.2
        this.localDirection.set(
          Math.sin(azimuth) * Math.cos(elevation),
          Math.sin(elevation),
          -Math.cos(azimuth) * Math.cos(elevation),
        )
        this.worldDirection.copy(this.localDirection).applyQuaternion(body.quaternion).normalize()
        this.eyeOrigin.set(side * 0.0011, 0.00035, -0.0011).applyQuaternion(body.quaternion).add(body.position)
        this.raycaster.set(this.eyeOrigin, this.worldDirection)
        // Habitat labels are THREE.Sprite objects. They are observer-facing
        // UI, not visual geometry available to the fly. Excluding them also
        // avoids Three.js requiring an observer camera for Sprite.raycast().
        const hit = this.raycaster.intersectObjects(this.raycastTargets, false)[0]
        const distance = hit?.distance ?? 1
        const luminance = hit ? materialLuminance(hit.object) : AMBIENT_LUMINANCE
        const contrast = Math.min(1, Math.abs(luminance - AMBIENT_LUMINANCE) / Math.max(AMBIENT_LUMINANCE, 1 - AMBIENT_LUMINANCE))
        this.tangentVelocity.copy(this.velocity).addScaledVector(this.worldDirection, -this.velocity.dot(this.worldDirection))
        const translationalFlow = this.tangentVelocity.length() / Math.max(distance, 0.01)
        const rotationalFlow = body.angularVelocity.length() * 0.025
        const opticFlow = Math.min(1, (translationalFlow + rotationalFlow) * 0.04)
        const objectAngularSizeRad = hit ? Math.atan2(estimateObjectRadius(hit.object), Math.max(distance, 0.001)) : 0
        samples.push({
          direction: vectorToWire(this.localDirection),
          azimuthRad: azimuth,
          elevationRad: elevation,
          luminance,
          contrast,
          opticFlow,
          objectAngularSizeRad,
        })
      }
    }
    return samples
  }

  private collectRaycastTargets(visualRoot: Object3D, timeSeconds: number) {
    if (visualRoot === this.lastRaycastRoot && timeSeconds - this.lastRaycastRefresh < 1) return
    const cached = raycastTargetCache.get(visualRoot)
    if (cached && timeSeconds - cached.refreshedAt < 1) {
      this.raycastTargets = cached.targets
      this.lastRaycastRoot = visualRoot
      this.lastRaycastRefresh = cached.refreshedAt
      return
    }
    this.lastRaycastRoot = visualRoot
    this.lastRaycastRefresh = timeSeconds
    const targets: Mesh[] = []
    visualRoot.traverse((object) => {
      if (object instanceof Mesh && object.userData.sensorVisible !== false) targets.push(object)
    })
    this.raycastTargets = targets
    raycastTargetCache.set(visualRoot, { targets, refreshedAt: timeSeconds })
  }

  private updateOdor(body: FlyBody, odorSampler: OdorSampler) {
    const center = odorSampler(body.position, this.currentTimeSeconds)
    // A slightly wider virtual antenna baseline makes the odor gradient
    // numerically observable at this metre-scale demo resolution.
    // Use a visible metre-scale baseline so the bilateral signal remains
    // useful while the fly is still several body-lengths from a habitat.
    this.antennaOrigin.set(-0.012, 0.0004, -0.0012).applyQuaternion(body.quaternion).add(body.position)
    const left = odorSampler(this.antennaOrigin, this.currentTimeSeconds + 0.013)
    this.antennaOrigin.set(0.012, 0.0004, -0.0012).applyQuaternion(body.quaternion).add(body.position)
    const right = odorSampler(this.antennaOrigin, this.currentTimeSeconds + 0.027)
    this.odor.concentration = center.attractive
    this.odor.leftAntenna = left.attractive
    this.odor.rightAntenna = right.attractive
    this.odor.aversiveConcentration = center.aversive
    this.odor.temporalChange = center.attractive - this.previousOdor
    this.previousOdor = center.attractive
  }

  private updateMotion(body: FlyBody) {
    const bodyVelocity = body.velocity.clone().applyQuaternion(this.inverseQuaternion)
    this.motion.angularVelocity = vectorToWire(body.angularVelocity)
    this.motion.bodyVelocity = vectorToWire(bodyVelocity)
    this.motion.translationalSpeed = body.velocity.length()
    this.motion.gravityAlignment = this.up.dot(WORLD_UP)
  }
}

function emptyEye(): EyeObservation {
  return { samples: [], meanLuminance: 0, meanContrast: 0, meanOpticFlow: 0 }
}

function cloneEye(eye: EyeObservation): EyeObservation {
  return {
    samples: eye.samples.map((sample) => ({ ...sample, direction: { ...sample.direction } })),
    meanLuminance: eye.meanLuminance,
    meanContrast: eye.meanContrast,
    meanOpticFlow: eye.meanOpticFlow,
  }
}

function updateEyeSummary(eye: EyeObservation) {
  if (eye.samples.length === 0) return
  eye.meanLuminance = mean(eye.samples.map((sample) => sample.luminance))
  eye.meanContrast = mean(eye.samples.map((sample) => sample.contrast))
  eye.meanOpticFlow = mean(eye.samples.map((sample) => sample.opticFlow))
}

function mean(values: number[]) {
  return values.reduce((sum, value) => sum + value, 0) / Math.max(values.length, 1)
}

function materialLuminance(object: Object3D) {
  const mesh = object as Mesh
  const material = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material
  const color = material instanceof Material && 'color' in material ? (material as Material & { color: Color }).color : new Color(0.15, 0.15, 0.15)
  return Math.min(1, 0.2126 * color.r + 0.7152 * color.g + 0.0722 * color.b)
}

function estimateObjectRadius(object: Object3D) {
  const mesh = object as Mesh
  const geometry = mesh.geometry
  if (geometry?.boundingSphere) return Math.max(0.002, geometry.boundingSphere.radius * Math.max(mesh.scale.x, mesh.scale.y, mesh.scale.z))
  return 0.02
}

export interface OdorFieldSample {
  attractive: number
  aversive: number
}

export type OdorSampler = (position: Vector3, timeSeconds: number) => OdorFieldSample
