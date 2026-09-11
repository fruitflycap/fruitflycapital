import { BufferGeometry, CanvasTexture, DoubleSide, Group, LineBasicMaterial, LineLoop, Mesh, MeshBasicMaterial, MeshStandardMaterial, RepeatWrapping, Shape, ShapeGeometry, SRGBColorSpace, Vector3 } from 'three'
import type { WorldBounds } from '../fly/FlyBody'

const FLOOR_Y = 0
export const PRESENTATION_SCENE_HALF_EXTENT = 3

export const ARENA_BOUNDS: WorldBounds = {
  // The authored city and the manual game-scene editor both use the full
  // presentation floor. Keep the simulation and visible map in the same
  // coordinate system so a drawn region is actually reachable by flies.
  min: new Vector3(-PRESENTATION_SCENE_HALF_EXTENT, 0, -PRESENTATION_SCENE_HALF_EXTENT),
  max: new Vector3(PRESENTATION_SCENE_HALF_EXTENT, 1, PRESENTATION_SCENE_HALF_EXTENT),
}

// This is the complete play surface: the star field is the background and the
// floor, habitats, and flies are the only world geometry.
export class Arena {
  readonly group = new Group()
  readonly bounds = ARENA_BOUNDS

  constructor() {
    this.group.name = 'Arena'
    const floorTexture = createFloorTexture()
    const floor = new Mesh(
      // The floor covers the same 6m x 6m presentation volume as the default
      // physics bounds, so the manual game-scene editor has no hidden area.
      new ShapeGeometry(roundedRectangle(6.2, 6.2, 0.44)),
      new MeshStandardMaterial({ color: 0x65776f, map: floorTexture, roughness: 0.78, metalness: 0.14 }),
    )
    floor.rotation.x = -Math.PI / 2
    // Keep the visual floor exactly on the same Y plane used by habitats and
    // body ground contact.
    floor.position.y = FLOOR_Y
    floor.name = 'StreetFloor'
    this.group.add(floor)

    // A rounded rim makes the playable surface read as one plate instead of
    // four unrelated wall bars. The authoritative collision boundary remains
    // ARENA_BOUNDS in FlyBody, so this never depends on mesh collision accuracy.
    const rimShape = roundedRectangle(6.34, 6.34, 0.56)
    rimShape.holes.push(roundedRectangle(6.08, 6.08, 0.42, true))
    const rim = new Mesh(
      new ShapeGeometry(rimShape),
      new MeshStandardMaterial({ color: 0x526761, roughness: 0.66, metalness: 0.24, side: DoubleSide }),
    )
    rim.rotation.x = -Math.PI / 2
    rim.position.y = 0.012
    rim.name = 'RoundedArenaRim'
    this.group.add(rim)

    // Gold is used as a shallow “sea” around the plate: visible in the camera
    // view, but transparent enough that it does not compete with habitats.
    const goldSeaShape = roundedRectangle(6.29, 6.29, 0.53)
    goldSeaShape.holes.push(roundedRectangle(6.13, 6.13, 0.45, true))
    const goldSea = new Mesh(
      new ShapeGeometry(goldSeaShape),
      new MeshBasicMaterial({ color: 0xffd166, transparent: true, opacity: 0.2, side: DoubleSide, depthWrite: false }),
    )
    goldSea.rotation.x = -Math.PI / 2
    goldSea.position.y = 0.027
    goldSea.name = 'GoldArenaSea'
    this.group.add(goldSea)

    const borderPoints = roundedRectanglePoints(6.29, 6.29, 0.53).map(([x, z]) => new Vector3(x, 0.034, z))
    const borderLine = new LineLoop(
      new BufferGeometry().setFromPoints(borderPoints),
      new LineBasicMaterial({ color: 0xffe09a, transparent: true, opacity: 0.72 }),
    )
    borderLine.name = 'GoldArenaBorder'
    this.group.add(borderLine)
  }

