import { createContext, useContext, useEffect, useState } from 'react'
import { initializeApp } from 'firebase/app'
import {
  getAuth, onAuthStateChanged, createUserWithEmailAndPassword, signInWithEmailAndPassword,
  sendPasswordResetEmail, GoogleAuthProvider, signInWithPopup, signOut
} from 'firebase/auth'

const env = import.meta.env
const config = { apiKey: env.VITE_FIREBASE_API_KEY, authDomain: env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: env.VITE_FIREBASE_PROJECT_ID, appId: env.VITE_FIREBASE_APP_ID }
const auth = Object.values(config).every(Boolean) ? getAuth(initializeApp(config)) : null
const Session = createContext(null)
const base = env.VITE_API_URL || 'http://127.0.0.1:4000'

export async function request(user, path, { method = 'GET', body, binary, signal } = {}) {
  const token = await user.getIdToken()
  const headers = { authorization: 'Bearer ' + token }
  if (body) headers['content-type'] = 'application/json'
  const response = await fetch(base + '/api' + path, { method, headers, signal, body: body && JSON.stringify(body) })
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}))
    throw new Error(detail.error || 'CampusIQ request failed.')
  }
  if (response.status === 204) return null
  return binary ? response.blob() : response.json()
}

export function AuthProvider({ children }) {
  const [firebase, setFirebase] = useState(null)
  const [account, setAccount] = useState(null)
  const [busy, setBusy] = useState(Boolean(auth))
  const [failure, setFailure] = useState('')
  useEffect(() => {
    if (!auth) return
    let generation = 0
    const close = onAuthStateChanged(auth, async user => {
      const current = ++generation
      setFirebase(user)
      setAccount(null)
      setFailure('')
      setBusy(Boolean(user))
      if (!user) return
      try {
        const next = await request(user, '/me')
        if (current === generation) setAccount(next)
      } catch (error) {
        if (current === generation) setFailure(error.message)
      } finally {
        if (current === generation) setBusy(false)
      }
    })
    return () => { generation++; close() }
  }, [])
  const value = {
    firebase, account, setAccount, busy, failure, configured: Boolean(auth),
    googleEnabled: env.VITE_GOOGLE_SIGN_IN === 'true',
    signIn: (email, password) => signInWithEmailAndPassword(auth, email, password),
    signUp: (email, password) => createUserWithEmailAndPassword(auth, email, password),
    reset: email => sendPasswordResetEmail(auth, email),
    google: () => signInWithPopup(auth, new GoogleAuthProvider()),
    logout: () => signOut(auth)
  }
  return <Session.Provider value={value}>{children}</Session.Provider>
}

export const useSession = () => useContext(Session)
