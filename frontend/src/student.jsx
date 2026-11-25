import { useEffect, useState } from 'react'
import { ArrowRight, ArrowUp, ArrowUpRight, BookOpen, MessageSquare, Plus, Sparkles, Trash2 } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { request, useSession } from './auth'
import { Category, DocumentCard, Feedback, PageTitle, Resource, useResource } from './shared'

const prompts = ['What is the latest SPPU copy case punishment list?', 'Where is the latest SPPU examination circular?', 'Where can I find the MCA syllabus?']

export function StudentHome() {
  const { account } = useSession()
  const updates = useResource('/documents')
  return <>
    <PageTitle label="Student workspace" title={account.name ? 'Welcome, ' + account.name.split(' ')[0] : 'Your academic workspace'}>
      Find SPPU documents and ask questions with official sources attached.
    </PageTitle>
    <section className="banner"><div><Sparkles size={24}/><h2>Ask CampusIQ</h2><p>CampusIQ checks saved documents and searches official SPPU websites when it needs more evidence.</p></div>
      <Link className="button white" to="/student/chat">Open AI chat <ArrowRight size={17}/></Link>
    </section>
    <div className="section-title"><h2>Recent verified documents</h2><Link className="text-link" to="/student/documents">View documents <ArrowRight size={15}/></Link></div>
    <Resource resource={updates}>{rows => rows.length ? rows.slice(0, 5).map(doc => <DocumentCard key={doc._id} doc={doc}/>) :
      <Feedback>Official documents will appear here after CampusIQ finds and saves them.</Feedback>}</Resource>
  </>
}

export function Documents({ notifications = false }) {
  const [filter, setFilter] = useState({ category: '', year: '', programme: '', semester: '', session: '', q: '' })
  const [applied, setApplied] = useState('')
  const result = useResource(notifications ? '/notifications' : '/documents' + applied)
  const set = key => event => setFilter({ ...filter, [key]: event.target.value })
  return <>
    <PageTitle label="Student workspace" title={notifications ? 'Notifications' : 'Academic documents'}>
      {notifications ? 'Recently saved publications relevant to your profile.' : 'Search official SPPU publications saved by CampusIQ.'}
    </PageTitle>
    {!notifications && <form className="panel filters" onSubmit={event => {
      event.preventDefault()
      setApplied('?' + new URLSearchParams(Object.entries(filter).filter(([, value]) => value.trim())))
    }}>
      <label>Title<input value={filter.q} onChange={set('q')} placeholder="Search by title"/></label>
      <label>Document type<Category all value={filter.category} change={set('category')}/></label>
      <label>Academic year<input value={filter.year} maxLength={9} onChange={set('year')} placeholder="2026-2027"/></label>
      <label>Programme<input value={filter.programme} onChange={set('programme')} placeholder="e.g. MCA"/></label>
      <label>Semester<select value={filter.semester} onChange={set('semester')}><option value="">All semesters</option>
        {Array.from({ length: 8 }, (_, i) => <option key={i}>{i + 1}</option>)}</select></label>
      <label>Session<select value={filter.session} onChange={set('session')}><option value="">All sessions</option>
        {['winter', 'summer', 'october/november', 'april/may'].map(item => <option key={item}>{item}</option>)}</select></label>
      <button className="button primary">Apply filters</button>
    </form>}
    <Resource resource={result}>{rows => rows.length ? rows.map(doc => <DocumentCard key={doc._id} doc={doc}/>) :
      <Feedback>{notifications ? 'No notifications yet.' : 'No saved documents match these filters.'}</Feedback>}</Resource>
  </>
}

export function Profile() {
  const { account, setAccount, firebase } = useSession()
  const fields = { programme: 'Programme', year: 'Academic year', semester: 'Semester', branch: 'Branch', pattern: 'Syllabus pattern' }
  const [draft, setDraft] = useState(account.profile || {})
  const [notice, setNotice] = useState(null)
  const [saving, setSaving] = useState(false)
  async function save(event) {
    event.preventDefault()
    setSaving(true)
    setNotice(null)
    try {
      setAccount(await request(firebase, '/me/profile', { method: 'PUT', body: draft }))
      setNotice({ text: 'Academic profile saved.' })
    } catch (error) { setNotice({ text: error.message, error: true }) }
    finally { setSaving(false) }
  }
  return <>
    <PageTitle label="Account" title="Academic profile">CampusIQ uses your profile to prioritize relevant material.</PageTitle>
    <form className="panel form" onSubmit={save}>
      <label>Email<input value={account.email} readOnly/></label>
      {Object.entries(fields).map(([key, label]) => <label key={key}>{label}<input maxLength={80} value={draft[key] || ''}
        onChange={event => setDraft({ ...draft, [key]: event.target.value })}/></label>)}
      {notice && <Feedback error={notice.error}>{notice.text}</Feedback>}
      <button className="button primary" disabled={saving}>{saving ? 'Saving…' : 'Save profile'}</button>
    </form>
  </>
}

