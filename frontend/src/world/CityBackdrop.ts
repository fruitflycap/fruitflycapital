import { Box3, Group, Mesh, MeshStandardMaterial, Vector3 } from 'three'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'

export interface CitySceneTuning {
  offsetX: number
  offsetY: number
  offsetZ: number
  rotationY: number
  scaleMultiplier: number
}

export const CITY_SCENE_TUNING: CitySceneTuning = {
  offsetX: 0,
  offsetY: -0.10,
  offsetZ: 0,
  rotationY: 0,
  scaleMultiplier: 1,
}

export const CITY_SCENE_LIMITS = {
  offsetX: [-1.5, 1.5] as const,
  offsetY: [-0.5, 0.5] as const,
  offsetZ: [-1.5, 1.5] as const,
  rotationY: [-Math.PI, Math.PI] as const,
  scaleMultiplier: [0.65, 1.25] as const,
}

const CITY_SCENE_STORAGE_KEY = 'ffc.citySceneTuning.v1'

function readSceneTuning(): CitySceneTuning {
  try {
    const saved = JSON.parse(window.localStorage.getItem(CITY_SCENE_STORAGE_KEY) ?? 'null') as Partial<CitySceneTuning> | null
    return clampTuning({ ...CITY_SCENE_TUNING, ...(saved ?? {}) })
  } catch {
    return { ...CITY_SCENE_TUNING }
  }
}

function clampTuning(tuning: CitySceneTuning): CitySceneTuning {
  return {
    offsetX: clamp(tuning.offsetX, ...CITY_SCENE_LIMITS.offsetX),
    offsetY: clamp(tuning.offsetY, ...CITY_SCENE_LIMITS.offsetY),
    offsetZ: clamp(tuning.offsetZ, ...CITY_SCENE_LIMITS.offsetZ),
    rotationY: clamp(tuning.rotationY, ...CITY_SCENE_LIMITS.rotationY),
    scaleMultiplier: clamp(tuning.scaleMultiplier, ...CITY_SCENE_LIMITS.scaleMultiplier),
  }
}

/** Loads and interactively positions the supplied street-city scene. */
export class CityBackdrop {
  readonly group = new Group()
  readonly ready: Promise<void>
  loaded = false
  private city: Group | null = null
  private fittedScale = 1
  private tuning: CitySceneTuning = readSceneTuning()

  constructor() {
    this.group.name = 'StreetCityBackdrop'
    this.ready = new Promise((resolve) => {
      new GLTFLoader().load('/models/city/street_city.glb', (gltf) => {
        this.city = gltf.scene
        const sourceBounds = new Box3().setFromObject(this.city)
        const sourceSize = sourceBounds.getSize(new Vector3())
        this.fittedScale = Math.min(
          sourceSize.x > 0 ? 5.65 / sourceSize.x : 1,
          sourceSize.z > 0 ? 5.65 / sourceSize.z : 1,
          sourceSize.y > 0 ? 4.2 / sourceSize.y : 1,
        )
        this.city.traverse((object) => {
          const mesh = object as Mesh
          if (!mesh.isMesh) return
          mesh.castShadow = false
          mesh.receiveShadow = true
          mesh.frustumCulled = true
          const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
          materials.forEach((material) => {
            const standard = material as MeshStandardMaterial
            standard.color?.multiplyScalar(0.96)
            if (standard.emissive) {
              standard.emissive.multiplyScalar(0.72)
              standard.emissiveIntensity = Math.min(1.05, Math.max(0.16, standard.emissiveIntensity || 0.16))
            }
          })
        })
        this.group.add(this.city)
        this.applyTuning()
        this.loaded = true
        resolve()
      }, undefined, (error) => {
        console.warn('Street city asset unavailable; using the bounded fallback floor', error)
        resolve()
      })
    })
  }

  getTuning(): CitySceneTuning {
    return { ...this.tuning }
  }

  setTuning(next: Partial<CitySceneTuning>) {
    this.tuning = clampTuning({ ...this.tuning, ...next })
    this.persistTuning()
    this.applyTuning()
    return this.getTuning()
  }

  resetTuning() {
    this.tuning = { ...CITY_SCENE_TUNING }
    this.persistTuning()
    this.applyTuning()
    return this.getTuning()
  }

  private applyTuning() {
    if (!this.city) return
    this.city.scale.setScalar(this.fittedScale * this.tuning.scaleMultiplier)
    this.city.rotation.set(0, this.tuning.rotationY, 0)
    this.city.position.set(0, 0, 0)
    this.city.updateMatrixWorld(true)
    const fittedBounds = new Box3().setFromObject(this.city)
    const center = fittedBounds.getCenter(new Vector3())
    this.city.position.x = -center.x + this.tuning.offsetX
    this.city.position.z = -center.z + this.tuning.offsetZ
    // Y is the height axis. This offset is relative to the normalized city
    // floor, so moving the GLB never changes fly physics coordinates.
    this.city.position.y = -fittedBounds.min.y + this.tuning.offsetY
    this.city.updateMatrixWorld(true)
  }

  private persistTuning() {
    try {
      window.localStorage.setItem(CITY_SCENE_STORAGE_KEY, JSON.stringify(this.tuning))
    } catch {
      // Storage-disabled environments can still use the controls this session.
    }
  }
}

function clamp(value: number, min: number, max: number) {
  return Math.max(min, Math.min(max, Number.isFinite(value) ? value : min))
}
