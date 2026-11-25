import { createRoot } from 'react-dom/client'
import { useState } from 'react'
import { BrowserRouter, Link, Navigate, NavLink, Outlet, Route, Routes } from 'react-router-dom'
import {
  ArrowRight, Bell, BookOpen, ClipboardCheck, FileText, GraduationCap, History,
  House, LibraryBig, LogOut, Menu, MessageSquare, Radio, ShieldCheck, Sparkles, Users, X
} from 'lucide-react'
import { AuthProvider, useSession } from './auth'
import { Brand, Feedback } from './shared'
import { Chat, Documents, Profile, StudentHome } from './student'
import { AdminHome, JobDetail, Jobs, Logs, Publications, ReviewDetail, ReviewQueue, Sources, Users as Accounts } from './admin'
import './styles.css'

function Landing() {
  const { account } = useSession()
  const destination = account?.role === 'admin' ? '/admin' : account ? '/student' : '/login'
  return <div className="public-shell">
    <header className="public-header"><Brand/><nav aria-label="Public navigation">
      <Link className="button subtle" to={destination}>{account ? 'Open workspace' : 'Sign in'}</Link>
      {!account && <Link className="button primary" to="/signup">Create account</Link>}
    </nav></header>
    <main id="main" className="landing">
      <section className="hero">
        <div><p className="eyebrow">Savitribai Phule Pune University</p>
          <h1>Your university<br/>information.<br/><em>With a source.</em></h1>
          <p className="hero-copy">Find SPPU timetables, circulars and syllabi in one place. Ask a question and follow the answer back to the official document.</p>
          <Link className="button primary" to={destination}>{account ? 'Open workspace' : 'Get started'} <ArrowRight size={18}/></Link>
        </div>
        <div className="hero-visual" aria-hidden="true">
          <div className="visual-orbit inner"/><div className="visual-orbit outer"/>
          <div className="visual-item visual-top"><LibraryBig size={30}/></div>
          <div className="visual-item visual-left"><Sparkles size={30}/></div>
          <div className="visual-item visual-right"><ShieldCheck size={30}/></div>
          <div className="visual-center"><GraduationCap size={86} strokeWidth={1.15}/></div>
        </div>
      </section>
      <section aria-label="CampusIQ capabilities" className="features">
        {[[BookOpen, 'Academic library', 'Filter saved SPPU publications by document type, programme, semester and exam session.'],
          [Sparkles, 'AI answers with citations', 'Ask in your own words and see the official source and page behind each answer.'],
          [ShieldCheck, 'Official sources', 'CampusIQ searches SPPU websites and saves validated documents for future questions.']
        ].map(([Icon, title, text]) => <article className="panel" key={title}><span className="document-icon"><Icon size={21}/></span><h2>{title}</h2><p>{text}</p></article>)}
      </section>
    </main>
    <footer className="public-footer"><span>CampusIQ</span><span>SPPU academic information workspace</span></footer>
  </div>
}

function AuthPage({ mode }) {
  const session = useSession()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState(null)
  if (session.account) return <Navigate replace to={session.account.role === 'admin' ? '/admin' : '/student'}/>
  const title = { login: 'Sign in', signup: 'Create an account', reset: 'Reset password' }[mode]
  async function complete(kind) {
    setPending(true)
    setMessage(null)
    try {
      if (kind === 'reset') {
        await session.reset(email)
        setMessage({ text: 'If an account exists for that email, check your inbox for a reset link.' })
      } else if (kind === 'google') await session.google()
      else if (kind === 'signup') await session.signUp(email, password)
      else await session.signIn(email, password)
    } catch (error) {
      const reason = {
        'auth/invalid-credential': 'Check your email and password.',
        'auth/email-already-in-use': 'That email is already registered. Sign in or reset your password.',
        'auth/weak-password': 'Choose a stronger password.',
        'auth/popup-blocked': 'Allow sign-in popups for this site and try again.',
        'auth/popup-closed-by-user': 'The Google sign-in window was closed.',
        'auth/operation-not-allowed': 'This sign-in method is disabled in Firebase.',
        'auth/unauthorized-domain': 'Add localhost to Firebase Authentication authorized domains.',
        'auth/too-many-requests': 'Too many attempts. Try again later.',
        'auth/network-request-failed': 'Could not reach Firebase. Check your connection.'
      }[error.code]
      setMessage(kind === 'reset' && error.code === 'auth/user-not-found' ?
        { text: 'If an account exists for that email, check your inbox for a reset link.' } :
        { error: true, text: reason || 'Firebase could not complete the request. Check the authentication configuration.' })
    } finally { setPending(false) }
  }
  return <div className="public-shell"><header className="public-header"><Brand/><Link className="text-link" to="/">Home</Link></header>
    <main id="main" className="auth-stage"><div className="panel auth-card">
      <p className="eyebrow">CampusIQ account</p><h1>{title}</h1>
      {!session.configured && <Feedback error>Firebase is not configured. Set the web client variables in frontend/.env and restart Vite.</Feedback>}
      {(message || session.failure) && <Feedback error={message?.error || Boolean(session.failure)}>{message?.text || session.failure}</Feedback>}
      <form className="form" onSubmit={event => { event.preventDefault(); complete(mode) }}>
        <label>Email<input value={email} required type="email" autoComplete="email" onChange={event => setEmail(event.target.value)}/></label>
        {mode !== 'reset' && <label>Password<input value={password} required minLength={mode === 'signup' ? 6 : undefined}
          type="password" autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} onChange={event => setPassword(event.target.value)}/></label>}
        <button className="button primary" disabled={!session.configured || pending || session.busy}>{pending || session.busy ? 'Please wait…' : title}<ArrowRight size={17}/></button>
      </form>
      {mode !== 'reset' && session.googleEnabled && <button className="button subtle" disabled={!session.configured || pending}
        onClick={() => complete('google')}>Continue with Google</button>}
      <div className="auth-links">
        {mode !== 'login' && <Link to="/login">Sign in</Link>}
        {mode === 'login' && <><Link to="/signup">Create account</Link><Link to="/reset">Forgot password?</Link></>}
      </div>
    </div></main></div>
}

