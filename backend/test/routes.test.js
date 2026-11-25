import test from 'node:test'
import assert from 'node:assert/strict'
import { randomUUID } from 'node:crypto'
import { once } from 'node:events'
import { initializeApp, deleteApp } from 'firebase-admin/app'
import { getAuth } from 'firebase-admin/auth'
import { createApp } from '../src/app.js'
import { connect } from '../src/db.js'
import { authorize, adminOnly } from '../src/auth.js'

test('Firebase Admin SDK rejects malformed untrusted tokens', async () => {
  const app = initializeApp({ projectId: 'campusiq-test-project' }, 'malformed-test')
  try { await assert.rejects(getAuth(app).verifyIdToken('a.b.c'), { code: 'auth/argument-error' }) }
  finally { await deleteApp(app) }
})

test('backend roles come from the CampusIQ user record', async () => {
  const users = { findOneAndUpdate: async (filter, update) => {
    assert.equal(filter._id, 'student-uid')
    assert.equal(update.$setOnInsert.role, 'student')
    assert.equal(update.$set.role, undefined)
    return { _id: filter._id, role: 'student' }
  } }
  const request = { get: () => 'Bearer token', body: { role: 'admin' } }
  const response = {
    status(code) { this.code = code; return this },
    json(payload) { this.payload = payload; return this }
  }
  await authorize(async () => ({ uid: 'student-uid', role: 'admin', email: 'admin@example.test' }), users)(
    request, response, () => adminOnly(request, response, () => assert.fail('Role escalated')))
  assert.equal(response.code, 403)
})

test('authentication distinguishes expired sessions from verifier failures', async t => {
  const log = t.mock.method(console, 'error', () => {})
  const users = { findOneAndUpdate: () => assert.fail('Unverified identity reached the user database') }
  const request = { get: () => 'Bearer token' }
  const response = {
    status(code) { this.code = code; return this },
    json(payload) { this.payload = payload; return this }
  }
  const verify = code => authorize(async () => {
    throw Object.assign(new Error('Sensitive verifier detail'), { code })
  }, users)(request, response, () => assert.fail('Unverified request was accepted'))

  await verify('auth/id-token-expired')
  assert.equal(response.code, 401)
  assert.match(response.payload.error, /Sign in again/)

  await verify('app/invalid-credential')
  assert.equal(response.code, 503)
  assert.match(response.payload.error, /backend Firebase configuration/)
  assert.deepEqual(log.mock.calls[0].arguments, ['Firebase token verification unavailable', 'app/invalid-credential'])
})

test('API routes enforce chat ownership, deletion and read-only administration', { skip: !process.env.CAMPUSIQ_TEST_MONGO }, async t => {
  process.env.MONGO_URI = process.env.CAMPUSIQ_TEST_MONGO
  process.env.MONGO_DB = 'campusiq_routes_' + randomUUID().replaceAll('-', '')
  const { client, db } = await connect()
  const server = createApp({ db, origin: 'http://localhost:5173', verify: async token => {
    if (!['admin', 'student', 'stranger'].includes(token)) {
      throw Object.assign(new Error('Invalid token'), { code: 'auth/invalid-id-token' })
    }
    return { uid: token }
  }, ai: () => assert.fail('Unexpected AI call') }).listen(0, '127.0.0.1')
  t.after(async () => {
    await new Promise(resolve => server.close(resolve))
    await db.dropDatabase()
    await client.close()
  })
  await once(server, 'listening')
  await db.collection('users').insertOne({ _id: 'admin', role: 'admin', profile: {} })
  const call = (path, token, body, method) => fetch('http://127.0.0.1:' + server.address().port + '/api' + path, {
    headers: { authorization: 'Bearer ' + token, 'content-type': 'application/json' },
    method: method || (body ? 'POST' : 'GET'), body: body && JSON.stringify(body)
  })
  assert.equal((await call('/me', 'invalid')).status, 401)
  assert.equal((await call('/admin/sources', 'student')).status, 403)
  assert.equal((await call('/admin/sources', 'admin')).status, 200)
  assert.equal((await call('/admin/sources', 'admin', { name: 'Private network', url: 'http://127.0.0.1/', category: 'timetable' })).status, 404)
  const chat = await (await call('/chats', 'student', { title: 'Test chat' })).json()
  assert.equal((await call('/chats/' + chat._id + '/messages', 'stranger')).status, 404)
  assert.equal((await call('/chats/' + chat._id + '/work', 'stranger')).status, 404)
  const question = { text: 'When does the MCA timetable start?' }
  const chatJob = await call('/chats/' + chat._id + '/messages', 'student', question)
  assert.equal(chatJob.status, 202)
  assert.equal((await call('/chats/' + chat._id + '/messages', 'student', question)).status, 409)
  const work = await (await call('/chats/' + chat._id + '/work', 'student')).json()
  assert.equal(work.status, 'queued')
  assert.equal(work.question, undefined)
  const logs = await (await call('/admin/jobs', 'admin')).json()
  assert.equal(logs.find(job => job.kind === 'answer').question, undefined)
  const doc = await db.collection('documents').insertOne({ createdAt: new Date(), activeVersion: null, sourceUrl: 'https://exam.unipune.ac.in/synthetic.pdf', category: 'timetable' })
  const candidate = await db.collection('versions').insertOne({
    documentId: doc.insertedId, state: 'pending', digest: 'a'.repeat(64), valid: true, readable: true, relevant: true
  })
  const action = { action: 'approve', verified: true, metadata: { title: 'Synthetic timetable' } }
  const endpoint = '/admin/versions/' + candidate.insertedId + '/review'
  assert.equal((await call(endpoint, 'student', action)).status, 403)
  for (const operation of ['approve', 'reject', 'revoke', 'reprocess']) {
    assert.equal((await call(endpoint, 'admin', { ...action, action: operation })).status, 404)
  }
  assert.equal((await call('/admin/jobs', 'admin', { sourceId: candidate.insertedId.toString() })).status, 404)
  assert.equal(await db.collection('jobs').countDocuments({ kind: 'approve' }), 0)
  assert.deepEqual(await (await call('/documents', 'student')).json(), [])
  assert.equal((await call('/chats/' + chat._id, 'stranger', undefined, 'DELETE')).status, 404)
  assert.equal((await call('/chats/' + chat._id, 'student', undefined, 'DELETE')).status, 204)
  assert.deepEqual(await (await call('/chats', 'student')).json(), [])
  assert.equal((await call('/chats/' + chat._id + '/messages', 'student')).status, 404)
  assert.equal((await call('/chats/' + chat._id + '/messages', 'student', question)).status, 404)
  const deletedJob = await db.collection('jobs').findOne({ kind: 'answer' })
  assert.equal(deletedJob.status, 'done')
  assert.equal(deletedJob.question, undefined)
  assert.equal(deletedJob.lock, undefined)
})
