
import { connect } from '../backend/src/db.js'
import { createApp } from '../backend/src/app.js'
import express from '../backend/node_modules/express/index.js'

process.env.MONGO_URI = process.env.CAMPUSIQ_TEST_MONGO || 'mongodb://127.0.0.1:27018'
process.env.MONGO_DB = 'campusiq_browser_' + crypto.randomUUID().replaceAll('-', '')
const { db, client } = await connect()
await db.collection('users').insertOne({ _id: 'fixture-admin', role: 'admin', profile: {}, createdAt: new Date() })
const app = express()
const server = app.listen(4012, '127.0.0.1')
app.post('/fixture-shutdown', async (_req, res) => {
  await db.dropDatabase()
  await client.close()
  res.json({ ok: true })
  server.close()
})
app.use(createApp({ db, origin: 'http://localhost:5187', ai: async () => ({ mongo: true, worker: true, qdrant: true }),
  verify: async token => {
    const parts = token.split('.')
    if (parts[2] !== 'fixture') throw Object.assign(new Error(), { code: 'auth/invalid-id-token' })
    const { sub, email } = JSON.parse(Buffer.from(parts[1], 'base64url').toString())
    if (!['fixture-student', 'fixture-admin'].includes(sub)) throw new Error()
    return { uid: sub, email }
  }
}))
console.log('Browser fixture server ready')
