import { useEffect, useState } from 'react'
import { ArrowUpRight, FileSearch, RefreshCw } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'
import { useSession } from './auth'
import { DocumentCard, downloadPdf, Feedback, names, PageTitle, Resource, useResource } from './shared'

const stamp = value => value ? new Date(value).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' }) : ''

export function AdminHome() {
  const overview = useResource('/admin/overview')
  const monitor = useResource('/admin/monitor')
  return <>
    <PageTitle label="Administration" title="Operations overview" action={<Link className="button subtle" to="/admin/jobs">View search activity</Link>}>
      Check automatic searches, saved publications and service health.
    </PageTitle>
    <Resource resource={overview}>{data => <div className="stats">{['discovered', 'approved', 'failed', 'updated', 'pendingJobs', 'failedJobs'].map(key =>
      <article className="panel" key={key}><p>{{ approved: 'saved', pendingJobs: 'active searches', failedJobs: 'failed searches' }[key] || key}</p><strong>{data[key]}</strong></article>)}</div>}</Resource>
    <div className="section-title"><h2>Service health</h2><button className="button subtle" onClick={monitor.reload}><RefreshCw size={15}/> Refresh</button></div>
    <Resource resource={monitor}>{data => <div className="panel health">{Object.entries({ MongoDB: data.mongo, Worker: data.worker,
      Qdrant: data.qdrant, 'Gemini configured': data.geminiConfigured }).map(([label, healthy]) =>
      <p key={label}><span>{label}</span><span className={'status ' + (healthy ? 'done' : 'failed')}>{healthy ? 'Ready' : 'Unavailable'}</span></p>)}</div>}</Resource>
  </>
}

export function Sources() {
  const result = useResource('/admin/sources')
  return <>
    <PageTitle label="Discovery" title="Source registry">Official university sections used by student searches.</PageTitle>
    <Resource resource={result}>{rows => rows.map(row => <article className="document" key={row._id}>
      <span className="status">{row.enabled ? 'Enabled' : 'Disabled'}</span>
      <div><h3>{row.name}</h3><a className="text-link break-all" href={row.url} target="_blank" rel="noreferrer">{row.url}</a>
      <p>{names[row.category]} · {row.last?.status || 'No searches yet'}</p></div>
    </article>)}</Resource>
  </>
}

export function Jobs() {
  const jobs = useResource('/admin/jobs')
  return <>
    <PageTitle label="Discovery" title="Search activity" action={<button className="button subtle" onClick={jobs.reload}><RefreshCw size={15}/> Refresh</button>}>
      Monitor automatic searches, crawler logs and extraction errors.
    </PageTitle>
    <Resource resource={jobs}>{rows => rows.length ? rows.map(job => <article className="document" key={job._id}>
      <span className={'status ' + job.status}>{job.status}</span><div><h3>{job.kind === 'answer' ? 'Student search' : job.kind}</h3>
      <p>{stamp(job.createdAt)}</p>{job.error && <p className="error-text">{job.error}</p>}</div>
      <Link className="button subtle" to={'/admin/jobs/' + job._id}>Open log</Link>
    </article>) : <Feedback>No searches yet.</Feedback>}</Resource>
  </>
}

export function JobDetail() {
  const { id } = useParams()
  const item = useResource('/admin/jobs/' + id)
  return <>
    <PageTitle label="Crawling jobs" title="Job log" action={<button className="button subtle" onClick={item.reload}><RefreshCw size={15}/> Refresh</button>}/>
    <Resource resource={item}>{job => <div className="panel form wide"><span className={'status ' + job.status}>{job.status}</span>
      <h2 className="capitalize">{job.kind} · {stamp(job.createdAt)}</h2>
      {job.counts?.pages !== undefined && <p>{job.counts.pages} listings · {job.counts.documents} documents · {job.counts.saved === undefined ? '' : job.counts.saved + ' saved · '}{job.counts.errors} errors</p>}
      {job.error && <Feedback error>{job.error}</Feedback>}
      <ul className="logs">{job.events.map((line, index) => <li key={index}><span>{stamp(line.at)} · {line.stage}</span>
        <strong>{line.message}</strong>{line.url && <code>{line.url}</code>}</li>)}</ul>
      <Link className="text-link" to="/admin/jobs">Back to jobs</Link></div>}</Resource>
  </>
}

export function ReviewQueue() {
  const [state, setState] = useState('')
  const rows = useResource('/admin/versions' + (state ? '?state=' + state : ''))
  return <>
    <PageTitle label="Discovery" title="Discovered documents" action={<label className="compact">Status<select value={state} onChange={event => setState(event.target.value)}>
      <option value="">All documents</option><option value="pending">Downloaded</option>
      <option value="approved">Saved</option><option value="failed">Extraction failed</option>
    </select></label>}>Inspect saved documents, extraction warnings and candidates that need review.</PageTitle>
    <Resource resource={rows}>{versions => versions.length ? versions.map(version => <article className="document" key={version._id}>
      <span className="document-icon"><FileSearch size={20}/></span><div><p className="eyebrow">{names[version.category]} · {version.state}</p>
        <h3>{version.title}</h3><p>{version.pageCount || 0} pages · {version.relevant ? 'Relevant evidence' : 'Needs attention'}{version.predecessor || version.suggestedPredecessor ? ' · Revision candidate' : ''}</p></div>
      <Link className="button subtle" to={'/admin/review/' + version._id}>Review</Link>
    </article>) : <Feedback>No versions in this view.</Feedback>}</Resource>
  </>
}

