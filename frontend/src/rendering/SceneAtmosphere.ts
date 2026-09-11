import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  DoubleSide,
  Group,
  Mesh,
  MeshBasicMaterial,
  Points,
  PointsMaterial,
  RingGeometry,
} from 'three'

interface Pulse {
  mesh: Mesh
  material: MeshBasicMaterial
  phase: number
}

/** Lightweight atmosphere effects that do not participate in world physics. */
export class SceneAtmosphere {
  readonly group = new Group()
  private readonly dust: Points
  private readonly dustPositions: Float32Array
  private readonly dustPhases: Float32Array
  private readonly dustBase: Array<[number, number, number]> = []
  private readonly pulses: Pulse[] = []

  constructor() {
    this.group.name = 'SceneAtmosphere'
    const mobile = window.matchMedia?.('(max-width: 600px)').matches ?? false
    const count = mobile ? 90 : 180
    this.dustPositions = new Float32Array(count * 3)
    this.dustPhases = new Float32Array(count)
    const colors = new Float32Array(count * 3)
    const palette = [0x71e8c0, 0x78b9ff, 0xffd27c]

    for (let index = 0; index < count; index += 1) {
      const angle = index * 2.399963 + (index % 5) * 0.14
      const radius = 0.35 + ((index * 37) % 270) / 100
      const x = Math.cos(angle) * radius
      const y = 0.12 + ((index * 19) % 105) / 100
      const z = Math.sin(angle) * radius
      this.dustBase.push([x, y, z])
      this.dustPhases[index] = (index * 0.618) % (Math.PI * 2)
      this.dustPositions[index * 3] = x
      this.dustPositions[index * 3 + 1] = y
      this.dustPositions[index * 3 + 2] = z
      const color = hexRgb(palette[index % palette.length]!)
      colors[index * 3] = color[0]
      colors[index * 3 + 1] = color[1]
      colors[index * 3 + 2] = color[2]
    }

    const geometry = new BufferGeometry()
    geometry.setAttribute('position', new BufferAttribute(this.dustPositions, 3))
    geometry.setAttribute('color', new BufferAttribute(colors, 3))
    const material = new PointsMaterial({
      size: mobile ? 0.012 : 0.016,
      vertexColors: true,
      transparent: true,
      opacity: 0.22,
      depthWrite: false,
      blending: AdditiveBlending,
      sizeAttenuation: true,
    })
    this.dust = new Points(geometry, material)
    this.dust.name = 'FloatingAtmosphericDust'
    this.dust.frustumCulled = false
    this.group.add(this.dust)

    const pulseSeeds = [
      [-1.75, -1.35, 0x4bd6a0],
      [1.55, 0.95, 0x78b9ff],
      [0.2, 1.7, 0xffb86b],
    ] as const
    pulseSeeds.forEach(([x, z, color], index) => {
      const pulseMaterial = new MeshBasicMaterial({
        color,
        transparent: true,
        opacity: 0.11,
        depthWrite: false,
        side: DoubleSide,
        blending: AdditiveBlending,
      })
      const pulse = new Mesh(new RingGeometry(0.24, 0.247, 48), pulseMaterial)
      pulse.name = `AtmospherePulse${index + 1}`
      pulse.rotation.x = -Math.PI / 2
      pulse.position.set(x, 0.038, z)
      this.group.add(pulse)
      this.pulses.push({ mesh: pulse, material: pulseMaterial, phase: index * 0.33 })
    })
  }

  update(timeSeconds: number) {
    this.dustBase.forEach(([x, y, z], index) => {
      const phase = this.dustPhases[index]!
      this.dustPositions[index * 3] = x + Math.sin(timeSeconds * 0.17 + phase) * 0.035
      this.dustPositions[index * 3 + 1] = y + Math.sin(timeSeconds * 0.24 + phase * 1.7) * 0.045
      this.dustPositions[index * 3 + 2] = z + Math.cos(timeSeconds * 0.14 + phase) * 0.035
    })
    ;(this.dust.geometry.getAttribute('position') as BufferAttribute).needsUpdate = true
    this.pulses.forEach(({ mesh, material, phase }) => {
      const cycle = (timeSeconds * 0.12 + phase) % 1
      const scale = 0.75 + cycle * 1.7
      mesh.scale.setScalar(scale)
      material.opacity = (1 - cycle) * 0.13
    })
  }
}

function hexRgb(value: number): [number, number, number] {
  return [((value >> 16) & 0xff) / 255, ((value >> 8) & 0xff) / 255, (value & 0xff) / 255]
}
