import { Group, Mesh, MeshStandardMaterial, Object3D, PlaneGeometry, Quaternion, SphereGeometry, Vector3 } from 'three'
import { FlyAgent } from '../fly/FlyAgent'
import { WingBeatPatternGenerator } from '../fly/WingBeatPattern'
import { FlybodyAssetLoader } from './FlybodyAsset'
import type { ActuatorCommand } from '../networking/protocol'

export type FlyLod = 'full' | 'medium' | 'low'

// A real adult fly is only a few millimetres long, so it disappears at room
// scale from the free camera. This affects rendering only; physics, sensors,
// collisions, and logged positions remain in SI metres.
const DISPLAY_MAGNIFICATION = 12
const DISPLAY_GROUND_OFFSET = 0.012
const HOVER_ACTUATOR_NEUTRAL = 0.5

export class FlyRenderer {
  readonly group = new Group()
  readonly ready: Promise<void>
  private readonly leftWingFallback: Mesh
  private readonly rightWingFallback: Mesh
  private readonly bodyRoot: Group
  private readonly wingBeat = new WingBeatPatternGenerator()
  private canonicalLeftWing: Group | null = null
  private canonicalRightWing: Group | null = null
  private canonicalLeftBase = new Quaternion()
  private canonicalRightBase = new Quaternion()
  private readonly wingAxisX = new Vector3(1, 0, 0)
  private readonly wingAxisY = new Vector3(0, 1, 0)
  private readonly wingAxisZ = new Vector3(0, 0, 1)
  private readonly wingRotation = new Quaternion()
  private lastAssetError: string | null = null
  private loadedCanonical = false
  private canonicalMeshCount = 0
  private selected = false
  private lod: FlyLod = 'medium'

  constructor(wingPhase = 0) {
    this.group.name = 'FlyRenderer'
    this.wingBeat.reset(wingPhase)
    this.group.scale.setScalar(DISPLAY_MAGNIFICATION)
    this.bodyRoot = new Group()
    this.bodyRoot.name = 'FlybodyLoadingFallback'
    this.group.add(this.bodyRoot)
    this.leftWingFallback = this.createFallbackWing()
    this.rightWingFallback = this.createFallbackWing()
    this.bodyRoot.add(this.createFallbackBody(), this.leftWingFallback, this.rightWingFallback)
    // Show a lightweight silhouette immediately so motion/contact can be
    // inspected while the canonical XML/OBJ asset is loading. The status HUD
    // still identifies this as a loading fallback; it is never claimed to be
    // the canonical Flybody.
    this.bodyRoot.visible = true
    this.ready = this.loadCanonicalAsset()
  }

  get assetError() {
    return this.lastAssetError
  }

  get assetStatus() {
    return this.loadedCanonical ? 'canonical' : this.lastAssetError ? 'error' : 'loading'
  }

  get meshCount() {
    return this.canonicalMeshCount
  }

  get currentLod() {
    return this.selected ? 'full' : this.lod
  }

  setSelected(selected: boolean) {
    if (this.selected === selected) return
    this.selected = selected
    this.applyDisplayDetail()
  }

  setLod(lod: FlyLod) {
    if (this.lod === lod) return
    this.lod = lod
    this.applyDisplayDetail()
  }

  update(agent: FlyAgent, elapsedSeconds: number) {
    this.updatePose(agent.body.position, agent.body.quaternion, agent.actuators.get(), elapsedSeconds)
  }

  updatePose(position: Vector3, quaternion: Quaternion, command: ActuatorCommand, elapsedSeconds: number) {
    this.group.position.copy(position)
    this.group.position.y += DISPLAY_GROUND_OFFSET
    this.group.quaternion.copy(quaternion)
    // A neutral vertical command is hover/idle in the shared actuator
    // interface. Do not animate the canonical wings merely because that
    // neutral value is non-zero; wing motion must correspond to actual
    // forward or lift drive.
    const liftDrive = Math.abs(command.verticalThrust - HOVER_ACTUATOR_NEUTRAL) * 2
    const activity = Math.min(1, Math.max(0, command.forwardThrust + liftDrive))
    const angles = this.wingBeat.step(1 / 60, activity)
    if (this.canonicalLeftWing && this.canonicalRightWing) {
      this.canonicalLeftWing.quaternion.copy(this.canonicalLeftBase)
      this.canonicalRightWing.quaternion.copy(this.canonicalRightBase)
      this.applyWingAngles(this.canonicalLeftWing, angles.leftYaw, angles.leftRoll, angles.leftPitch)
      this.applyWingAngles(this.canonicalRightWing, angles.rightYaw, angles.rightRoll, angles.rightPitch)
    } else {
      const fallbackBeat = Math.sin(elapsedSeconds * (36 + activity * 18)) * (0.24 + activity * 0.32)
      this.leftWingFallback.rotation.z = 0.18 + fallbackBeat
      this.rightWingFallback.rotation.z = -0.18 - fallbackBeat
    }
  }