  /** Kept for compatibility with older callers; the floor is always visible. */
  setFallbackFloorVisible(visible: boolean) {
    const floor = this.group.getObjectByName('StreetFloor')
    if (floor) floor.visible = visible
  }

}

function roundedRectangle(width: number, height: number, radius: number, clockwise = false) {
  const shape = new Shape()
  const points = roundedRectanglePoints(width, height, radius)
  if (clockwise) points.reverse()
  const [firstX, firstZ] = points[0]!
  shape.moveTo(firstX, firstZ)
  for (const [x, z] of points.slice(1)) shape.lineTo(x, z)
  shape.lineTo(firstX, firstZ)
  return shape
}

function roundedRectanglePoints(width: number, height: number, radius: number) {
  const halfWidth = width / 2
  const halfHeight = height / 2
  const clampedRadius = Math.min(radius, halfWidth, halfHeight)
  const corners = [
    [halfWidth - clampedRadius, -halfHeight + clampedRadius, -Math.PI / 2, 0],
    [halfWidth - clampedRadius, halfHeight - clampedRadius, 0, Math.PI / 2],
    [-halfWidth + clampedRadius, halfHeight - clampedRadius, Math.PI / 2, Math.PI],
    [-halfWidth + clampedRadius, -halfHeight + clampedRadius, Math.PI, Math.PI * 1.5],
  ] as const
  const points: Array<[number, number]> = []
  const cornerSegments = 10
  for (const [centerX, centerZ, startAngle, endAngle] of corners) {
    for (let segment = 0; segment < cornerSegments; segment += 1) {
      const angle = startAngle + (endAngle - startAngle) * (segment / cornerSegments)
      points.push([centerX + Math.cos(angle) * clampedRadius, centerZ + Math.sin(angle) * clampedRadius])
    }
  }
  return points
}

function createFloorTexture() {
  const canvas = document.createElement('canvas')
  canvas.width = 128
  canvas.height = 128
  const context = canvas.getContext('2d')
  if (!context) return undefined
  const image = context.createImageData(canvas.width, canvas.height)
  let seed = 0x5eed
  for (let index = 0; index < image.data.length; index += 4) {
    seed = (seed * 1664525 + 1013904223) >>> 0
    const noise = 82 + Math.floor(((seed >>> 8) & 0xffff) / 65536 * 26)
    image.data[index] = noise
    image.data[index + 1] = noise + 13
    image.data[index + 2] = noise + 11
    image.data[index + 3] = 255
  }
  context.putImageData(image, 0, 0)
  // Subtle wet-road seams and oil patches give the plain floor depth without
  // reintroducing buildings, props, or another competing play surface.
  context.lineWidth = 1
  context.strokeStyle = 'rgba(133, 218, 202, 0.12)'
  for (let position = 16; position < 128; position += 32) {
    context.beginPath()
    context.moveTo(position, 0)
    context.lineTo(position + 7, 128)
    context.stroke()
  }
  for (let index = 0; index < 14; index += 1) {
    seed = (seed * 1664525 + 1013904223) >>> 0
    const x = ((seed >>> 8) & 0xffff) / 65536 * 128
    seed = (seed * 1664525 + 1013904223) >>> 0
    const y = ((seed >>> 8) & 0xffff) / 65536 * 128
    const radius = 4 + ((seed >>> 16) & 0xff) / 255 * 13
    const patch = context.createRadialGradient(x, y, 0, x, y, radius)
    patch.addColorStop(0, 'rgba(8, 20, 23, 0.28)')
    patch.addColorStop(0.72, 'rgba(8, 20, 23, 0.08)')
    patch.addColorStop(1, 'rgba(8, 20, 23, 0)')
    context.fillStyle = patch
    context.beginPath()
    context.ellipse(x, y, radius * 1.4, radius * 0.62, 0.2, 0, Math.PI * 2)
    context.fill()
  }
  const texture = new CanvasTexture(canvas)
  texture.colorSpace = SRGBColorSpace
  texture.wrapS = RepeatWrapping
  texture.wrapT = RepeatWrapping
  texture.repeat.set(9, 9)
  return texture
}
