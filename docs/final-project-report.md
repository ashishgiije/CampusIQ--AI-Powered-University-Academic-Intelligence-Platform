# CampusIQ — Final Technical Project Report

## 1. Executive summary

CampusIQ is a locally runnable SPPU (Savitribai Phule Pune University) academic-intelligence platform. A student asks a natural-language question, the system identifies the academic intent, searches previously saved official documents, and—when evidence is missing—performs a bounded crawl of configured SPPU pages. PDF/HTML content is extracted page by page, OCR is used for scanned pages, metadata and relevance are validated, and the resulting evidence is stored and indexed. A retrieval-augmented generation (RAG) layer answers from the evidence and returns the official URL and page citation.

The current product follows an automatic-discovery model. Documents discovered during a valid student search can be saved and indexed automatically. The administrator workspace is read-only for monitoring documents, users, jobs, evidence, warnings and service health; it does not contain approve/reject controls. Public academic information is searchable, while sensitive individual disciplinary records remain restricted.

## 2. Problem statement and solution

SPPU academic information is distributed across examination pages, HTML listings, legacy SharePoint libraries and PDFs. Students use incomplete, misspelled or informal questions, while the relevant document may be buried in a listing or be a scanned PDF. Keyword search has difficulty preserving programme, branch, semester, pattern, exam type, session and revision constraints. A general-purpose LLM can also invent dates or cite documents that were never inspected.

CampusIQ combines deterministic intent parsing, optional Gemini query rewriting, safe official-source crawling, document extraction/OCR, strict scope validation, exact identifier matching, hybrid retrieval and source-grounded generation. Every factual answer is tied to stored SPPU evidence, or the system explicitly reports that it could not verify the answer.

It supports examination timetables, examination circulars, public Unfair Means/copy-case punishment publications, syllabi, academic calendars, university announcements and other public academic documents.

## 3. End-to-end workflow

```text
Student question
    -> Firebase-authenticated React client
    -> Express API and durable MongoDB chat job
    -> Python worker
    -> deterministic intent parser
    -> Gemini rewrite/ranking when useful
    -> saved-document lookup
    -> bounded official SPPU crawl if evidence is missing
    -> PDF/HTML extraction and OCR
    -> relevance, metadata, privacy and revision validation
    -> MongoDB metadata/pages + local document blob
    -> BAAI embeddings in Qdrant
    -> lexical/exact/semantic retrieval and reranking
    -> grounded Gemini answer or explicit abstention
    -> page citations, official links and inspected-source diagnostics
```

1. The user signs in and submits a question in the React chat.
2. Express verifies the Firebase ID token and creates an owner-scoped chat message and background answer job.
3. The intent parser preserves the original wording and extracts category, institution, programme, branch, study year, semester, examination type, session, academic year, pattern, dates, identifiers, latest/revised flags and ambiguity.
4. Gemini may rewrite a typo-filled or underspecified search objective. The rewrite is constrained by the original intent.
5. The worker first searches active saved publications and exact page identifiers.
6. If saved evidence is insufficient, the crawler searches enabled official SPPU source records with bounded depth, page, document, timeout and retry limits.
7. Each candidate is fetched only after host, DNS, redirect, robots and public-network checks.
8. HTML tables are converted to text rows. PDFs use native extraction first and Tesseract OCR when native text is insufficient.
9. Validation checks document category, programme, semester, branch, pattern, exam type, session, dates, revision state, readability and exact requested identifiers.
10. Valid official evidence is stored. A SHA-256 content hash identifies the binary and supports duplicate/revision detection.
11. Retrieval combines exact identifiers, MongoDB lexical matching, Qdrant dense similarity and cross-encoder reranking when model resources are available.
12. Gemini receives selected retrieved evidence. Citation quotes are checked against the source page before return.
13. The answer, intent, rewritten query, search method, citations and diagnostics are stored in chat history. Students can delete their own conversations.

## 4. Repository modules

### `frontend/`

