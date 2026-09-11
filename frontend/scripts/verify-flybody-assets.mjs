import { existsSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const assetRoot = resolve('public/models/flybody/fruitfly/assets')
const xmlPath = resolve(assetRoot, 'fruitfly.xml')

if (!existsSync(xmlPath)) {
  throw new Error(`Missing canonical Flybody XML: ${xmlPath}`)
}

const xml = readFileSync(xmlPath, 'utf8')
const meshFiles = [...xml.matchAll(/<mesh\b[^>]*\bfile="([^"]+)"/g)].map((match) => match[1])
const missing = [...new Set(meshFiles)].filter((file) => !existsSync(resolve(assetRoot, file)))

if (missing.length > 0) {
  throw new Error(`Canonical Flybody XML references missing mesh files: ${missing.join(', ')}`)
}

console.log(`Canonical Flybody assets verified: fruitfly.xml + ${new Set(meshFiles).size} referenced OBJ meshes`)
