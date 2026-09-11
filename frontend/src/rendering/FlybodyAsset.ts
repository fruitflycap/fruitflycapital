import {
  DoubleSide,
  Group,
  Mesh,
  MeshStandardMaterial,
  Object3D,
  Quaternion,
} from 'three'
import { OBJLoader } from 'three/examples/jsm/loaders/OBJLoader.js'

export interface FlybodyAssetResult {
  root: Group
  leftWing: Group | null
  rightWing: Group | null
  meshCount: number
}

interface MeshDefinition {
  file: string
}

const ASSET_BASE = '/models/flybody/fruitfly/assets/'
const MUJOCO_MESH_SCALE = 0.1
// Flybody's XML uses centimetres (gravity is 981 cm/s^2); the browser world
// uses SI metres. Keep this conversion explicit rather than hiding it in the
// renderer's object scale.
const CENTIMETRES_TO_METRES = 0.01

const MATERIALS: Record<string, { color: number; opacity: number; transparent: boolean; roughness: number }> = {
  // Near-black charcoal keeps the canonical Flybody geometry and material
  // separation readable under the bright world lighting. The eyes and wings
  // remain distinct so the fly does not collapse into a flat silhouette.
  body: { color: 0x17181b, opacity: 1, transparent: false, roughness: 0.62 },
  red: { color: 0xcc0701, opacity: 1, transparent: false, roughness: 0.55 },
  ocelli: { color: 0x050608, opacity: 1, transparent: false, roughness: 0.3 },
  black: { color: 0x050505, opacity: 1, transparent: false, roughness: 0.48 },
  'bristle-brown': { color: 0x0b0b0d, opacity: 1, transparent: false, roughness: 0.5 },
  lower: { color: 0x28282d, opacity: 1, transparent: false, roughness: 0.6 },
  brown: { color: 0x0d0f12, opacity: 1, transparent: false, roughness: 0.6 },
  membrane: { color: 0x89afd0, opacity: 0.4, transparent: true, roughness: 0.25 },
  blue: { color: 0x334cff, opacity: 1, transparent: false, roughness: 0.55 },
  pink: { color: 0x994dcc, opacity: 1, transparent: false, roughness: 0.55 },
}

export class FlybodyAssetLoader {
  private readonly objLoader = new OBJLoader()
  private static readonly meshCache = new Map<string, Promise<Group>>()
  private static templatePromise: Promise<FlybodyAssetResult> | null = null

  async load(): Promise<FlybodyAssetResult> {
    // Both flies use the same canonical geometry. Parse the expensive XML/OBJ
    // template once, then deep-clone its scene graph while sharing immutable
    // BufferGeometry and materials between agents.
    const template = FlybodyAssetLoader.templatePromise ?? (FlybodyAssetLoader.templatePromise = this.loadTemplate())
    return cloneAsset(await template)
  }

  private async loadTemplate(): Promise<FlybodyAssetResult> {
    const xmlText = await fetch(`${ASSET_BASE}fruitfly.xml`).then(async (response) => {
      if (!response.ok) throw new Error(`Flybody XML request failed (${response.status})`)
      return response.text()
    })
    const document = new DOMParser().parseFromString(xmlText, 'application/xml')
    if (document.querySelector('parsererror')) throw new Error('Flybody XML could not be parsed')

    const meshDefinitions = this.readMeshDefinitions(document)
    const worldbody = document.querySelector('worldbody')
    if (!worldbody) throw new Error('Flybody XML has no worldbody')

    const root = new Group()
    root.name = 'FlybodyCanonicalAsset'
    // MuJoCo is Z-up. Three.js is Y-up; this is the same coordinate mapping
    // used by the rest of this project for world-space vectors. Flybody's
    // anatomical head direction is MuJoCo +X, while FlyBody's flight
    // direction is Three.js -Z. The rotation values alone are not enough:
    // Three's default XYZ Euler order maps +X to -Y here. YXZ applies the
    // intended conversion (+X -> -Z, +Z/up -> +Y) so the rendered head,
    // forward arrow, and velocity agree.
    root.rotation.order = 'YXZ'
    root.rotation.set(-Math.PI / 2, Math.PI / 2, 0)
    const state: { leftWing: Group | null; rightWing: Group | null; meshCount: number } = {
      leftWing: null,
      rightWing: null,
      meshCount: 0,
    }
    const bodies = Array.from(worldbody.children).filter((child) => child.tagName === 'body')
    await Promise.all(bodies.map(async (body) => root.add(await this.buildBody(body, meshDefinitions, state))))
    return { root, ...state }
  }