React/Vite/Tailwind application. `auth.jsx` implements Firebase login, email/password, password reset and Google sign-in when enabled. `student.jsx` implements chat polling, citations, document links, source-inspection details, history and chat deletion. `admin.jsx` provides read-only monitoring views. `shared.jsx` and `main.jsx` provide common API/auth/layout behavior.

### `backend/src/`

- `server.js`: Express process startup.
- `app.js`: REST routes for identity, profiles, documents, chats, notifications and read-only administration.
- `auth.js`: Firebase token verification, user provisioning and role enforcement.
- `firebase.js`: Firebase Admin SDK initialization.
- `db.js`: MongoDB connection, collection indexes, validators and default SPPU source registry.
- `provision.js`: trusted command-line grant/revoke of administrator role by Firebase UID.

Express is the public application boundary. It owns Firebase verification, user/chat ownership and calls the private AI service using the internal shared secret.

### `ai-service/`

- `main.py`: FastAPI health, question, exact-lookup and PDF endpoints.
- `worker.py`: durable MongoDB job worker, lease/heartbeat, crawl orchestration, extraction, publication/index synchronization and answer persistence.
- `rag.py`: chunking, embeddings, Qdrant indexing, lexical retrieval, exact lookup, reranking, citation verification, timetable rendering and grounded answer assembly.
- `gemini.py`: Gemini REST calls for generation, intent rewrite, candidate-link ranking and failure classification.
- `config.py`: AI-service database, storage and internal-secret configuration.

The FastAPI process handles internal requests; the worker handles slow crawling, OCR and model/index operations.

### `crawler/`

- `navigation.py`: safe HTTP client, robots handling, URL canonicalization, link/context extraction, SharePoint expansion, pagination, candidate ranking and bounded crawl loop.
- `intent.py`: deterministic academic intent grammar, aliases, dates, identifiers, branch-section extraction and metadata validation.
- `extraction.py`: HTML extraction, native PDF extraction, table preservation and OCR fallback.

### `tests/`

Offline crawler/intent/OCR tests, MongoDB/Qdrant service integration tests, backend route tests, live SPPU opt-in tests, live answer tests and browser smoke tests. `evaluation.json` contains deterministic intent cases.

## 5. How modules relate

The React client never accesses MongoDB, Qdrant or Gemini directly. It sends Firebase-authenticated requests to Express. Express authorizes the request and persists chat/job state in MongoDB. The Python worker consumes that job, uses the shared crawler and intent modules, writes document data to MongoDB/local storage, indexes active content through `rag.py` into Qdrant, and writes the final answer back to MongoDB. Express exposes the stored result to React. This keeps credentials and heavy processing out of the browser and keeps crawling/OCR outside the request lifetime.

## 6. Authentication and authorization

Firebase Authentication provides email/password, password reset and optional Google sign-in. The browser sends a Firebase ID token as a Bearer token. Firebase Admin SDK in Express verifies the token, rejects expired/malformed tokens and creates a separate CampusIQ user profile keyed by Firebase UID.

Roles are stored in MongoDB. New users default to `student`. The frontend cannot assign itself `admin`; an authorized operator runs `npm.cmd run admin -- "FIREBASE_UID" grant` from the trusted backend environment. `adminOnly` middleware enforces administrator routes. Chat, messages and deletion are owner-scoped. FastAPI endpoints require `INTERNAL_SECRET` and are not public student endpoints.

## 7. API keys and secrets

Secrets are environment variables and are excluded by `.gitignore`:

- `GEMINI_API_KEY` and `GEMINI_MODEL`: Gemini generation, rewriting and link ranking.
- `GOOGLE_APPLICATION_CREDENTIALS` and `FIREBASE_PROJECT_ID`: Firebase Admin verification; the service-account JSON stays outside the repository.
- `INTERNAL_SECRET`: random Express-to-FastAPI service secret.
- `MONGO_URI`/`MONGO_DB`: MongoDB connection.
- `QDRANT_URL`/`QDRANT_API_KEY`: vector service endpoint/key.
- `TESSERACT_CMD`/`OCR_LANG`: OCR executable and installed languages.
- `VITE_FIREBASE_*`, `VITE_API_URL`, `VITE_GOOGLE_SIGN_IN`: browser-safe Firebase web configuration and API origin.

