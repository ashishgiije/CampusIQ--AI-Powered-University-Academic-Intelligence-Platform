# CampusIQ API contracts

Express returns JSON except for the administrator PDF download. Authenticated requests send `Authorization: Bearer <Firebase ID token>`. Collection endpoints have bounded newest-first results. IDs are lower-case 24-character MongoDB ObjectId strings, except Firebase UIDs.

## Account and student APIs

- `GET /health` checks MongoDB connectivity.
- `GET /api/me` returns the Firebase-linked CampusIQ account and backend role.
- `PUT /api/me/profile` accepts `programme`, `year`, `semester`, `branch`, `pattern` as strings.
- `GET /api/documents` accepts `q`, `category`, `year`, `programme`, `semester`, `session`. Returns active saved versions with academic metadata and official links.
- `GET /api/notifications` returns relevant active publication updates.
- `GET /api/chats` returns the caller's active conversations.
- `DELETE /api/chats/:chatId` deletes the owned conversation and messages, cancels queued work and prevents a running worker from recreating deleted messages. Returns HTTP 204. Shared academic documents stay available.
- `POST /api/chats` accepts `{ "title": "Exam documents" }`.
- `GET /api/chats/:chatId/messages` returns owned messages. Answers whose still-stored versions have been superseded or withdrawn are hidden from the conversation's current view.
- `POST /api/chats/:chatId/messages` accepts `{ "text": "What is the latest examination circular?" }` and returns HTTP 202 with a job ID, status and stage. A student can have one search in progress.
- `GET /api/chats/:chatId/work` returns the caller's latest search progress in that chat. After completion, fetch the assistant turn from the messages endpoint. It includes `text`, `status`, structured `intent`, `citations`, `search` diagnostics and `inspectedSources`. Citations carry `title`, `url`, `page`, `versionId`, `ocr` and `restricted`.

## Administrator APIs

These read-only endpoints require the CampusIQ admin role.

- `GET /api/admin/overview`, `GET /api/admin/monitor` show document counts and service health, including the running worker version.
- `GET /api/admin/sources` shows configured official source sections.
- `GET /api/admin/jobs`, `GET /api/admin/jobs/:id` show search progress, crawler mode, visited pages and processing failures.
- `GET /api/admin/versions`, `GET /api/admin/versions/:id?page=1` show discovered documents, extraction evidence and warnings.
- `GET /api/admin/versions/:id/pdf` streams the stored PDF through an authenticated route.
- `POST /api/admin/versions/:id/exact` performs an audit-logged read for a synthetic or authorized identifier within one version.
- `GET /api/admin/audit`, `GET /api/admin/users` show audit history and account overviews.

Source mutation, manual crawl creation, document approval, rejection, revocation and reprocessing endpoints have been removed. Saved content is indexed by the automatic discovery worker.

## Internal Python API and worker contracts

FastAPI binds to loopback for local development. Express sends `X-Internal-Secret` on each internal request.

- `GET /internal/status` checks database connectivity and worker heartbeat and reports whether Gemini configuration is present.
- `POST /internal/answer` accepts `{ "question": "...", "context": { "programme": "mca" } }` and returns answered, unavailable or abstained text with intent and citations.
- `POST /internal/exact` accepts `version` and `identifier`. Express controls administrator access, per-version scope, audit and rate limits before proxying.
- `GET /internal/pdf/:versionId` reads the document-store file by digest, after validating the requested version.

The durable MongoDB queue is the asynchronous Python service contract. Student questions trigger saved-document lookup, conservative query normalization, Gemini link ranking and bounded official website discovery. Extracted content is saved and indexed automatically. Only metadata summaries of restricted public disciplinary publications enter student retrieval. The worker owns the lease and status transitions. Responses report the search method, Gemini failures and inspected sources.
