import { connect } from './db.js'
import { createApp } from './app.js'
import { firebaseAuth } from './firebase.js'

const secret = process.env.INTERNAL_SECRET
if (!secret || secret.length < 32) throw new Error('Set an INTERNAL_SECRET of at least 32 random characters.')
const auth = firebaseAuth()
const aiUrl = process.env.AI_URL || 'http://127.0.0.1:8000'
const unavailable = () => Object.assign(new Error('AI service unavailable. Check the FastAPI process and configuration.'), { status: 503 })
async function getPdf(versionId) {
  try {
    const response = await fetch(new URL('/internal/pdf/' + versionId, aiUrl), {
      headers: { 'x-internal-secret': secret }, signal: AbortSignal.timeout(30_000), redirect: 'error'
    })
    if (response.status === 404) return null
    if (!response.ok) throw new Error()
    return response
  } catch {
    throw unavailable()
  }
}
async function ai(path, payload) {
  try {
    const response = await fetch(new URL(path, aiUrl), {
      method: payload ? 'POST' : 'GET',
      headers: { 'content-type': 'application/json', 'x-internal-secret': secret },
      body: payload ? JSON.stringify(payload) : undefined,
      signal: AbortSignal.timeout(90_000), redirect: 'error'
    })
    if (!response.ok) throw new Error('Internal service error')
    return await response.json()
  } catch {
    throw unavailable()
  }
}
const { db } = await connect()
const host = process.env.HOST || '127.0.0.1'
const port = Number(process.env.PORT || 4000)
createApp({ db, verify: token => auth.verifyIdToken(token, true), ai, getPdf,
  origin: process.env.WEB_ORIGIN || 'http://localhost:5173',
  sharepointHost: process.env.SPPU_SHAREPOINT_HOST?.toLowerCase()
}).listen(port, host, () => console.log('CampusIQ API listening on', host, port))