Gemini is optional for crawling and deterministic parsing. If it fails, the worker reports a Gemini fallback/rule-based method and continues where deterministic search is sufficient.

## 8. Web-crawling algorithm

The crawler is an adapted and hardened version of the supplied CampusIQ v0.6 crawler. It uses a priority-guided, bounded best-first search rather than unrestricted site crawling.

1. The source registry supplies an approved SPPU listing URL, category and limits.
2. The goal is converted into intent constraints and search terms.
3. The initial page is fetched with Requests. Robots rules and redirects are evaluated.
4. URLs are canonicalized: fragments/tracking parameters are removed and credentials, nonstandard ports and unsafe hosts are rejected.
5. DNS results are checked to prevent loopback, link-local, private-network and metadata-service access. Redirect destinations must remain on approved public hosts.
6. Links are extracted with anchor text, table-row context, headings and listing labels. PDF candidates receive priority; pagination and SharePoint expansion links are retained.
7. Candidate scores combine category terms, programme/branch/session/year evidence, source context, date recency, PDF status, depth and Gemini link ranking when configured.
8. A priority queue processes the highest-scoring candidates first. Page/document/depth/timeout/Gemini-call budgets bound the crawl.
9. Playwright is used for dynamic SharePoint/group expansion when ordinary HTML does not expose document links.
10. Each downloaded document is hashed, extracted and validated. Duplicate hashes are skipped. A changed hash becomes a new version in the same document family when provenance/scope indicates a revision.
11. Crawl events retain listing URL, candidate URL, HTTP outcome, extraction result, warnings and errors for administrator inspection.

This is useful because SPPU pages contain mixed categories and legacy libraries. Context-aware scoring and mandatory validation reduce false positives, while limits and host guards prevent runaway crawling and SSRF-style requests.

## 9. RAG implementation

The RAG system is evidence-first:

- Page text is normalized and split into structure-aware chunks.
- BAAI embeddings are generated using the EduMind-derived embedding pattern.
- Vectors are stored in the dedicated `campusiq_chunks` Qdrant collection with document/version/page metadata.
- MongoDB pages provide lexical and exact matching fallback.
- Exact seat/case/circular/course identifiers are matched against native text; OCR-only identifiers are flagged for visual verification.
- A MiniLM cross-encoder reranks candidate passages when available.
- Active document/version filters prevent superseded or revoked content from being retrieved.
- Gemini receives retrieved evidence and returns answer text plus evidence indexes/quotes.
- Citation validation checks that every returned quote occurs in the cited page. Prompt-injection text inside a source is treated as data, not an instruction.
- If no adequate evidence exists, the system abstains instead of answering from general model knowledge.

## 10. Databases and storage

### MongoDB

MongoDB is the operational database. Collections include `users`, `sources`, `jobs`, `runtime`, `documents`, `versions`, `pages`, `reviews`, `chats`, `messages`, `notifications`, `audit` and discovery/runtime records. Indexes support owner-scoped chat access, active document lookup, URL/hash deduplication, job leasing and metadata filtering.

### Qdrant

Qdrant is the vector database. The CampusIQ collection is `campusiq_chunks`. Payloads retain MongoDB document/version IDs and page metadata so vector hits can be revalidated against the current active version.

### Local document store

Downloaded PDF/HTML binaries are stored outside normal MongoDB documents using SHA-256 filenames. MongoDB stores metadata and extracted pages; it does not need to contain every binary blob.

### Current Windows locations

Project source: `C:\Users\ashish\myproj\CampusIQ\campusiq`

Configured native local data:

- MongoDB: `D:\CampusIQ-data\mongo-native`
- Qdrant: `D:\CampusIQ-data\qdrant`
- Downloaded documents/storage: `D:\CampusIQ-data\...` according to the active environment
- Service logs: `D:\CampusIQ-data\logs`

The Compose alternative uses MongoDB on port `27017` and Qdrant on `6333`. The current native Windows setup uses MongoDB on port `27018` to avoid conflict with an existing service and Qdrant on `6333`. Keep `MONGO_URI`, `MONGO_DB`, `QDRANT_URL`, `AI_URL` and `VITE_API_URL` consistent across services.

