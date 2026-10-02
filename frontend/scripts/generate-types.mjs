import { readFile, mkdir, writeFile } from 'node:fs/promises'
import openapiTS, { astToString } from 'openapi-typescript'

const schema = new URL('../../schemas/openapi.json', import.meta.url)
const target = new URL('../src/api/generated/schema.ts', import.meta.url)
const ast = await openapiTS(JSON.parse(await readFile(schema, 'utf8')))
const content = '// Generated from schemas/openapi.json. Run npm run types to update.\n' + astToString(ast)

if (process.argv.includes('--check')) {
  if (await readFile(target, 'utf8') !== content) {
    throw new Error('Frontend types are stale; run npm run types')
  }
} else {
  await mkdir(new URL('.', target), { recursive: true })
  await writeFile(target, content)
}
