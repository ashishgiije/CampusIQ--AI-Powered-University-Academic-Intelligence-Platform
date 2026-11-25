import { connect } from './db.js'
import { firebaseAuth } from './firebase.js'

const uid = process.argv[2]
const action = process.argv[3] || 'grant'
if (!uid || !['grant', 'revoke'].includes(action)) throw new Error('Usage: npm run admin -- FIREBASE_UID [grant|revoke]')
const account = await firebaseAuth().getUser(uid)
if (account.disabled && action === 'grant') throw new Error('Firebase account is disabled.')
const { client, db } = await connect()
try {
  const role = action === 'grant' ? 'admin' : 'student'
  const createdAt = new Date()
  await db.collection('users').updateOne({ _id: uid }, {
    $set: { role }, $setOnInsert: { profile: {}, createdAt, email: account.email || '', name: account.displayName || '' }
  }, { upsert: true })
  await db.collection('audit').insertOne({ actor: 'local-operator', action: 'role.' + action, target: uid, createdAt })
  console.log('CampusIQ role updated for UID', uid, role)
} finally {
  await client.close()
}
