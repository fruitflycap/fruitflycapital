import {
  AdditiveBlending,
  DynamicDrawUsage,
  InstancedMesh,
  Matrix4,
  MeshBasicMaterial,
  SphereGeometry,
  Color,
} from 'three'
import type { TokenHabitat } from './TokenHabitat'

interface ParticleSeed {
  habitatIndex: number
  angle: number
  radius: number
  phase: number
  height: number
  kind: 'energy' | 'spark' | 'smoke'
}

/** One pooled InstancedMesh for all habitat particles. */
export class ParticleField {
  readonly mesh: InstancedMesh
  private readonly seeds: ParticleSeed[] = []
  private readonly matrix = new Matrix4()
  private readonly color = new Color()
  private activeCount = 0

  constructor(private readonly habitats: TokenHabitat[], capacityPerHabitat = 24, maxHabitats = 100) {
    const capacity = Math.max(1, Math.max(habitats.length, maxHabitats) * capacityPerHabitat)
    const geometry = new SphereGeometry(0.004, 4, 3)
    const material = new MeshBasicMaterial({
      color: 0xffffff,
      vertexColors: true,
      transparent: true,
      opacity: 0.7,
      depthWrite: false,
      blending: AdditiveBlending,
    })
    this.mesh = new InstancedMesh(geometry, material, capacity)
    this.mesh.name = 'PooledHabitatParticles'
    this.mesh.instanceMatrix.setUsage(DynamicDrawUsage)
    this.mesh.frustumCulled = false

    for (let index = 0; index < capacity; index += 1) {
      const habitatIndex = index % Math.max(1, maxHabitats)
      // Live mode starts empty. Avoid divide-by-zero/Infinity seeds before
      // the first market snapshot arrives.
      const ring = Math.floor(index / Math.max(1, maxHabitats))
      const kind = ring % 12 < 7 ? 'energy' : ring % 12 < 10 ? 'spark' : 'smoke'
      this.seeds.push({
        habitatIndex,
        angle: (ring * 2.399963 + habitatIndex * 1.7) % (Math.PI * 2),
        radius: 0.018 + ((ring * 17 + habitatIndex * 5) % 40) / 1000,
        phase: ((ring * 37 + habitatIndex * 11) % 100) / 100,
        height: 0.022 + ((ring * 13) % 70) / 1000,
        kind,
      })
      this.mesh.setColorAt(index, this.particleColor(kind, habitatIndex))
    }
    if (this.mesh.instanceColor) this.mesh.instanceColor.needsUpdate = true
  }

  get count() {
    return this.activeCount
  }

  update(timeSeconds: number) {
    this.activeCount = 0
    this.seeds.forEach((seed, index) => {
      const habitat = this.habitats[seed.habitatIndex]
      if (!habitat) return
      const properties = habitat.properties
      const activity = Math.max(properties.particleActivity, properties.visualMotionIntensity * 0.15)
      const enabled = habitat.isEnabled && (activity > 0.035 || properties.chaos > 0.035)
      if (!enabled) {
        this.matrix.makeScale(0, 0, 0)
        this.mesh.setMatrixAt(index, this.matrix)
        return
      }
      this.activeCount += 1

      const speed = 0.45 + activity * 1.8 + properties.chaos * 0.8
      const cycle = (timeSeconds * speed + seed.phase) % 1
      const angle = seed.angle + timeSeconds * (0.2 + properties.chaos * 1.7) + seed.phase
      const radial = seed.radius * (0.7 + cycle * 1.2)
      const vertical = seed.height + cycle * (0.05 + activity * 0.12)
      const scale = seed.kind === 'smoke'
        ? 0.75 + properties.chaos * 1.8
        : seed.kind === 'spark' ? 0.65 + activity * 1.5 : 0.45 + activity * 0.9
      this.matrix.makeScale(scale, scale, scale)
      this.matrix.setPosition(
        habitat.group.position.x + Math.cos(angle) * radial,
        vertical + (seed.kind === 'smoke' ? cycle * 0.03 : 0),
        habitat.group.position.z + Math.sin(angle) * radial,
      )
      this.mesh.setMatrixAt(index, this.matrix)
    })
    this.mesh.instanceMatrix.needsUpdate = true
  }

  private particleColor(kind: ParticleSeed['kind'], habitatIndex: number) {
    const palette = [0x62f0be, 0x86b8ff, 0xff7187, 0xf5c84c, 0xa980ff, 0xff9b5c, 0x56d9d0, 0xff80b8]
    if (kind === 'spark') return this.color.setHex(palette[habitatIndex % palette.length] ?? 0xffe8a1)
    if (kind === 'smoke') return this.color.setHex(0xaab8bd)
    return this.color.setHex(palette[habitatIndex % palette.length] ?? 0x62f0be)
  }
}
