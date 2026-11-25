# CampusIQ

CampusIQ answers questions about public SPPU academic information. It checks saved documents first, uses Gemini to refine a search when needed, and crawls official SPPU pages for additional evidence. The worker saves validated publications for future questions and returns official URLs and page citations.

## Start this Windows installation

CampusIQ now uses a dedicated MongoDB database under `D:/CampusIQ-data/mongo-native` on port 27018. Its collections were copied and verified from the previous local instance. Both server env files point to that port. Qdrant and downloaded documents also use `D:/CampusIQ-data/`.

Run these commands in PowerShell after configuring Firebase and Gemini.

```powershell
Set-Location 'C:\Users\ashish\myproj\CampusIQ\campusiq'
powershell -ExecutionPolicy Bypass -File .\start-local.ps1 -Restart
```

The script starts native Windows services and keeps logs under `D:/CampusIQ-data/logs`. Open [CampusIQ](http://localhost:5173). Use the same command after code changes to restart the app processes.

## Windows setup

Use PowerShell and keep the long-running services in separate tabs. The example paths match this workspace.

### 1. Install prerequisites

- **Node.js 22.12 or newer** with npm. Use `npm.cmd` in PowerShell if execution policy blocks `npm.ps1`. [Node.js downloads](https://nodejs.org/en/download)
- **Python 3.10 or 3.11 x64**. Install Python with the PATH option and check `python --version`. Only one selected interpreter is needed. [Python for Windows](https://www.python.org/downloads/windows/)
- **Docker Desktop with Compose v2**, or native MongoDB 8 and Qdrant 1.18. The Compose ports are bound to loopback. [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/), [MongoDB Windows install](https://www.mongodb.com/docs/manual/tutorial/install-mongodb-on-windows/), [Qdrant releases](https://github.com/qdrant/qdrant/releases)
- **Tesseract 5** for scanned documents. Install English and optionally Marathi. Add `mar.traineddata` to the installation's `tessdata` folder if it is absent. [Windows installer guidance](https://github.com/UB-Mannheim/Tesseract_Dokumentation/blob/main/Tesseract_Doku_Windows.md), [Marathi trained data](https://github.com/tesseract-ocr/tessdata_fast/blob/main/mar.traineddata)

```powershell
Set-Location 'C:\Users\ashish\myproj\CampusIQ\campusiq'
node --version
npm.cmd --version
python --version
docker compose version
& 'C:\Program Files\Tesseract-OCR\tesseract.exe' --list-langs
```

### 2. Install service dependencies

Run from the project root.

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

PowerShell activation is optional. The commands call the virtual environment's Python directly. On Windows install the [Microsoft Visual C++ x64 runtime](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) if PyTorch fails with a missing DLL. BAAI CPU model files download on first use and can be warmed up in advance.

### 3. Start MongoDB and Qdrant

From `campusiq`, run:

```powershell
docker compose up -d
docker compose ps
Test-NetConnection 127.0.0.1 -Port 27017
Invoke-RestMethod http://127.0.0.1:6333/collections
```

The default database is `campusiq` at `mongodb://127.0.0.1:27017`. Express initializes collections, validators, indexes and SPPU sources during startup. The worker creates `campusiq_chunks` when first indexing a reviewed version. Compose preserves database files in volumes. Use `docker compose stop` to stop the services.

With native software, start the local MongoDB Windows service using the installer configuration or run the following in one tab. Use either Compose or the native processes on the same ports.

```powershell
Set-Location 'C:\Users\ashish\myproj\CampusIQ\campusiq'
$mongoData = (New-Item -ItemType Directory -Force ./var/mongo).FullName
mongod.exe --dbpath $mongoData --bind_ip 127.0.0.1 --port 27017
```

Extract the official Windows x64 Qdrant ZIP for v1.18.0 to `campusiq/var/qdrant`, then run in another tab:

```powershell
Set-Location 'C:\Users\ashish\myproj\CampusIQ\campusiq\var\qdrant'
$env:QDRANT__SERVICE__HOST = '127.0.0.1'
$env:QDRANT__TELEMETRY_DISABLED = 'true'
.\qdrant.exe
```

### 4. Configure Firebase and Gemini

1. In Firebase Console, open the Firebase project used by EduMind if existing accounts should also work here. The Firebase web app config in the reference export is `refereance/edumind-ai (2)/firebase-applet-config.json`. Use the project's authorized web config from the console. Set the four `VITE_FIREBASE_*` variables in `frontend/.env`. Firebase web config identifies the project. Keep Admin credentials in the backend only. [Register a Firebase web app](https://firebase.google.com/docs/web/setup)
2. Enable **Email/Password** under Authentication → Sign-in method and add `localhost` under Authentication → Settings → Authorized domains. If Google sign-in is enabled in that project, set `VITE_GOOGLE_SIGN_IN=true`. CampusIQ profiles and roles stay in its own MongoDB database. [Password authentication](https://firebase.google.com/docs/auth/web/password-auth), [Google sign-in](https://firebase.google.com/docs/auth/web/google-signin)
3. Set `FIREBASE_PROJECT_ID` in `backend/.env` to the same project ID. Use Firebase Console → Project settings → Service accounts to generate a service-account file if your project permits it. Keep it outside the repository, for example under `C:/Users/ashish/campusiq-secrets/` in a folder only your Windows account can read. Set `GOOGLE_APPLICATION_CREDENTIALS=C:/Users/ashish/campusiq-secrets/service-account.json`. Firebase Admin needs permission to read Firebase users and check token revocation. Admin email, group or token claims never select a CampusIQ role. [Firebase Admin setup](https://firebase.google.com/docs/admin/setup), [Firebase ID token verification](https://firebase.google.com/docs/auth/admin/verify-id-tokens)
4. Create a Gemini API key in Google AI Studio. Set `GEMINI_API_KEY` and set `GEMINI_MODEL` to a model your key can use with `generateContent` and JSON responses. Enter the model ID without the `models/` prefix. Crawling and document review can run without Gemini. Chat displays an unavailable status until Gemini is configured. [Gemini keys](https://ai.google.dev/gemini-api/docs/api-key), [Generate content](https://ai.google.dev/api/generate-content)
5. Generate a random shared secret. Copy its value into both server `.env` files as `INTERNAL_SECRET`. Keep it out of Vite and out of source control.

```powershell
node -e "process.stdout.write(require('node:crypto').randomBytes(32).toString('hex'))"
```

6. In `ai-service/.env`, set `TESSERACT_CMD=C:/Program Files/Tesseract-OCR/tesseract.exe` if Tesseract is absent from PATH. Use `OCR_LANG=eng+mar` only if `--list-langs` reports both languages. Set `SPPU_SHAREPOINT_HOST` in both server env files only for a verified SPPU-owned tenant whose DNS name ends in `.sharepoint.com`. SPPU's SharePoint pages under `.unipune.ac.in` are already covered.

The templates list all variables. Keep both `MONGO_URI` and `MONGO_DB` settings aligned. If you use another port or host, update `AI_URL`, `QDRANT_URL`, `VITE_API_URL` and `WEB_ORIGIN` as applicable. Leave Vite on `http://localhost:5173` for the default authorized origin. Leave the Compose database ports on loopback.

### 5. Start CampusIQ

Open four PowerShell tabs. Start Express first so it initializes MongoDB.

**Express**

```powershell
Set-Location 'C:\Users\ashish\myproj\CampusIQ\campusiq\backend'
npm.cmd start
```

**FastAPI**

```powershell
Set-Location 'C:\Users\ashish\myproj\CampusIQ\campusiq\ai-service'
& ..\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
```

**Crawl and indexing worker**

```powershell
Set-Location 'C:\Users\ashish\myproj\CampusIQ\campusiq\ai-service'
& ..\.venv\Scripts\python.exe worker.py
```

**React**

```powershell
Set-Location 'C:\Users\ashish\myproj\CampusIQ\campusiq\frontend'
npm.cmd run dev
```

Open [CampusIQ on localhost](http://localhost:5173). To download and initialize the embedding and reranking models before the first search, run this optional command in the AI service folder:

```powershell
& ..\.venv\Scripts\python.exe -c "import config; from rag import encoder, reranker; encoder(); reranker()"
```

### 6. Ask a question and check the source

1. Sign in to CampusIQ and open **AI chat**. Try **“Which academic year does SPPU's tentative schedule of examinations cover for 2026-2027?”** or ask for your timetable with the programme, semester, pattern and exam session.
2. The chat shows progress while the worker checks saved documents and, if needed, searches the university website. Open a citation to check the official document and page. CampusIQ saves validated documents and their links. It periodically refreshes searches for the latest publication and reports limits on coverage. Each reply identifies saved-document retrieval, Gemini-assisted crawling, or rule-based fallback. Unanswered queries include the sources inspected.
3. Look in **Academic documents** for saved sources. The read-only admin workspace shows documents, users, discovery logs, extraction warnings and service health. Students can delete conversations with the trash button in chat history.

### 7. Optional administrator access

1. In Firebase Console → Authentication → Users, create or identify the authorized account and copy its **UID**. In `campusiq/backend`, run:

   ```powershell
   npm.cmd run admin -- "PASTE_FIREBASE_UID_HERE" grant
   ```

   Run the same command with `revoke` to restore the student role. This operation needs local access to trusted backend credentials and the MongoDB database. Sign out and back in if the account was already open in the browser.
2. Check **Overview → Service health**, **Search activity** and **Discovered documents**. The admin portal is read-only. Public punishment-list publication searches return official document links. Individual disciplinary lookups remain restricted.

## Tests

Run from `campusiq` after installing dependencies.

```powershell
npm.cmd --prefix backend test
npm.cmd --prefix frontend run build
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Run the real database integration tests against a **local development instance**. The tests use unique scratch databases and collections and remove them afterward. Model results in the integration test are deterministic fixtures. The suite also makes a local FastAPI request to check the internal authentication contract.

```powershell
$env:CAMPUSIQ_TEST_MONGO = 'mongodb://127.0.0.1:27018'
$env:CAMPUSIQ_TEST_QDRANT = 'http://127.0.0.1:6333'
$env:CAMPUSIQ_BROWSER_TEST = '1'
npm.cmd --prefix backend test
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
# Optional real BGE and MiniLM models in the database integration test.
$env:CAMPUSIQ_REAL_MODELS = '1'
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_services.py -v
Remove-Item Env:CAMPUSIQ_REAL_MODELS
# In another tab, first start the Vite dev server.
& .\.venv\Scripts\python.exe .\tests\browser_smoke.py
# Explicit opt-in to the live official listing check.
$env:CAMPUSIQ_LIVE_SPPU = '1'
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_offline.py -k live_sppu -v
# After configuring MongoDB, Qdrant, Gemini and the model cache, test a complete live question.
$env:CAMPUSIQ_LIVE_ANSWER = '1'
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_live_answer.py -v
# Optional current-term MCA timetable test against SPPU's legacy library.
$env:CAMPUSIQ_LIVE_MCA = '1'
& .\.venv\Scripts\python.exe -m unittest discover -s tests -p test_live_answer.py -k mca_timetable -v
```

To re-run the unmodified v0.6 tests from `campusiq`, set `$env:PYTHONDONTWRITEBYTECODE = '1'` and run:

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s '..\refereance\CampusIQ_Onboarding_v0_6\campusiq_onboarding_test' -p test_v06.py -v
```

## Troubleshooting

- **Firebase login or token errors**. Check that the web and Admin project IDs match, the credential file path exists, the sign-in method is enabled, and localhost is authorized. Check that the credential has Firebase Authentication permissions. If an account is disabled or its token is revoked, sign-in cannot grant CampusIQ access.
- **MongoDB / Qdrant connection refused**. Start the databases first and verify the ports. An existing Windows MongoDB service can occupy 27017. Use either the installed service or Compose, or configure a distinct Compose port in both backend env files.
- **Crawl queued indefinitely**. Start `worker.py`. The monitoring route reports worker heartbeat. After a crash another worker can claim the lease after roughly 45 seconds and retry running jobs.
- **Browser executable missing**. Run the Playwright install command with the same Python environment and `PLAYWRIGHT_BROWSERS_PATH` as the worker.
- **OCR failure**. Run Tesseract's `--list-langs` command and configure the exact executable path. PyMuPDF and pypdf process native-text PDFs without Tesseract.
- **Embeddings fail**. Warm the models up from a machine that can reach Hugging Face. Keep the inference version and model configuration identical in FastAPI and the worker. A Qdrant HTTP 500 during collection creation can indicate full disk space. If changing models, plan a separate collection and reindex active publications before switching the running services.
- **Crawler returns no candidates**. Inspect Job Log for robots, DNS or timeout failures. Try a bounded source-specific objective or a narrower verified section URL. Verify listing headings and dates in the browser. Endpoint health cannot guarantee an official section is reachable.
- **Frontend returns API errors**. Confirm Express is running with `Invoke-RestMethod http://127.0.0.1:4000/health`. Check `VITE_API_URL` and `WEB_ORIGIN`. Restart Vite after editing its env file.

## Verification in this workspace

- Live testing passed for the official SPPU academic schedule and the exact MCA second-year 2025-pattern winter 2026 timetable. It used the official listings and PDFs, configured Gemini API, BGE embeddings, MiniLM reranking, MongoDB and Qdrant. The first question saved the evidence and a repeat question reused it.
- The original crawler fixtures, Express route tests, frontend production build and desktop and mobile browser smoke tests also passed.
- OCR fallback was exercised with a deterministic fixture. The live test used native PDF text, and the browser smoke test covered public pages and protected-route redirects.

See [API contracts](docs/api.md) and [design and references](docs/design.md).
