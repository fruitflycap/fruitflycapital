import { cpSync, existsSync, mkdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

// Vercel does not reliably publish files reached through a repository
// symlink. Copy the canonical XML and the meshes it references into the
// frontend's own public tree during the build instead.
const sourceRoot = resolve('..', 'third_party', 'flybody', 'flybody', 'fruitfly', 'assets')
const destinationRoot = resolve('public', 'models', 'flybody', 'fruitfly', 'assets')
const xmlSource = resolve(sourceRoot, 'fruitfly.xml')

if (!existsSync(xmlSource)) throw new Error(`Missing canonical Flybody source: ${xmlSource}`)

mkdirSync(destinationRoot, { recursive: true })
const xml = readFileSync(xmlSource, 'utf8')
const meshFiles = [...xml.matchAll(/<mesh\b[^>]*\bfile="([^"]+)"/g)].map((match) => match[1])
cpSync(xmlSource, resolve(destinationRoot, 'fruitfly.xml'))

for (const file of [...new Set(meshFiles)]) {
  const source = resolve(sourceRoot, file)
  if (!existsSync(source)) throw new Error(`Canonical Flybody source mesh is missing: ${source}`)
  cpSync(source, resolve(destinationRoot, file))
}

console.log(`Prepared canonical Flybody assets for deployment: fruitfly.xml + ${new Set(meshFiles).size} OBJ meshes`)