  private readMeshDefinitions(document: Document) {
    const definitions = new Map<string, MeshDefinition>()
    for (const element of Array.from(document.querySelectorAll('asset > mesh[name][file]'))) {
      const name = element.getAttribute('name')
      const file = element.getAttribute('file')
      if (name && file) definitions.set(name, { file })
    }
    return definitions
  }

  private async buildBody(
    element: Element,
    meshDefinitions: Map<string, MeshDefinition>,
    state: { leftWing: Group | null; rightWing: Group | null; meshCount: number },
  ) {
    const body = new Group()
    const name = element.getAttribute('name') ?? 'unnamed-body'
    body.name = `flybody:${name}`
    this.applyTransform(body, element)
    if (name === 'wing_left') state.leftWing = body
    if (name === 'wing_right') state.rightWing = body

    const geoms = Array.from(element.children).filter((child) => child.tagName === 'geom')
    await Promise.all(geoms.map(async (geom) => {
      const meshName = geom.getAttribute('mesh')
      if (!meshName) return
      const definition = meshDefinitions.get(meshName)
      if (!definition) throw new Error(`Flybody XML references missing mesh ${meshName}`)
      const visual = (await this.loadMesh(definition.file)).clone(true)
      const geomNode = new Group()
      geomNode.name = `flybody:geom:${geom.getAttribute('name') ?? meshName}`
      this.applyTransform(geomNode, geom)
      geomNode.scale.setScalar(MUJOCO_MESH_SCALE * CENTIMETRES_TO_METRES)
      this.applyMaterial(visual, geom.getAttribute('material') ?? 'body')
      visual.traverse((child) => {
        if (child instanceof Mesh) {
          // Fly bodies are physical agents, not world landmarks. Keeping
          // them out of the environment ray list prevents the population from
          // ray-testing against thousands of their own detail meshes.
          child.userData.sensorVisible = false
          child.castShadow = false
          child.receiveShadow = true
        }
      })
      geomNode.add(visual)
      body.add(geomNode)
      state.meshCount += 1
    }))

    const children = Array.from(element.children).filter((child) => child.tagName === 'body')
    await Promise.all(children.map(async (child) => body.add(await this.buildBody(child, meshDefinitions, state))))
    return body
  }

  private loadMesh(file: string) {
    const cached = FlybodyAssetLoader.meshCache.get(file)
    if (cached) return cached
    const request = this.objLoader.loadAsync(`${ASSET_BASE}${file}`)
    FlybodyAssetLoader.meshCache.set(file, request)
    return request
  }

  private applyTransform(target: Object3D, element: Element) {
    const pos = this.parseNumbers(element.getAttribute('pos'))
    if (pos.length === 3) target.position.set(pos[0] ?? 0, pos[1] ?? 0, pos[2] ?? 0)
    const quat = this.parseNumbers(element.getAttribute('quat'))
    if (quat.length === 4) {
      // MuJoCo stores quaternions as w x y z; Three.js expects x y z w.
      target.quaternion.copy(new Quaternion(quat[1] ?? 0, quat[2] ?? 0, quat[3] ?? 0, quat[0] ?? 1))
    }
    const euler = this.parseNumbers(element.getAttribute('euler'))
    // The XML declares angle="radian" at the compiler level.
    if (euler.length === 3 && quat.length !== 4) target.rotation.set(
      euler[0] ?? 0,
      euler[1] ?? 0,
      euler[2] ?? 0,
    )
    target.position.multiplyScalar(CENTIMETRES_TO_METRES)
  }

  private applyMaterial(object: Object3D, materialName: string) {
    const definition = MATERIALS[materialName] ?? {
      color: 0x17181b,
      opacity: 1,
      transparent: false,
      roughness: 0.62,
    }
    object.traverse((child) => {
      if (!(child instanceof Mesh)) return
      child.material = new MeshStandardMaterial({
        color: definition.color,
        roughness: definition.roughness,
        transparent: definition.transparent,
        opacity: definition.opacity,
        depthWrite: materialName !== 'membrane',
        ...(materialName === 'membrane' ? { side: DoubleSide } : {}),
      })
      // The fly is small and moves continuously. Receiving scene light is
      // useful for inspection; including every body mesh in the shadow pass is
      // disproportionately expensive at interactive frame rates.
      child.castShadow = false
      child.receiveShadow = true
    })
  }

  private parseNumbers(value: string | null) {
    if (!value) return []
    return value.trim().split(/\s+/).map(Number).filter(Number.isFinite)
  }
}

function cloneAsset(template: FlybodyAssetResult): FlybodyAssetResult {
  const root = template.root.clone(true) as Group
  return {
    root,
    leftWing: (root.getObjectByName('flybody:wing_left') as Group | undefined) ?? null,
    rightWing: (root.getObjectByName('flybody:wing_right') as Group | undefined) ?? null,
    meshCount: template.meshCount,
  }
}
