import { applicationDefault, initializeApp } from 'firebase-admin/app'
import { getAuth } from 'firebase-admin/auth'

export function firebaseAuth() {
  const projectId = process.env.FIREBASE_PROJECT_ID
  if (!projectId) throw new Error('Set FIREBASE_PROJECT_ID in backend/.env.')
  return getAuth(initializeApp({ projectId, credential: applicationDefault() }))
}
