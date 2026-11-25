import hmac
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from bson import ObjectId

from config import database, now, secret
from crawler.intent import exact
from gemini import configured
from rag import answer, vectors
from worker import blob_path

app = FastAPI(title="CampusIQ Internal API", docs_url=None, redoc_url=None, openapi_url=None)

def authenticate(x_internal_secret: Annotated[str, Header()] = ""):
    if not hmac.compare_digest(x_internal_secret.encode(), secret().encode()):
        raise HTTPException(401, "Internal access required")

secure = [Depends(authenticate)]

class Question(BaseModel):
    question: str = Field(min_length=3, max_length=1200)
    context: dict[str, str] = Field(default_factory=dict)

class Identifier(BaseModel):
    version: str = Field(pattern=r"^[a-f0-9]{24}$")
    identifier: str = Field(pattern=r"^[\w/-]{3,40}$")

@app.get("/internal/status", dependencies=secure)
def health():
    db = database()
    db.command("ping")
    state = db.runtime.find_one({"_id": "campusiq-worker", "heartbeat": {"$gte": now() - timedelta(seconds=45)}})
    try:
        vectors().get_collections()
        qdrant = True
    except Exception:
        qdrant = False
    return {"mongo": True, "worker": bool(state), "qdrant": qdrant, "geminiConfigured": configured(),
            "workerVersion": state.get("version") if state else None}

@app.post("/internal/answer", dependencies=secure)
def ask(payload: Question):
    return answer(database(), payload.question, payload.context)

@app.post("/internal/exact", dependencies=secure)
def lookup(payload: Identifier):
    version_id = ObjectId(payload.version)
    key = payload.identifier.upper()
    pages = database().pages.find({"versionId": version_id, "ocr": False, "identifiers": key}).limit(20)
    hits = []
    for page in pages:
        match = exact(page["text"], key)
        if match:
            hits.append({"page": page["number"], "excerpt": page["text"][max(0, match.start() - 70):match.end() + 70]})
    return {"hits": hits}

@app.get("/internal/pdf/{version_id}", dependencies=secure)
def pdf(version_id: str):
    if not ObjectId.is_valid(version_id):
        raise HTTPException(404)
    version = database().versions.find_one({"_id": ObjectId(version_id), "format": "pdf", "valid": True})
    if not version:
        raise HTTPException(404)
    path = blob_path(version["digest"], "pdf")
    if not path.is_file():
        raise HTTPException(404)
    return FileResponse(path, media_type="application/pdf", filename="campusiq-review.pdf",
                        headers={"Cache-Control": "no-store"})

