import { useEffect, useState } from 'react'
import { ArrowDownToLine, ArrowUpRight, FileText, GraduationCap } from 'lucide-react'
import { Link } from 'react-router-dom'
import { request, useSession } from './auth'

export const names = {
  punishment: 'Unfair Means', timetable: 'Timetable', circular: 'Exam circular',
  syllabus: 'Syllabus', calendar: 'Academic calendar', announcement: 'Announcement', document: 'University document'
}
export const composeDate = value => value ? new Intl.DateTimeFormat('en-IN', { dateStyle: 'medium', timeZone: 'Asia/Kolkata' }).format(new Date(value)) : 'Date unverified'

export function Brand() {
  return <Link to="/" className="brand"><span className="brand-icon"><GraduationCap size={23}/></span>Campus<span>IQ</span></Link>
}

export function useResource(path) {
  const { firebase } = useSession()
  const [state, setState] = useState({ data: null, error: '' })
  const [revision, reload] = useState(0)
  useEffect(() => {
    if (!path || !firebase) return
    const controller = new AbortController()
    request(firebase, path, { signal: controller.signal }).then(data => {
      if (!controller.signal.aborted) setState({ data, error: '', path, revision })
    }).catch(error => {
      if (!controller.signal.aborted) setState({ data: null, error: error.message, path, revision })
    })
    return () => controller.abort()
  }, [firebase, path, revision])
  const current = state.path === path && state.revision === revision ? state : { data: null, error: '' }
  return { ...current, loading: !current.data && !current.error, reload: () => reload(value => value + 1) }
}

export function Feedback({ error, children }) {
  return <div className={'feedback ' + (error ? 'error' : '')} role={error ? 'alert' : 'status'}>{children}</div>
}

export function Resource({ resource, children }) {
  if (resource.error) return <Feedback error>{resource.error} <button className="text-link" onClick={resource.reload}>Retry</button></Feedback>
  if (resource.loading) return <Feedback>Loading…</Feedback>
  return children(resource.data)
}

export function PageTitle({ label, title, children, action }) {
  return <div className="page-title"><div><p className="eyebrow">{label}</p><h1>{title}</h1>{children && <p>{children}</p>}</div>{action}</div>
}

export function DocumentCard({ doc }) {
  return <article className="document">
    <span className="document-icon"><FileText size={20}/></span>
    <div><p className="eyebrow">{names[doc.category] || doc.category} · {composeDate(doc.published)}</p>
      <h3>{doc.title}</h3>
      <p>{[doc.programme?.toUpperCase(), doc.semester && 'Semester ' + doc.semester, doc.year, doc.session].filter(Boolean).join(' · ')}</p>
    </div>
    <a className="button subtle" target="_blank" rel="noopener noreferrer" href={doc.url}>
      Official document <ArrowUpRight size={15}/>
    </a>
  </article>
}

export function Category({ value, change, all = false }) {
  return <select value={value} onChange={change}>{all && <option value="">All types</option>}
    {Object.entries(names).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select>
}

export async function downloadPdf(user, id) {
  const file = await request(user, '/admin/versions/' + id + '/pdf', { binary: true })
  return URL.createObjectURL(file)
}

export const Download = ArrowDownToLine
