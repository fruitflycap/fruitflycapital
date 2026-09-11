import { BufferAttribute, BufferGeometry, Color, DynamicDrawUsage, LineBasicMaterial, LineSegments, Vector3 } from 'three'
import type { FlyAgent } from '../fly/FlyAgent'

const TRAIL_POINTS = 14

/** A single dynamic line buffer for every agent trail. */
export class FlyTrails {
  readonly mesh: LineSegments
  private readonly histories: Vector3[][]
  private readonly positions: Float32Array
  private readonly colors: Float32Array
  private readonly positionAttribute: BufferAttribute
  private readonly colorAttribute: BufferAttribute
  private elapsedSinceSample = 0

  constructor(agents: FlyAgent[]) {
    const vertexCount = agents.length * (TRAIL_POINTS - 1) * 2
    this.positions = new Float32Array(vertexCount * 3)
    this.colors = new Float32Array(vertexCount * 3)
    this.positionAttribute = new BufferAttribute(this.positions, 3)
    this.colorAttribute = new BufferAttribute(this.colors, 3)
    this.positionAttribute.setUsage(DynamicDrawUsage)
    this.colorAttribute.setUsage(DynamicDrawUsage)
    const geometry = new BufferGeometry()
    geometry.setAttribute('position', this.positionAttribute)
    geometry.setAttribute('color', this.colorAttribute)
    geometry.setDrawRange(0, 0)
    this.mesh = new LineSegments(geometry, new LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.34, depthWrite: false }))
    this.mesh.name = 'PooledFlyTrails'
    this.mesh.frustumCulled = false

    this.histories = agents.map((agent) => Array.from({ length: TRAIL_POINTS }, () => agent.body.position.clone()))
  }

  update(agents: FlyAgent[], selectedIndex: number, deltaSeconds: number) {
    this.elapsedSinceSample += deltaSeconds
    if (this.elapsedSinceSample >= 1 / 24) {
      this.elapsedSinceSample = 0
      agents.forEach((agent, agentIndex) => {
        const history = this.histories[agentIndex]
        if (!history) return
        history.shift()
        history.push(agent.body.position.clone())
      })
    }

    let offset = 0
    agents.forEach((_, agentIndex) => {
      const history = this.histories[agentIndex]
      if (!history) return
      const color = new Color(agentIndex === selectedIndex ? 0x80e7ff : 0x617d92)
      for (let pointIndex = 0; pointIndex < TRAIL_POINTS - 1; pointIndex += 1) {
        const from = history[pointIndex]!
        const to = history[pointIndex + 1]!
        this.positions[offset] = from.x
        this.positions[offset + 1] = from.y
        this.positions[offset + 2] = from.z
        this.positions[offset + 3] = to.x
        this.positions[offset + 4] = to.y
        this.positions[offset + 5] = to.z
        for (let vertex = 0; vertex < 2; vertex += 1) {
          this.colors[offset + vertex * 3] = color.r
          this.colors[offset + vertex * 3 + 1] = color.g
          this.colors[offset + vertex * 3 + 2] = color.b
        }
        offset += 6
      }
    })
    this.positionAttribute.needsUpdate = true
    this.colorAttribute.needsUpdate = true
    this.mesh.geometry.setDrawRange(0, offset / 3)
  }
}
