import express from 'express'
import { Readable } from 'node:stream'
import cors from 'cors'
import helmet from 'helmet'
import { rateLimit } from 'express-rate-limit'
import { ObjectId } from 'mongodb'
import { z, ZodError } from 'zod'
import { adminOnly, authorize } from './auth.js'
import { categories } from './db.js'

const idString = z.string().regex(/^[a-f0-9]{24}$/)
const id = value => new ObjectId(idString.parse(value))
const profile = z.object(Object.fromEntries(
  ['programme', 'year', 'semester', 'branch', 'pattern'].map(field => [field, z.string().trim().max(80).default('')])
))
const linked = (value, res, message = 'Record not found.') => {
  if (value) return true
  res.status(404).json({ error: message })
  return false
}

export function searchableFilter(extra = {}) {
  return { activeVersion: { $type: 'objectId' }, ...extra }
}

export function createApp({ db, verify, ai, getPdf, origin, sharepointHost }) {
  const app = express()
  const c = name => db.collection(name)
  const audit = (actor, action, target, extra = {}) => c('audit').insertOne({ actor, action, target, createdAt: new Date(), ...extra })
  const list = (name, filter = {}, project, max = 100) => c(name).find(filter, { projection: project }).sort({ createdAt: -1 }).limit(max).toArray()

  app.disable('x-powered-by')
  app.use(helmet(), cors({ origin }), express.json({ limit: '64kb' }))
  app.use('/api', (_req, res, next) => {
    res.set('Cache-Control', 'no-store')
    next()
  })
  app.get('/health', async (_req, res) => {
    await db.command({ ping: 1 })
    res.json({ status: 'ok' })
  })
  app.use('/api', rateLimit({ windowMs: 60_000, limit: 180 }), authorize(verify, c('users')))
  app.get('/api/me', (req, res) => res.json(req.user))
  app.put('/api/me/profile', async (req, res) => {
    const user = await c('users').findOneAndUpdate({ _id: req.user._id }, { $set: { profile: profile.parse(req.body) } }, { returnDocument: 'after' })
    res.json(user)
  })

  app.get('/api/documents', async (req, res) => {
    const filter = z.object({
      category: z.enum(categories).optional(),
      year: z.string().trim().max(9).optional(),
      programme: z.string().trim().max(80).optional(),
      semester: z.string().trim().max(1).optional(),
      session: z.string().trim().max(30).optional(),
      q: z.string().trim().max(100).optional()
    }).parse(req.query)
    const clauses = {}
    for (const key of ['category', 'year', 'programme', 'semester', 'session']) {
      if (filter[key]) clauses['public.' + key] = filter[key].toLowerCase()
    }
    if (filter.q) clauses['public.title'] = { $regex: filter.q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), $options: 'i' }
    const records = await c('documents').find(searchableFilter(clauses), { projection: { public: 1, activeVersion: 1 } }).sort({ 'public.published': -1, activatedAt: -1 }).limit(100).toArray()
    res.json(records.map(({ _id, public: fields, activeVersion }) => ({ _id, ...fields, activeVersion })))
  })
  app.get('/api/notifications', async (req, res) => {
    const rows = await c('notifications').aggregate([
      { $sort: { createdAt: -1 } },
      { $lookup: { from: 'documents', localField: 'versionId', foreignField: 'activeVersion', as: 'document' } },
      { $unwind: '$document' },
      { $replaceWith: { $mergeObjects: ['$document.public', { _id: '$_id', createdAt: '$createdAt' }] } },
      { $limit: 100 }
    ]).toArray()
    const programme = req.user.profile.programme?.toLowerCase()
    res.json(rows.filter(row => !programme || !row.programme || row.programme === programme))
  })
  app.get('/api/chats', async (req, res) => {
    res.json(await c('chats').find({ owner: req.user._id, deletedAt: { $exists: false } }).sort({ updatedAt: -1 }).limit(100).toArray())
  })
  app.post('/api/chats', async (req, res) => {
    const title = z.string().trim().min(1).max(100).parse(req.body.title)
    const now = new Date()
    const { insertedId } = await c('chats').insertOne({ title, owner: req.user._id, createdAt: now, updatedAt: now })
    res.status(201).json({ _id: insertedId, title })
  })
  app.delete('/api/chats/:chatId', async (req, res) => {
    const chatId = id(req.params.chatId)
    const owner = req.user._id
    const chat = await c('chats').findOneAndUpdate(
      { _id: chatId, owner, deletedAt: { $exists: false } },
      { $set: { deletedAt: new Date() } }, { returnDocument: 'after' })
    if (!linked(chat, res)) return
    await c('jobs').updateMany({ chatId, owner, status: 'queued' }, {
      $set: { status: 'done', stage: 'deleted', cancelRequested: true, finishedAt: new Date() },
      $unset: { lock: '', question: '', context: '' }
    })
    await c('jobs').updateMany({ chatId, owner, status: 'running' }, { $set: { cancelRequested: true } })
    await c('messages').deleteMany({ chatId, owner })
    res.status(204).end()
  })
  app.get('/api/chats/:chatId/messages', async (req, res) => {
    const chatId = id(req.params.chatId)
    const owner = req.user._id
    if (!linked(await c('chats').findOne({ _id: chatId, owner, deletedAt: { $exists: false } }), res)) return
    const messages = (await list('messages', { chatId, owner }, undefined, 200)).reverse()
    const versions = messages.flatMap(row => (row.citations || []).map(item => id(item.versionId)))
    const live = new Set((await c('documents').find({ activeVersion: { $in: versions } }, { projection: { activeVersion: 1 } }).toArray()).map(doc => doc.activeVersion.toString()))
    res.json(messages.map(row => row.citations?.some(item => !live.has(item.versionId)) ?
      { _id: row._id, role: 'assistant', text: 'A source for this answer was replaced or withdrawn. Ask again to check current evidence.', citations: [] } : row))
  })
  app.post('/api/chats/:chatId/messages', rateLimit({ windowMs: 60_000, limit: 15 }), async (req, res) => {
    const chatId = id(req.params.chatId)
    const owner = req.user._id
    const text = z.string().trim().min(3).max(1200).parse(req.body.text)
    if (!linked(await c('chats').findOne({ _id: chatId, owner, deletedAt: { $exists: false } }), res)) return
    const createdAt = new Date()
    const { insertedId } = await c('jobs').insertOne({
      kind: 'answer', status: 'queued', stage: 'queued', createdAt, owner, chatId,
      lock: 'answer:' + owner, questionId: new ObjectId(), question: text, context: req.user.profile, events: []
    })
    if (!await c('chats').findOne({ _id: chatId, owner, deletedAt: { $exists: false } })) {
      await c('jobs').updateOne({ _id: insertedId, status: 'queued' }, { $set: { cancelRequested: true, status: 'done', stage: 'deleted' },
        $unset: { lock: '', question: '', context: '' } })
      await c('jobs').updateOne({ _id: insertedId, status: 'running' }, { $set: { cancelRequested: true } })
      return res.status(404).json({ error: 'Conversation was deleted.' })
    }
    await c('chats').updateOne({ _id: chatId, owner }, { $set: { updatedAt: createdAt } })
    res.status(202).json({ _id: insertedId, status: 'queued', stage: 'queued' })
  })
  app.get('/api/chats/:chatId/work', async (req, res) => {
    const chatId = id(req.params.chatId)
    const owner = req.user._id
    if (!linked(await c('chats').findOne({ _id: chatId, owner, deletedAt: { $exists: false } }), res)) return
    const job = await c('jobs').findOne({ kind: 'answer', chatId, owner }, {
      sort: { createdAt: -1 }, projection: { status: 1, stage: 1 }
    })
    res.json(job)
  })

  app.use('/api/admin', adminOnly)
  app.get('/api/admin/overview', async (_req, res) => {
    const [states, discovered, approved, updated, failedJobs, pendingJobs] = await Promise.all([
      c('versions').aggregate([{ $group: { _id: '$state', count: { $sum: 1 } } }]).toArray(),
      c('documents').countDocuments(),
      c('documents').countDocuments(searchableFilter()),
      c('documents').countDocuments({ $or: [{ revisionCount: { $gt: 1 } }, { previousVersion: { $type: 'objectId' } }] }),
      c('jobs').countDocuments({ status: 'failed' }),
      c('jobs').countDocuments({ status: { $in: ['queued', 'running'] } })
    ])
    res.json({ pending: 0, rejected: 0, failed: 0, ...Object.fromEntries(states.map(row => [row._id, row.count])), discovered, approved, updated, failedJobs, pendingJobs })
  })
  app.get('/api/admin/monitor', async (_req, res) => res.json(await ai('/internal/status')))
  app.get('/api/admin/sources', async (_req, res) => {
    const sources = await list('sources')
    res.json(await Promise.all(sources.map(async source => {
      const last = await c('jobs').findOne({ sourceId: source._id }, { sort: { createdAt: -1 }, projection: { status: 1, createdAt: 1 } })
      return { ...source, last }
    })))
  })
  const adminJobProjection = { question: 0, context: 0, owner: 0, chatId: 0, questionId: 0, lock: 0 }
  app.get('/api/admin/jobs', async (_req, res) => res.json(await list('jobs', {}, { ...adminJobProjection, events: { $slice: -20 } }, 50)))
  app.get('/api/admin/jobs/:id', async (req, res) => {
    const job = await c('jobs').findOne({ _id: id(req.params.id) }, { projection: adminJobProjection })
    if (linked(job, res)) res.json(job)
  })
  app.get('/api/admin/versions', async (req, res) => {
    const filter = req.query.state ? { state: z.enum(['pending', 'approved', 'rejected', 'failed']).parse(req.query.state) } : {}
    res.json(await list('versions', filter, { validation: 0, warnings: 0 }))
  })
  app.get('/api/admin/versions/:id', async (req, res) => {
    const versionId = id(req.params.id)
    const version = await c('versions').findOne({ _id: versionId })
    if (!linked(version, res)) return
    const page = z.coerce.number().int().min(1).max(250).default(1).parse(req.query.page)
    const [content, reviews, document] = await Promise.all([
      c('pages').findOne({ versionId, number: page }, { projection: { text: 1, number: 1, ocr: 1 } }),
      list('reviews', { versionId }),
      c('documents').findOne({ _id: version.documentId })
    ])
    const canonical = document?.canonicalDocumentId ? await c('documents').findOne({ _id: document.canonicalDocumentId }) : document
    if (version.restricted) await audit(req.user._id, 'restricted.review', versionId, { page })
    res.json({ ...version, content, reviews, activeVersion: canonical?.activeVersion })
  })
  app.get('/api/admin/versions/:id/pdf', async (req, res) => {
    const versionId = id(req.params.id)
    const pdf = await getPdf(versionId)
    if (!linked(pdf, res, 'Stored PDF unavailable.')) return
    await audit(req.user._id, 'pdf.review', versionId)
    res.type('application/pdf').attachment('campusiq-review.pdf')
    const stream = Readable.fromWeb(pdf.body)
    res.on('close', () => stream.destroy())
    stream.on('error', () => res.destroy())
    stream.pipe(res)
  })
  app.post('/api/admin/versions/:id/exact', rateLimit({ windowMs: 60_000, limit: 20 }), async (req, res) => {
    const version = id(req.params.id).toString()
    const identifier = z.string().trim().regex(/^[\p{L}\p{N}_/-]{3,40}$/u).parse(req.body.identifier)
    await audit(req.user._id, 'identifier.lookup', version)
    res.json(await ai('/internal/exact', { version, identifier }))
  })
  app.get('/api/admin/audit', async (_req, res) => res.json(await list('audit')))
  app.get('/api/admin/users', async (_req, res) => res.json(await list('users', {}, { profile: 0 })))
  app.use((_req, res) => res.status(404).json({ error: 'Endpoint not found.' }))
  app.use((error, _req, res, _next) => {
    if (error instanceof ZodError) return res.status(400).json({ error: error.issues.map(issue => issue.path.join('.') + ' ' + issue.message).join('; ') })
    if (error.code === 11000) return res.status(409).json({ error: 'A matching record or operation already exists.' })
    if (error.type === 'entity.parse.failed') return res.status(400).json({ error: 'Invalid JSON body.' })
    if (error.status === 503) return res.status(503).json({ error: error.message })
    console.error(error.name, error.code || '')
    res.status(500).json({ error: 'Request failed. Check service logs.' })
  })
  return app
}
