import { MongoClient } from 'mongodb'

export const categories = ['punishment', 'timetable', 'circular', 'syllabus', 'calendar', 'announcement', 'document']

const schema = {
  users: { required: ['role', 'profile'], properties: { role: { enum: ['student', 'admin'] }, profile: { bsonType: 'object' } } },
  sources: { required: ['url', 'category', 'enabled'], properties: { category: { enum: categories }, enabled: { bsonType: 'bool' } } },
  jobs: { required: ['kind', 'status', 'createdAt'], properties: { status: { enum: ['queued', 'running', 'done', 'failed'] } } },
  versions: { required: ['documentId', 'state', 'digest'], properties: { state: { enum: ['pending', 'approved', 'rejected', 'failed'] } } },
  documents: { required: ['createdAt'] },
  reviews: { required: ['action', 'versionId', 'actor'] },
  chats: { required: ['owner', 'title'] },
  messages: { required: ['chatId', 'owner', 'role'], properties: { role: { enum: ['student', 'assistant'] } } },
  notifications: { required: ['versionId', 'createdAt'] },
  audit: { required: ['action', 'actor', 'createdAt'] },
  pages: { required: ['versionId', 'number', 'text'] }
}

export async function connect() {
  const client = new MongoClient(process.env.MONGO_URI || 'mongodb://127.0.0.1:27017', { serverSelectionTimeoutMS: 5000 })
  await client.connect()
  const db = client.db(process.env.MONGO_DB || 'campusiq')
  await initialize(db)
  return { client, db }
}

async function initialize(db) {
  for (const [name, shape] of Object.entries(schema)) {
    try { await db.createCollection(name, { validator: { $jsonSchema: { bsonType: 'object', ...shape } } }) }
    catch (error) {
      if (error.code !== 48) throw error
      await db.command({ collMod: name, validator: { $jsonSchema: { bsonType: 'object', ...shape } } })
    }
  }
  const indexes = {
    sources: [{ key: { url: 1, category: 1 }, unique: true }],
    jobs: [{ key: { status: 1, createdAt: 1 } }, { key: { sourceId: 1, createdAt: -1 } },
      { key: { owner: 1, chatId: 1, createdAt: -1 } }, { key: { lock: 1 }, sparse: true, unique: true }],
    versions: [{ key: { documentId: 1, digest: 1 }, unique: true }, { key: { state: 1, createdAt: -1 } }, { key: { digest: 1, category: 1 } }],
    documents: [{ key: { activeVersion: 1 } }, { key: { sourceUrl: 1, category: 1 }, unique: true }, { key: { 'public.category': 1, 'public.published': -1 } }],
    pages: [{ key: { versionId: 1, number: 1 }, unique: true }, { key: { identifiers: 1, versionId: 1 } }, { key: { text: 'text' }, default_language: 'none' }],
    chats: [{ key: { owner: 1, updatedAt: -1 } }],
    messages: [{ key: { owner: 1, chatId: 1, createdAt: 1 } }],
    notifications: [{ key: { createdAt: -1 } }],
    audit: [{ key: { createdAt: -1 } }],
    reviews: [{ key: { versionId: 1, createdAt: -1 } }],
    discovery: [{ key: { expiresAt: 1 }, expireAfterSeconds: 0 }]
  }
  await Promise.all(Object.entries(indexes).map(([name, specs]) => db.collection(name).createIndexes(specs)))
  const defaults = [
    ['SPPU Unfair Means', 'https://exam.unipune.ac.in/Pages/UnfairMeans.html', 'punishment'],
    ['SPPU Exam Timetables', 'https://exam.unipune.ac.in/Pages/SchedulesTimetables.html', 'timetable'],
    ['SPPU Online Timetables', 'https://exam.unipune.ac.in/', 'timetable'],
    ['SPPU Examination Circulars', 'https://exam.unipune.ac.in/Pages/Circulars.html', 'circular'],
    ['SPPU Syllabi', 'https://exam.unipune.ac.in/Pages/Syllabus.html', 'syllabus'],
    ['SPPU Academic Calendar', 'https://www.unipune.ac.in/university_files/academic_calender.htm', 'calendar'],
    ['SPPU Announcements', 'https://www.unipune.ac.in/', 'announcement']
    ,['SPPU Official Documents', 'https://www.unipune.ac.in/', 'document']
  ]
  for (const [name, url, category] of defaults) {
    await db.collection('sources').updateOne({ url, category }, { $setOnInsert: { name, enabled: true, intervalHours: 0, limits: { maxPages: 12, maxDocuments: 10, depth: 2 }, nextRun: new Date() } }, { upsert: true })
  }
}