function DocumentPreview({ version }) {
  const { firebase } = useSession()
  const [pdf, setPdf] = useState('')
  const [error, setError] = useState('')
  useEffect(() => () => { if (pdf) URL.revokeObjectURL(pdf) }, [pdf])
  async function load() {
    setError('')
    try { setPdf(await downloadPdf(firebase, version._id)) }
    catch (failure) { setError(failure.message) }
  }
  return <>
    <div className="toolbar"><a className="button subtle" href={version.url} target="_blank" rel="noreferrer">Official source <ArrowUpRight size={15}/></a>
    {version.format === 'pdf' && version.valid && <button className="button subtle" onClick={load}>Preview stored PDF</button>}</div>
    {error && <Feedback error>{error}</Feedback>}
    {pdf && <object className="pdf-preview" data={pdf} type="application/pdf" aria-label="Stored PDF preview"><a href={pdf} download="campusiq-document.pdf">Download PDF</a></object>}
  </>
}

export function ReviewDetail() {
  const { id } = useParams()
  const [page, setPage] = useState(1)
  const version = useResource('/admin/versions/' + id + '?page=' + page)
  return <Resource resource={version}>{data => <>
    <PageTitle label={names[data.category] || 'Publishing'} title={data.title} action={<button className="button subtle" onClick={version.reload}><RefreshCw size={15}/> Refresh</button>}>
      Version {data._id}
    </PageTitle>
    <section className="panel form wide"><h2>Extraction evidence</h2>
      <div className="toolbar"><span className="status">{data.state}</span><span>{data.valid ? 'Valid file' : 'Invalid or unprocessed'}</span>
        <span>{data.readable ? 'Readable' : 'Unreadable'} · {data.readablePages || 0}/{data.pageCount || 0} pages with usable text</span>
        <span>{data.relevant ? 'Relevant' : 'Relevance check failed'}</span>
        {data.restricted && <span className="status failed">Restricted</span>}</div>
      {(data.reasons || []).concat(data.warnings || []).map((line, index) => <p className="error-text" key={index}>{line}</p>)}
      {data.validation?.listing && <p>{data.validation.listing}</p>}
      <div className="toolbar"><button className="button subtle" disabled={page === 1} onClick={() => setPage(page - 1)}>Previous</button>
        <span>Page {page} of {data.pageCount || 0}{data.content?.ocr && ' · OCR'}</span>
        <button className="button subtle" disabled={page >= data.pageCount || !data.pageCount} onClick={() => setPage(page + 1)}>Next</button></div>
      <pre className="excerpt">{data.content?.text || 'No extracted text for this page.'}</pre>
    </section>
    <DocumentPreview key={id} version={data}/>
    {!!data.reviews.length && <section className="panel form wide"><h2>Review history</h2><ul className="logs">{data.reviews.map(review =>
      <li key={review._id}><span>{stamp(review.createdAt)} · {review.actor}</span><strong>{review.action}</strong><p>{review.notes}</p></li>)}</ul></section>}
  </>}</Resource>
}

export function Publications() {
  const documents = useResource('/documents')
  return <>
    <PageTitle label="Publishing" title="Saved documents">These are the official sources available to students.</PageTitle>
    <Resource resource={documents}>{rows => rows.length ? rows.map(doc => <div className="publication" key={doc._id}>
      <DocumentCard doc={doc}/><Link className="text-link" to={'/admin/review/' + doc.activeVersion}>View document</Link></div>) :
      <Feedback>No saved documents yet.</Feedback>}</Resource>
  </>
}

export function Logs() {
  const logs = useResource('/admin/audit')
  return <>
    <PageTitle label="Operations" title="Audit history" action={<button className="button subtle" onClick={logs.reload}><RefreshCw size={15}/> Refresh</button>}>
      View recorded system events and restricted lookups.
    </PageTitle>
    <Resource resource={logs}>{rows => rows.length ? <ul className="panel logs">{rows.map(row => <li key={row._id}>
      <span>{stamp(row.createdAt)}</span><strong>{row.action}</strong><p>{row.actor} · {row.target}</p></li>)}</ul> :
      <Feedback>No audit events yet.</Feedback>}</Resource>
  </>
}

export function Users() {
  const users = useResource('/admin/users')
  return <>
    <PageTitle label="Operations" title="Accounts">CampusIQ roles are managed by an authorized local operator.</PageTitle>
    <Resource resource={users}>{rows => rows.length ? rows.map(user => <article className="document" key={user._id}>
      <span className="status">{user.role}</span><div><h3>{user.name || user.email || 'Account'}</h3><p>{user.email} · {user._id}</p></div></article>) :
      <Feedback>No accounts yet.</Feedback>}</Resource>
  </>
}