  private async loadCanonicalAsset() {
    try {
      const result = await new FlybodyAssetLoader().load()
      this.bodyRoot.clear()
      this.bodyRoot.name = 'FlybodyCanonicalAsset'
      this.bodyRoot.add(result.root)
      this.canonicalLeftWing = result.leftWing
      this.canonicalRightWing = result.rightWing
      this.canonicalMeshCount = result.meshCount
      this.applyDisplayDetail()
      this.bodyRoot.visible = true
      if (this.canonicalLeftWing) this.canonicalLeftBase.copy(this.canonicalLeftWing.quaternion)
      if (this.canonicalRightWing) this.canonicalRightBase.copy(this.canonicalRightWing.quaternion)
      this.loadedCanonical = true
    } catch (error) {
      this.lastAssetError = error instanceof Error ? error.message : String(error)
      // Keep the lightweight silhouette visible if the optional canonical
      // asset fails. Physics, sensors, and behavior remain fully active and
      // the status HUD reports the asset error.
      this.bodyRoot.visible = true
      console.error(`Flybody canonical asset unavailable: ${this.lastAssetError}`)
    }
  }

  private applyDisplayDetail() {
    if (!this.loadedCanonical && !this.bodyRoot.getObjectByName('FlybodyCanonicalAsset')) return
    this.bodyRoot.traverse((child) => {
      if (!(child instanceof Mesh)) return
      const geomName = canonicalGeomName(child)
      // The asset remains canonical for every agent. This is a render-only
      // LOD: unselected bodies keep the recognizable head/thorax/abdomen/
      // wing silhouette, while the selected body exposes all XML geoms for
      // inspection. It avoids rendering every XML geom for every population
      // member at room scale.
      child.visible = this.selected || this.lod === 'full'
        || (this.lod === 'medium' && isSwarmSilhouetteGeom(geomName))
        || (this.lod === 'low' && isLowDetailGeom(geomName))
    })
  }

  private applyWingAngles(wing: Group, yaw: number, roll: number, pitch: number) {
    // These axes and the order mirror the yaw/roll/pitch joint declarations
    // on wing_left and wing_right in the canonical XML.
    wing.quaternion.multiply(this.wingRotation.setFromAxisAngle(this.wingAxisZ, yaw))
    wing.quaternion.multiply(this.wingRotation.setFromAxisAngle(this.wingAxisX, roll))
    wing.quaternion.multiply(this.wingRotation.setFromAxisAngle(this.wingAxisY, pitch))
  }

  private createFallbackBody() {
    const body = new Group()
    const abdomen = new Mesh(new SphereGeometry(0.0018, 18, 12), new MeshStandardMaterial({ color: 0x111216, roughness: 0.62 }))
    abdomen.scale.set(0.8, 0.8, 1.9)
    abdomen.position.z = 0.0027
    abdomen.castShadow = true
    body.add(abdomen)
    const thorax = new Mesh(new SphereGeometry(0.0016, 16, 10), new MeshStandardMaterial({ color: 0x1b1c20, roughness: 0.58 }))
    thorax.scale.set(1.15, 1, 1.05)
    thorax.castShadow = true
    body.add(thorax)
    const head = new Mesh(new SphereGeometry(0.00125, 16, 10), new MeshStandardMaterial({ color: 0x17181c, roughness: 0.4 }))
    head.position.z = -0.0022
    head.castShadow = true
    body.add(head)
    const eyeMaterial = new MeshStandardMaterial({ color: 0x721d32, emissive: 0x25040b, emissiveIntensity: 0.5 })
    for (const x of [-0.0009, 0.0009]) {
      const eye = new Mesh(new SphereGeometry(0.00065, 12, 8), eyeMaterial)
      eye.position.set(x, 0.00045, -0.00255)
      body.add(eye)
    }
    return body
  }

  private createFallbackWing() {
    const wing = new Mesh(
      new PlaneGeometry(0.0075, 0.0022),
      new MeshStandardMaterial({ color: 0xaad7e8, transparent: true, opacity: 0.58, side: 2, roughness: 0.25 }),
    )
    wing.castShadow = true
    return wing
  }
}

function isSwarmSilhouetteGeom(name: string) {
  return /:geom:(thorax|thorax_black|head|head_red|head_ocelli|abdomen(?:_\d+)?|wing_left_(brown|membrane)|wing_right_(brown|membrane))$/.test(name)
}

function isLowDetailGeom(name: string) {
  if (!/:geom:(thorax|head|abdomen|wing_left|wing_right)/.test(name)) return false
  return !/(collision|fluid|inertial|abduct|twist|yaw|roll|pitch)/.test(name)
}

function canonicalGeomName(object: Object3D) {
  let current: Object3D | null = object
  while (current) {
    if (current.name.startsWith('flybody:geom:')) return current.name
    current = current.parent
  }
  return object.name
}