const student = [
  ['Overview', '/student', House], ['AI chat', '/student/chat', MessageSquare], ['Academic documents', '/student/documents', LibraryBig],
  ['Notifications', '/student/notifications', Bell], ['Academic profile', '/student/profile', GraduationCap]
]
const admin = [
  ['Overview', '/admin', House], ['Source registry', '/admin/sources', Radio], ['Crawling jobs', '/admin/jobs', History],
  ['Discovered documents', '/admin/review', ClipboardCheck], ['Saved documents', '/admin/publications', FileText],
  ['Audit history', '/admin/logs', ShieldCheck], ['Accounts', '/admin/users', Users]
]

function Workspace({ administrator = false }) {
  const { account, busy, failure, logout } = useSession()
  const [opened, setOpened] = useState(false)
  const [logoutError, setLogoutError] = useState('')
  if (busy || failure) return <main id="main" className="auth-stage"><Feedback error={Boolean(failure)}>
    {failure || 'Checking your session…'} {failure && <button className="text-link" onClick={() => window.location.reload()}>Retry</button>}
  </Feedback></main>
  if (!account) return <Navigate replace to="/login"/>
  if (administrator && account.role !== 'admin') return <Navigate replace to="/student"/>
  const items = administrator ? admin : student
  return <div className="workspace">
    <aside className={'sidebar ' + (opened ? 'opened' : '')}>
      <div className="sidebar-brand"><Brand/><button className="mobile-toggle" aria-label="Close navigation" onClick={() => setOpened(false)}><X size={22}/></button></div>
      <p className="eyebrow">{administrator ? 'Administration' : 'Student workspace'}</p>
      <nav aria-label="Workspace">{items.map(([label, path, Icon], index) =>
        <NavLink key={path} end={!index} to={path} onClick={() => setOpened(false)}><Icon size={18}/> {label}</NavLink>)}</nav>
      {account.role === 'admin' && <Link className="switch" to={administrator ? '/student' : '/admin'} onClick={() => setOpened(false)}>
        <ArrowRight size={16}/> {administrator ? 'Student workspace' : 'Admin workspace'}</Link>}
      <div className="sidebar-foot"><span className="avatar">{(account.name || account.email || 'C').slice(0, 1).toUpperCase()}</span>
        <div><strong>{account.name || account.email || 'CampusIQ account'}</strong><p>{account.role}</p></div>
        <button className="icon-button" aria-label="Sign out" title="Sign out" onClick={() => logout().catch(() => setLogoutError('Could not sign out. Try again.'))}><LogOut size={17}/></button>
      </div>
    </aside>
    <div className="workspace-body">
      <header className="workspace-bar"><button className="mobile-toggle" aria-label="Open navigation" aria-expanded={opened} onClick={() => setOpened(true)}><Menu size={22}/></button>
        <span>SPPU Academic Intelligence</span><span className="workspace-label">{administrator ? 'Admin portal' : 'Student portal'}</span></header>
      <main id="main" className="workspace-content">{logoutError && <Feedback error>{logoutError}</Feedback>}<Outlet/></main>
    </div>
  </div>
}

function App() {
  return <BrowserRouter><AuthProvider><a className="skip-link" href="#main">Skip to main content</a><Routes>
    <Route path="/" element={<Landing/>}/>
    <Route path="/login" element={<AuthPage key="login" mode="login"/>}/>
    <Route path="/signup" element={<AuthPage key="signup" mode="signup"/>}/>
    <Route path="/reset" element={<AuthPage key="reset" mode="reset"/>}/>
    <Route path="/student" element={<Workspace/>}>
      <Route index element={<StudentHome/>}/>
      <Route path="chat/:sessionId?" element={<Chat/>}/>
      <Route path="documents" element={<Documents/>}/>
      <Route path="notifications" element={<Documents notifications/>}/>
      <Route path="profile" element={<Profile/>}/>
    </Route>
    <Route path="/admin" element={<Workspace administrator/>}>
      <Route index element={<AdminHome/>}/>
      <Route path="sources" element={<Sources/>}/>
      <Route path="jobs" element={<Jobs/>}/>
      <Route path="jobs/:id" element={<JobDetail/>}/>
      <Route path="review" element={<ReviewQueue/>}/>
      <Route path="review/:id" element={<ReviewDetail/>}/>
      <Route path="publications" element={<Publications/>}/>
      <Route path="logs" element={<Logs/>}/>
      <Route path="users" element={<Accounts/>}/>
    </Route>
    <Route path="*" element={<main id="main" className="auth-stage"><Feedback error>Page not found. <Link className="text-link" to="/">Go home</Link></Feedback></main>}/>
  </Routes></AuthProvider></BrowserRouter>
}

createRoot(document.getElementById('root')).render(<App/>)
