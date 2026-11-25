const sessionErrors = new Set([
  'auth/argument-error', 'auth/invalid-argument', 'auth/invalid-id-token',
  'auth/id-token-expired', 'auth/id-token-revoked', 'auth/user-disabled',
  'auth/user-not-found', 'auth/tenant-id-mismatch'
])

export function authorize(verify, users) {
  return async (req, res, next) => {
    const token = /^Bearer ([^ ]+)$/.exec(req.get('authorization') || '')?.[1]
    if (!token) return res.status(401).json({ error: 'Sign in to continue.' })
    let identity
    try {
      identity = await verify(token)
    } catch (error) {
      const code = error?.code
      if (sessionErrors.has(code)) {
        return res.status(401).json({ error: 'Session invalid or expired. Sign in again.' })
      }
      const safeCode = typeof code === 'string' && /^[a-z0-9/_-]+$/i.test(code) ? code : 'unknown'
      console.error('Firebase token verification unavailable', safeCode)
      return res.status(503).json({ error: 'CampusIQ could not verify your sign-in. Check the backend Firebase configuration and try again.' })
    }
    const user = await users.findOneAndUpdate(
      { _id: identity.uid },
      { $setOnInsert: { role: 'student', profile: {}, createdAt: new Date() },
        $set: { email: identity.email || '', name: identity.name || '' } },
      { upsert: true, returnDocument: 'after' }
    )
    req.user = user
    next()
  }
}

export function adminOnly(req, res, next) {
  if (req.user.role !== 'admin') return res.status(403).json({ error: 'Administrator access required.' })
  next()
}