## 11. Technology stack and important libraries

| Area | Technology/library | Purpose |
|---|---|---|
| UI | React, Vite, Tailwind CSS | Student/admin web application |
| Public API | Node.js, Express | Authenticated REST boundary and chat/job APIs |
| Identity | Firebase Auth, Firebase Admin SDK | Sign-in, token verification and identity |
| AI API | Python, FastAPI, Uvicorn | Private AI/document endpoints |
| Jobs | Python worker + MongoDB lease | Durable asynchronous crawl/OCR/answer work |
| Database | MongoDB, PyMongo, MongoDB Node driver | Profiles, jobs, documents, pages, chats and audit |
| Vectors | Qdrant client/server | Semantic chunk retrieval |
| Embeddings | BAAI embedding model | Dense document/query vectors |
| Reranking | Cross-encoder MiniLM | Passage relevance reranking |
| LLM | Gemini REST `generateContent` | Rewrite, link ranking and grounded response |
| Crawling | Requests, BeautifulSoup, Playwright | Static pages, tables, SharePoint and pagination |
| PDF | PyMuPDF, pypdf | Native extraction, page count and validation |
| OCR | Tesseract, pytesseract, Pillow | Scanned PDF fallback, English/Marathi if installed |
| Testing | Python unittest, Node test runner, browser scripts | Regression, integration and UI checks |

## 12. Installation and packages

Required software:

- Windows PowerShell
- Node.js 22.12+ and npm
- Python 3.10 or 3.11 x64
- MongoDB native or Docker Compose
- Qdrant native executable or Docker Compose
- Tesseract 5; Marathi trained data is optional
- Playwright Chromium
- Firebase project and Admin service-account file
- Gemini API key for model-assisted rewriting/generation

Install from the project root:

```powershell
Copy-Item backend/.env.example backend/.env
Copy-Item ai-service/.env.example ai-service/.env
Copy-Item frontend/.env.example frontend/.env
npm.cmd --prefix backend ci
npm.cmd --prefix frontend ci
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -r .\ai-service\requirements.txt
& .\.venv\Scripts\python.exe -m playwright install chromium
```

Normal local startup:

```powershell
Set-Location 'C:\Users\ashish\myproj\CampusIQ\campusiq'
powershell -ExecutionPolicy Bypass -File .\start-local.ps1 -Restart
```

## 13. What is used and what is deliberately not used

Used:

- Official SPPU source registry and automatic discovery
- Gemini with deterministic fallback
- MongoDB and Qdrant
- Firebase authentication
- Native PDF extraction and OCR fallback
- Page-level citations and source URLs
- Exact identifier matching plus semantic retrieval
- Asynchronous worker jobs
- Read-only administrator monitoring
- Student-owned chat deletion

Not used in the current product:

- Personal document-upload study chat
- General internet crawling outside approved SPPU hosts
- Frontend-controlled administrator privileges
- Hardcoded individual PDF URLs as the discovery mechanism
- Redis/Celery; MongoDB jobs and leases are used instead
- PostgreSQL/SQL as the application database
- OpenAI API; Gemini is the configured LLM
- Automatic publication of private individual disciplinary records
- GitHub as a runtime host for MongoDB, Qdrant, FastAPI or the worker
- A mandatory human approve/reject gate; this was removed from the current workflow

## 14. Reference projects used

### CampusIQ Onboarding v0.6

This supplied the working foundation for Requests/BeautifulSoup crawling, Playwright/SharePoint expansion, PDF downloading, PyMuPDF/pypdf extraction, Tesseract fallback, relevance validation, page indexing, exact lookup and evidence reporting. Its patterns were adapted and security-hardened in `crawler/` and `ai-service/worker.py`; the original reference source was not modified.

### EduMind AI

This supplied patterns for Firebase authentication, FastAPI organization, BAAI embeddings, Qdrant retrieval, lexical/BM25 fallback, MiniLM reranking, Gemini generation and source-grounded answers. The exported reference contained compiled/application artifacts and manifests rather than a complete editable source tree, so CampusIQ implements compatible patterns independently and keeps its database and credentials separate.