export function Chat() {
  const { sessionId } = useParams()
  const { firebase } = useSession()
  const navigate = useNavigate()
  const threads = useResource('/chats')
  const messages = useResource(sessionId ? '/chats/' + sessionId + '/messages' : null)
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [notice, setNotice] = useState('')
  const [work, setWork] = useState(null)
  const [deleting, setDeleting] = useState('')
  const [poll, refreshWork] = useState(0)
  const working = sending || (work?.chatId === sessionId && ['queued', 'running'].includes(work?.status))
  useEffect(() => {
    if (!sessionId) return
    const controller = new AbortController()
    let timer
    let wasActive = false
    async function check() {
      try {
        const current = await request(firebase, '/chats/' + sessionId + '/work', { signal: controller.signal })
        if (controller.signal.aborted) return
        setWork(current && { ...current, chatId: sessionId })
        if (current && ['queued', 'running'].includes(current.status)) {
          if (!wasActive) messages.reload()
          wasActive = true
          timer = setTimeout(check, 2200)
        } else if (current) {
          messages.reload()
        }
      } catch (error) {
        if (controller.signal.aborted) return
        setNotice(error.message)
        timer = setTimeout(check, 5000)
      }
    }
    check()
    return () => { controller.abort(); clearTimeout(timer) }
  }, [firebase, sessionId, poll])
  async function send(text) {
    if (working || text.trim().length < 3) return
    setSending(true)
    setNotice('')
    setDraft('')
    let id = sessionId
    try {
      if (!id) {
        const chat = await request(firebase, '/chats', { method: 'POST', body: { title: text.trim().slice(0, 100) } })
        id = chat._id
        navigate('/student/chat/' + id)
        threads.reload()
      }
      const queued = await request(firebase, '/chats/' + id + '/messages', { method: 'POST', body: { text } })
      setWork({ ...queued, chatId: id })
      refreshWork(value => value + 1)
      threads.reload()
    } catch (error) { setNotice(error.message); setDraft(text) }
    finally { setSending(false) }
  }
  async function deleteChat(chat) {
    if (!window.confirm('Delete this conversation and its messages?')) return
    setDeleting(chat._id)
    setNotice('')
    try {
      await request(firebase, '/chats/' + chat._id, { method: 'DELETE' })
      if (chat._id === sessionId) {
        setWork(null)
        navigate('/student/chat')
      }
      threads.reload()
    } catch (error) { setNotice(error.message) }
    finally { setDeleting('') }
  }
  return <>
    <PageTitle label="Student workspace" title="AI chat">Ask about SPPU academic information and follow the cited sources.</PageTitle>
    <div className="chat-layout">
      <aside className="panel chat-history"><Link className="button subtle" to="/student/chat" aria-disabled={working} onClick={event => working && event.preventDefault()}><Plus size={16}/> New conversation</Link>
        <Resource resource={threads}>{items => items.length ? items.map(item =>
          <div key={item._id} className="flex items-center gap-1">
          <Link className={'flex min-w-0 flex-1 items-center gap-2 rounded-lg p-2 text-sm ' + (item._id === sessionId ? 'bg-green-100' : '')} to={'/student/chat/' + item._id}
            onClick={event => working && event.preventDefault()}><MessageSquare size={15}/> <span className="truncate">{item.title}</span></Link>
          <button className="icon-button shrink-0" aria-label={'Delete chat ' + item.title}
            disabled={Boolean(deleting)} onClick={() => deleteChat(item)}><Trash2 size={15}/></button></div>) :
          <p>Conversation history will appear here.</p>}</Resource>
      </aside>
      <section className="panel chat-body" aria-label="Conversation">
        {!sessionId && !working && <div className="chat-empty"><Sparkles size={25}/><h2>What would you like to find?</h2>
          {prompts.map(text => <button key={text} className="suggestion" onClick={() => send(text)}>{text}<ArrowRight size={15}/></button>)}</div>}
        {sessionId && <Resource resource={messages}>{items => items.map(item => <article className={'message ' + item.role} key={item._id}>
          <p className="eyebrow">{item.role === 'student' ? 'You' : 'CampusIQ'}</p><p className="whitespace-pre-wrap">{item.text}</p>
          {item.citations?.map((citation, i) => <a className="citation" key={i} href={citation.url} target="_blank" rel="noopener noreferrer">
            <BookOpen size={15}/> {i + 1}. {citation.title} · page {citation.page}{citation.ocr ? ' · OCR' : ''} <ArrowUpRight size={14}/>
          </a>)}
          {!!item.inspectedSources?.length && <details className="mt-3"><summary className="text-link">Sources inspected</summary>
            {item.inspectedSources.map((source, index) => <div key={source.url} className="mt-2 text-sm">
              <a className="text-link" href={source.url} target="_blank" rel="noopener noreferrer">{index + 1}. {source.title} <ArrowUpRight size={13}/></a>
              <p>{source.reason}</p></div>)}</details>}
        </article>)}</Resource>}
        {working && <Feedback>{{ queued: 'Waiting for the search worker…', cache: 'Checking saved SPPU documents…',
          rewrite: 'Refining the academic search…', crawl: 'Searching official SPPU websites…',
          answer: 'Checking evidence and preparing your answer…' }[work?.stage] || 'Checking your question…'}</Feedback>}
        {notice && <Feedback error>{notice}</Feedback>}
        <form className="composer" onSubmit={event => { event.preventDefault(); send(draft) }}>
          <label className="sr-only" htmlFor="question">Question about SPPU</label>
          <textarea id="question" value={draft} maxLength={1200} onChange={event => setDraft(event.target.value)} placeholder="Ask about SPPU…" rows={2}/>
          <button className="button primary" aria-label="Send question" disabled={working || draft.trim().length < 3}><ArrowUp size={20}/></button>
        </form>
      </section>
    </div>
  </>
}
