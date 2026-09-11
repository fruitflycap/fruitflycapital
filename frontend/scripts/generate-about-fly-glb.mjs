import { writeFile } from 'node:fs/promises'
import {
  BoxGeometry,
  CylinderGeometry,
  Group,
  Mesh,
  MeshStandardMaterial,
  PlaneGeometry,
  SphereGeometry,
  Vector3,
} from 'three'
import { GLTFExporter } from 'three/examples/jsm/exporters/GLTFExporter.js'

// GLTFExporter uses browser FileReader for the final binary blob. This small
// adapter lets the same exporter produce a compact static asset in Node.
globalThis.FileReader = class FileReader {
  readAsArrayBuffer(blob) {
    blob.arrayBuffer().then((result) => {
      this.result = result
      this.onloadend?.({ target: this })
    }).catch((error) => this.onerror?.(error))
  }
}

const bodyMaterial = new MeshStandardMaterial({ color: 0x252d32, roughness: 0.58, metalness: 0.08 })
const abdomenMaterial = new MeshStandardMaterial({ color: 0x6a3025, roughness: 0.64 })
const eyeMaterial = new MeshStandardMaterial({ color: 0xc40c20, roughness: 0.28, metalness: 0.1 })
const legMaterial = new MeshStandardMaterial({ color: 0x11171b, roughness: 0.72 })
const wingMaterial = new MeshStandardMaterial({ color: 0x75b7d4, transparent: true, opacity: 0.34, roughness: 0.18, depthWrite: false })

const root = new Group()
root.name = 'FruitFlyAboutPreview'

function add(mesh, name, position = [0, 0, 0], scale = [1, 1, 1]) {
  mesh.name = name
  mesh.position.set(...position)
  mesh.scale.set(...scale)
  root.add(mesh)
  return mesh
}

add(new Mesh(new SphereGeometry(0.43, 16, 10), bodyMaterial), 'thorax', [0, 0, 0], [1.35, 0.86, 0.9])
add(new Mesh(new SphereGeometry(0.38, 16, 10), abdomenMaterial), 'abdomen', [0.78, 0, 0], [1.65, 0.82, 0.78])
add(new Mesh(new SphereGeometry(0.31, 16, 10), bodyMaterial), 'head', [-0.58, 0.02, 0], [0.95, 0.9, 0.9])
add(new Mesh(new SphereGeometry(0.13, 12, 8), eyeMaterial), 'left-eye', [-0.72, 0.13, -0.23])
add(new Mesh(new SphereGeometry(0.13, 12, 8), eyeMaterial), 'right-eye', [-0.72, 0.13, 0.23])

for (const side of [-1, 1]) {
  const wing = add(new Mesh(new PlaneGeometry(1.55, 0.52), wingMaterial), `${side < 0 ? 'left' : 'right'}-wing`, [0.02, 0.27, side * 0.32], [1, 1, 1])
  wing.rotation.set(0.12 * side, 0.45 * side, 0.18 * side)
  wing.renderOrder = 2
  for (const legX of [-0.26, 0.05, 0.34]) {
    const leg = add(new Mesh(new CylinderGeometry(0.018, 0.012, 0.72, 7), legMaterial), `leg-${side}-${legX}`, [legX, -0.27, side * 0.18])
    leg.rotation.z = side * 0.82
    leg.rotation.x = side * 0.24
  }
  const antenna = add(new Mesh(new CylinderGeometry(0.012, 0.008, 0.48, 7), legMaterial), `antenna-${side}`, [-0.88, 0.29, side * 0.08])
  antenna.rotation.z = side * 0.52
}

const exporter = new GLTFExporter()
exporter.parse(root, async (result) => {
  await writeFile(new URL('../public/models/flybody/about-fly.glb', import.meta.url), Buffer.from(result))
  console.log('Generated lightweight about fly GLB')
}, (error) => {
  console.error(error)
  process.exitCode = 1
}, { binary: true })