## 15. Successful functionality

- React student and read-only administrator interfaces
- Firebase email/password and optional Google authentication
- Backend token verification and backend-controlled roles
- MongoDB initialization, indexes and source registry
- Qdrant collection/index synchronization
- Automatic question-triggered SPPU discovery
- Static HTML, table and dynamic SharePoint link discovery
- PDF validity checks, native extraction and OCR fallback
- Strict category/programme/session/branch/year/pattern validation
- Branch-section filtering for engineering timetables
- Duplicate hash and revision-aware version handling
- Automatic saving and indexing of valid official documents
- Hybrid semantic, lexical and exact retrieval
- Gemini rewrite, candidate ranking and grounded answer generation
- Citation quote validation and page/URL citations
- Explicit abstention/inspected-source diagnostics when evidence is missing
- Sensitive punishment/case privacy controls
- Chat ownership checks and student chat deletion
- Durable worker leases, heartbeats and retry-friendly processing
- Backend, crawler, RAG, OCR, browser and integration test coverage

The repository is available at [CampusIQ on GitHub](https://github.com/ashishgiije/CampusIQ--AI-Powered-University-Academic-Intelligence-Platform).

## 16. Known limitations and errors

1. **External availability:** SPPU pages, legacy SharePoint libraries, DNS, robots rules and network timeouts can change. A healthy local service does not guarantee that a particular listing is reachable.
2. **Gemini configuration:** Missing/invalid key or unsupported model causes rewrite/generation fallback. Deterministic search still works for supported patterns, but ambiguous questions may need clarification.
3. **OCR uncertainty:** OCR numeric values are marked for visual verification. Poor scans, missing Tesseract languages or a missing executable path can produce an unverified answer.
4. **Model downloads and disk space:** BAAI and MiniLM files download on first use. Insufficient disk space can prevent model loading or Qdrant collection creation.
5. **Incomplete metadata:** Some PDFs do not state programme, pattern, session or publication date clearly. CampusIQ abstains rather than claiming that such a document is latest.
6. **Ambiguous questions:** A question mixing multiple branches, sessions or academic years is not silently broadened; it may receive clarification or an unverified result.
7. **Legacy HTTP links:** Some official SPPU timetable PDFs use legacy HTTP SharePoint links. They are accepted only when reached from an HTTPS official SPPU portal and kept inside the verified timetable library; the answer identifies the legacy link.
8. **Sensitive disciplinary content:** Public publication-level information can be indexed, but individual records and OCR-derived identifiers remain restricted or require stronger verification.
9. **Local-only deployment:** Production deployment still needs managed MongoDB/Qdrant, secret management, HTTPS, process supervision and monitoring.

## 17. Verification and test commands

```powershell
npm.cmd --prefix backend test
npm.cmd --prefix frontend run build
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Live SPPU and live-answer tests are opt-in because they depend on external network access and configured credentials. The deterministic suite covers crawler safety, SharePoint extraction, table parsing, PDF/OCR extraction, relevance constraints, branch filtering, exact identifiers, role separation, read-only administration, chat deletion, automatic discovery, retrieval fallbacks, citation validation, prompt-injection resistance, revision replacement and RAG abstention.

## 18. Handoff checklist

1. Read this report, `README.md`, `docs/design.md` and `docs/api.md` first.
2. Inspect `.env.example` files; never infer secrets from source code.
3. Start MongoDB and Qdrant before Express, FastAPI, worker and frontend.
4. Confirm `/health` for Express and FastAPI and check worker heartbeat.
5. Test a saved-document timetable question before a live crawl question.
6. Check the chat `search.method`, `inspectedSources`, citations and page numbers when debugging.
7. Use offline tests before enabling live SPPU tests.
8. Keep crawler changes bounded by host allowlists, redirect checks, limits and robots behavior.
9. Preserve original question constraints when changing Gemini rewriting or retrieval.
10. Never expose Firebase Admin credentials, Gemini keys, internal secrets, database passwords or private document storage.


