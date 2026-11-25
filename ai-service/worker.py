"""Durable crawl and review worker. Run separately from the HTTP API."""
from datetime import timedelta
from hashlib import sha256
import os
import re
from threading import Event, Thread
from time import sleep
from uuid import uuid4

from bson import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from config import database, now, store
from crawler.extraction import extract_html, extract_pdf
from crawler.intent import DATE, BRANCHES, parse_date, branch_section, fields, identities, interpret, metadata_matches, validate
from crawler.navigation import PublicClient, crawl, linked_timetable_library
from gemini import configured, rank_links, rewrite
from rag import active_cards, answer, index_version, question_gate, remove_version, result, words

LEASE = "campusiq-worker"
EXTRACTION_REVISION = 4
WORKER_VERSION = "2026-11-18-discovery-v4"

def blob_path(digest, kind):
    if not re.fullmatch("[a-f0-9]{64}", digest) or kind not in {"pdf", "html"}:
        raise ValueError("Invalid file reference")
    return store() / (digest + "." + kind)

def write_blob(digest, kind, data):
    path = blob_path(digest, kind)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        tmp = path.with_suffix("." + uuid4().hex + ".tmp")
        try:
            tmp.write_bytes(data)
            tmp.replace(path)
        finally:
            tmp.unlink(missing_ok=True)
    return path

def base_fields(version, pages, warnings, readable, validation, valid=True):
    return {
        "state": "pending" if readable and valid else "failed",
        "valid": valid, "readable": readable, "relevant": validation["relevant"],
        "restricted": validation["restricted"], "metadata": validation["metadata"],
        "validation": validation["evidence"], "reasons": validation["reasons"], "warnings": warnings,
        "pageCount": len(pages), "ocrPages": [p["number"] for p in pages if p["ocr"]],
        "readablePages": sum(len(p["text"].strip()) >= 45 for p in pages),
        "extractionRevision": EXTRACTION_REVISION,
        "processedAt": now()
    }

def process(db, version, data, mode="auto"):
    try:
        if version["category"] == "punishment":
            mode = "off"
        pages, warnings, readable = extract_pdf(data, mode) if version["format"] == "pdf" else extract_html(data)
        valid = True
    except Exception as error:
        pages, warnings, readable, valid = [], [f"Invalid document ({type(error).__name__})."], False, False
    validation = validate(version["title"], pages, version["context"], version["category"], version.get("goal", ""))
    summary_only = (version["category"] == "punishment" and valid and
                    bool(re.search(r"punishment\s*list", version["title"], re.I)) and
                    not re.search(r"notice.*meeting|show\s*cause", version["title"], re.I))
    if summary_only:
        validation["relevant"] = True
        validation["reasons"] = []
    db.pages.delete_many({"versionId": version["_id"]})
    if pages:
        db.pages.insert_many([
            {**page, "versionId": version["_id"], "identifiers": [] if page["ocr"] else
             sorted({value for _, value in identities(page["text"])})} for page in pages
        ])
    fields = base_fields(version, pages, warnings, readable, validation, valid)
    fields["summaryOnly"] = summary_only
    if summary_only:
        fields["state"] = "pending"
    db.versions.update_one({"_id": version["_id"]}, {"$set": fields})
    return fields

def consume(db, source, job, link, response, digest, kind, log):
    exact_doc = db.documents.find_one({"sourceUrl": response.url, "category": source["category"]})
    older = db.versions.find_one({"digest": digest, "category": source["category"], "state": {"$ne": "failed"}})
    if older:
        if older["url"] == response.url and link.get("legacyPortal") and not older.get("legacyPortal"):
            older["legacyPortal"] = link["legacyPortal"]
            db.versions.update_one({"_id": older["_id"]}, {"$set": {"legacyPortal": older["legacyPortal"]}})
        new_goal = job.get("goal", "")
        if older["state"] == "pending" and older["url"] == response.url and (
                older.get("extractionRevision") != EXTRACTION_REVISION or
                not older.get("relevant") and older.get("goal") != new_goal):
            # A narrow earlier crawl should not permanently lock a valid
            # publication out of the review queue for a different objective.
            fields = process(db, {**older, "goal": new_goal}, response.data)
            db.versions.update_one({"_id": older["_id"]}, {"$set": {"goal": new_goal}})
            log(fields["state"], "Revalidated existing content against the revised objective", response.url)
            return {**older, **fields}
        else:
            log("duplicate", "Identical content already catalogued", response.url)
        return older
    write_blob(digest, kind, response.data)
    if not exact_doc:
        doc_id = db.documents.insert_one({"createdAt": now(), "sourceUrl": response.url,
                                         "category": source["category"], "activeVersion": None}).inserted_id
    else:
        doc_id = exact_doc["_id"]
    version = db.versions.find_one({"documentId": doc_id, "digest": digest})
    if not version:
        version = {"_id": ObjectId(), "documentId": doc_id, "state": "failed", "createdAt": now(),
                   "digest": digest, "format": kind, "url": response.url, "listing": link["listing"],
                   "title": link["title"], "context": link["context"], "sourceId": source["_id"],
                   "jobId": job["_id"], "category": source["category"], "goal": job.get("goal", "")}
        if link.get("legacyPortal"):
            version["legacyPortal"] = link["legacyPortal"]
        group = (db.documents.find_one({"_id": exact_doc["canonicalDocumentId"]})
                 if exact_doc and exact_doc.get("canonicalDocumentId") else exact_doc)
        version["predecessor"] = group.get("activeVersion") if group else None
        db.versions.insert_one(version)
    fields = process(db, version, response.data)
    if fields["metadata"].get("revised") and not version.get("predecessor"):
        label = re.sub(r"\b(revised|corrected|corrigendum|amended)\b|\W", "", version["title"].casefold())
        if label:
            for doc in db.documents.find({"category": version["category"], "activeVersion": {"$type": "objectId"}}, {"public": 1, "activeVersion": 1}).limit(1000):
                former = re.sub(r"\b(revised|corrected|corrigendum|amended)\b|\W", "", doc["public"]["title"].casefold())
                if former == label:
                    db.versions.update_one({"_id": version["_id"]}, {"$set": {"suggestedPredecessor": doc["activeVersion"]}})
                    break
    db.documents.update_one({"_id": doc_id}, {"$set": {"revisionCount": db.versions.count_documents({"documentId": doc_id})}})
    log(fields["state"], "Relevant evidence found" if fields["relevant"] else "Review validation reasons", response.url)
    return {**version, **fields}

def publish_version(db, job, version, log):
    if not version.get("valid") or not (version.get("readable") or version.get("summaryOnly")) or not version.get("relevant") or not job["review"]["verified"]:
        raise ValueError("Verification checks failed. Reprocess before approving.")
    data = job["review"]
    vid = version["_id"]
    owner = db.documents.find_one({"_id": version["documentId"]})
    active_self = db.documents.find_one({"activeVersion": vid})
    replacement = ObjectId(data["replaces"]) if data.get("replaces") else job.get("expectedActive")
    if active_self:
        target = active_self
        replacement = target.get("previousVersion")
    else:
        if version["state"] != "pending":
            raise ValueError("Only a pending version can be approved.")
        previous_group = owner.get("canonicalDocumentId") or owner["_id"]
        target = (db.documents.find_one({"activeVersion": replacement}) if replacement else
                  db.documents.find_one({"_id": previous_group}))
        if not target or target.get("activeVersion") != replacement:
            raise ValueError("The selected previous version is no longer active.")
        if target["_id"] != owner["_id"] and owner.get("activeVersion"):
            raise ValueError("Revoke the other active publication before combining revisions.")
        if previous_group != owner["_id"] and target["_id"] != previous_group:
            raise ValueError("This source URL already belongs to another revision family.")
        if target["category"] != version["category"]:
            raise ValueError("A revision must belong to the same document category.")
        page = db.pages.find_one({"versionId": vid, "number": data["evidencePage"]})
        if not page or not (page["text"].strip() or version.get("summaryOnly")):
            raise ValueError("The selected evidence page contains no extracted text.")
        card = {**data["metadata"], "category": version["category"], "revised": bool(version["metadata"].get("revised") or replacement),
                "restricted": version["restricted"], "evidencePage": page["number"], "documentId": str(target["_id"]),
                "url": version["url"], "listingUrl": version.get("listing", version["url"]), "format": version["format"]}
        card["publicationMode"] = "automatic" if job["kind"] == "answer" else "reviewed"
        if version["restricted"] and (identities(card["title"]) or not card["title"].strip()):
            raise ValueError("Publish a general title without case or seat identifiers.")
        reviewed_scope = ("programme", "branch", "year", "studyYear", "semester", "session", "pattern", "examType", "published", "effective")
        if not data["notes"].strip() and any(card.get(key) != version["metadata"].get(key)
                for key in reviewed_scope if version["metadata"].get(key)):
            raise ValueError("Record a review note explaining changes to extracted scope or dates.")
        if replacement:
            previous = target["public"]
            for key in ("programme", "branch", "year", "studyYear", "semester", "session", "pattern", "examType"):
                if previous.get(key) and card.get(key) and previous[key] != card[key]:
                    raise ValueError(f"Revision and previous publication disagree on {key}.")
            if card["published"] and previous["published"] and card["published"] < previous["published"]:
                raise ValueError("A newer publication cannot be replaced with an older publication date.")
        log("index", "Building CampusIQ vectors before changing the active version", None)
        index_version(version, db, card)
        changed = db.documents.update_one({"_id": target["_id"], "activeVersion": replacement}, {"$set": {
            "activeVersion": vid, "public": card, "activatedAt": now(), "previousVersion": replacement
        }})
        if changed.modified_count != 1:
            raise ValueError("The active version changed. Reload the review and try again.")
    if target["_id"] != owner["_id"]:
        db.documents.update_one({"_id": owner["_id"]}, {"$set": {"canonicalDocumentId": target["_id"]}})
    db.versions.update_one({"_id": vid}, {"$set": {"state": "approved"}, "$unset": {"needsVectorCleanup": "", "supersededBy": ""}})
    db.notifications.update_one({"_id": vid}, {"$setOnInsert": {"versionId": vid, "createdAt": now()}}, upsert=True)
    if replacement:
        db.versions.update_one({"_id": replacement}, {"$set": {"supersededBy": vid}})
        cleanup_version(db, replacement, log)

def cleanup_version(db, version_id, log):
    db.versions.update_one({"_id": version_id}, {"$set": {"needsVectorCleanup": True}})
    try:
        remove_version(version_id)
    except Exception:
        log("cleanup", "Vector cleanup delayed. The inactive version is excluded from retrieval.", None)
    else:
        db.versions.update_one({"_id": version_id}, {"$unset": {"needsVectorCleanup": ""}})

def claim_worker(db, owner):
    try:
        return db.runtime.find_one_and_update({"_id": LEASE, "$or": [
            {"expires": {"$lt": now()}}, {"owner": owner}
        ]}, {"$set": {"owner": owner, "expires": now() + timedelta(seconds=45), "heartbeat": now(), "version": WORKER_VERSION}},
            upsert=True, return_document=ReturnDocument.AFTER)
    except DuplicateKeyError:
        return None

def heartbeat(db, owner, done):
    while not done.wait(10):
        try:
            if claim_worker(db, owner):
                continue
        except Exception:
            pass
        # Abort if the worker cannot prove exclusive ownership.
        os._exit(2)

def save_official_version(db, job, version, intent, log):
    if not version or version["state"] != "pending" or version.get("revokedAt"):
        return False
    if version.get("restricted") and version["category"] != "punishment":
        log("excluded", "Document contains restricted content", version["url"])
        return False
    secure_origin = version["url"].startswith("https://")
    linked_legacy = version["category"] == "timetable" and linked_timetable_library(
        version.get("legacyPortal", ""), version["listing"], version["url"])
    if not version.get("valid") or not (version.get("readable") or version.get("summaryOnly")) or not version.get("relevant") or not (secure_origin or linked_legacy):
        log("excluded", "Document failed official URL, category or readability checks", version["url"])
        return False
    # Confirm the document itself identifies the university. Listing titles
    # and the allowlisted download URL alone cannot establish provenance.
    heading = version["validation"]["heading"]
    if version["category"] != "punishment" and (version.get("ocrPages") or version.get("readablePages") != version.get("pageCount")):
        log("excluded", "One or more pages require extraction review", version["url"])
        return False
    if version["category"] != "punishment" and not re.search(r"\b(?:(?:savitribai\s+phule\s+)?pune\s+university|university\s+of\s+pune)\b|सावित्रीबाई\s+फुले\s+पुणे\s+विद्यापीठ", heading, re.I):
        log("excluded", "Official issuer not established in extracted heading", version["url"])
        return False
    extracted = fields(heading)
    metadata = {key: "" for key in ("programme", "branch", "semester", "studyYear", "examType", "session", "year", "pattern")}
    metadata.update({key: val for key, val in extracted.items() if key in metadata})
    if version["category"] == "timetable" and metadata.get("programme") == "engineering":
        pages = list(db.pages.find({"versionId": version["_id"]}, {"text": 1}))
        metadata["branches"] = [branch for branch in BRANCHES
                                if any(branch_section(page["text"], branch) for page in pages)]
        if metadata["branches"]:
            metadata["branch"] = metadata["branches"][0] if len(metadata["branches"]) == 1 else ""
    metadata.update({key: version["metadata"].get(key, "") for key in ("title", "published", "effective")})
    if version["category"] == "punishment":
        dates = [parse_date(value) for value in re.findall(DATE, version["title"] + " " + version["context"], re.I)]
        metadata["sourceDate"] = max((value for value in dates if value), default="")
    metadata.update(category=version["category"], revised=bool(version["metadata"].get("revised")),
                    legacyTransport=not secure_origin,
                    tentative=bool(re.search(r"\b(?:tentative|provisional)\b", heading, re.I)))
    if not metadata_matches(metadata, intent):
        log("excluded", "Document metadata does not match the question scope", version["url"])
        return False
    owner = db.documents.find_one({"_id": version["documentId"]})
    target = db.documents.find_one({"_id": owner["canonicalDocumentId"]}) if owner.get("canonicalDocumentId") else owner
    prior = target.get("activeVersion")
    publish = {**job, "expectedActive": prior,
               "review": {"verified": True, "metadata": metadata, "evidencePage": 1,
                          "notes": "Checked official source provenance, document issuer and academic scope."}}
    publish_version(db, publish, version, log)
    log("saved", "Validated official document indexed for CampusIQ", version["url"])
    return True

def search_answer(db, job, log, inspected):
    question = job["question"]
    context = job.get("context", {})
    intent = interpret(question)
    blocked = question_gate(intent)
    if blocked:
        return blocked
    log("cache", "Checking saved official sources")
    if intent["constraints"].get("category"):
        cached = answer(db, question, context, intent)
        if cached["status"] == "clarify" and cached["citations"]:
            return cached
        if cached["status"] == "answered" and (not intent["latest"] or recent_lookup(db, intent)):
            return cached
    else:
        cached = None
    log("rewrite", "Refining the academic search")
    intent = rewrite(intent, report=log)
    blocked = question_gate(intent)
    if blocked:
        return blocked
    category = intent["constraints"].get("category")
    if not category:
        category = "document"
        intent["constraints"]["category"] = category
    # Reconsider downloaded candidates using current extraction rules before
    # spending a new university network budget.
    for version in db.versions.find({"category": category, "state": "pending"}).sort("createdAt", -1).limit(20):
        if version.get("extractionRevision") != EXTRACTION_REVISION:
            path = blob_path(version["digest"], version["format"])
            if path.is_file():
                version.update(process(db, version, path.read_bytes()))
        inspected.append({"title": version["title"], "url": version["url"], "reason": "Previously downloaded source inspected"})
        save_official_version(db, job, version, intent, log)
    refreshed = answer(db, question, context, intent, allow_undated=True)
    if refreshed["status"] in {"answered", "clarify"} and refreshed["citations"] and not intent["latest"]:
        return refreshed
    # Latest requests refresh official coverage when older than the saved
    # lookup window. Other requests can use relevant saved evidence directly.
    if not recent_lookup(db, intent):
        log("crawl", "Searching SPPU sources for " + category)
        client = PublicClient(seconds=110, requests_limit=70)
        sources = list(db.sources.find({"enabled": True, **({"category": category} if category != "document" else {})}).limit(12))
        if category == "document":
            sources.sort(key=lambda source: source["url"] != "https://www.unipune.ac.in/")
        if category == "timetable":
            sources.sort(key=lambda source: source["url"] != "https://exam.unipune.ac.in/")
        counts = {"pages": 0, "documents": 0, "errors": 0, "saved": 0}
        save_limit = 1 if intent["constraints"].get("pattern") and not intent["latest"] else 2
        for source in sources[:3]:
            if counts["saved"] >= save_limit or client.exhausted():
                break
            try:
                limits = {key: min(source["limits"][key], value) for key, value in
                          {"maxPages": 10, "maxDocuments": 8, "depth": 3}.items()}
                def ingest(link, response, digest, kind):
                    crawl_source = {**source, "category": category}
                    version = consume(db, crawl_source, {**job, "goal": intent["rewritten"] if category == "document" else ""},
                                      link, response, digest, kind, log)
                    if version and (not version.get("restricted") or category == "punishment"):
                        inspected.append({"title": version["title"], "url": version["url"],
                                          "reason": "; ".join(version.get("reasons", [])) or "Downloaded and extracted"})
                    counts["saved"] += int(save_official_version(db, job, version, intent, log))
                    return counts["saved"] >= save_limit
                run = crawl({**source, "category": category}, limits, intent["rewritten"], log, ingest,
                            lambda links, goal: rank_links(links, goal, report=log), client=client)
                for key in ("pages", "documents", "errors"):
                    counts[key] += run[key]
            except Exception as error:
                counts["errors"] += 1
                log("crawl_error", type(error).__name__, source["url"])
        db.jobs.update_one({"_id": job["_id"]}, {"$set": {"counts": counts}})
        db.discovery.update_one({"_id": lookup_key(intent)}, {"$set": {
            "expiresAt": now() + timedelta(hours=6) if counts["saved"] else now() + timedelta(minutes=10)
        }}, upsert=True)
    log("answer", "Retrieving and checking official evidence")
    for vid, card in active_cards(db, intent).items():
        inspected.append({"title": card["title"], "url": card["url"], "reason": "Saved source inspected"})
    response = answer(db, question, context, intent, allow_undated=True)
    if response["status"] == "unverified" and cached and cached["status"] == "answered":
        return cached
    return response

def automatic_answer(db, job, log):
    inspected = []
    methods = []
    def report(stage, message, url=None):
        if stage in {"gemini", "gemini_fallback", "browser", "crawl", "cache"}:
            methods.append((stage, message))
        if stage == "page" and url:
            inspected.append({"title": "Official SPPU listing", "url": url, "reason": "Listing page inspected"})
        log(stage, message, url)
    try:
        response = search_answer(db, job, report, inspected)
    except InterruptedError:
        raise
    except Exception as error:
        report("search_error", "Search processing failed (" + type(error).__name__ + ").")
        response = result(interpret(job["question"]), "CampusIQ couldn't finish processing the sources for this question.", "unavailable")
    seen = set()
    public_sources = []
    for source in inspected:
        if source["url"] not in seen:
            seen.add(source["url"])
            public_sources.append(source)
    response["inspectedSources"] = public_sources[:12]
    fallback = [message for stage, message in methods if stage == "gemini_fallback"]
    assisted = any(stage == "gemini" for stage, _ in methods)
    crawled = any(stage == "crawl" for stage, _ in methods)
    mode = ("Gemini-assisted crawling with rule-based fallback" if assisted and fallback else
            "Rule-based crawling" if crawled and fallback else
            "Gemini-assisted crawling" if crawled and assisted else
            "Rule-based crawling" if crawled else "Saved document retrieval")
    if any(stage == "browser" for stage, _ in methods):
        mode += " with Playwright SharePoint expansion"
    response["search"] = {"method": mode, "fallbacks": list(dict.fromkeys(fallback)),
                          "workerVersion": WORKER_VERSION}
    if response["status"] in {"unverified", "unavailable"}:
        response["answer"] += ("\n\nThe sources I inspected are listed below." if public_sources else
                               "\n\nI did not find a readable matching source within this search.")
    response["answer"] += "\n\nSearch used " + mode.lower() + "."
    if fallback:
        response["answer"] += "\n" + " ".join(dict.fromkeys(fallback))
    if response.get("generationFailure"):
        response["answer"] += "\nAnswer generation failed (" + response["generationFailure"] + ")."
    return response

def lookup_key(intent):
    scope = repr((EXTRACTION_REVISION, sorted(intent["constraints"].items()), intent["identifiers"],
                  intent["dates"], intent["revised"], sorted(set(words(intent["original"])))))
    return sha256(scope.encode()).hexdigest()

def recent_lookup(db, intent):
    return db.discovery.find_one({"_id": lookup_key(intent), "expiresAt": {"$gt": now()}}, {"_id": 1})

def record_turn(db, job, response=None):
    common = {"chatId": job["chatId"], "owner": job["owner"]}
    if db.chats.find_one({"_id": job["chatId"], "owner": job["owner"], "deletedAt": {"$exists": True}}, {"_id": 1}):
        db.messages.delete_many(common)
        return
    if response is None:
        db.messages.update_one({"_id": job["questionId"]}, {"$setOnInsert": {
            **common, "role": "student", "text": job["question"], "createdAt": job["createdAt"]
        }}, upsert=True)
        if db.chats.find_one({"_id": job["chatId"], "owner": job["owner"], "deletedAt": {"$exists": True}}, {"_id": 1}):
            db.messages.delete_many(common)
        return
    db.messages.update_one({"_id": job["_id"]}, {"$setOnInsert": {
        **common, "role": "assistant", "text": response["answer"], "status": response["status"],
        "citations": response["citations"], "intent": response["intent"],
        "inReplyTo": job["questionId"], "createdAt": now(),
        "search": response.get("search"), "inspectedSources": response.get("inspectedSources", [])
    }}, upsert=True)
    if db.chats.find_one({"_id": job["chatId"], "owner": job["owner"], "deletedAt": {"$exists": True}}, {"_id": 1}):
        db.messages.delete_many(common)

def process_job(db, job):
    job_id = job["_id"]
    def log(stage, message, url=None):
        if job["kind"] == "answer" and (db.jobs.find_one({"_id": job_id, "cancelRequested": True}, {"_id": 1}) or
                db.chats.find_one({"_id": job["chatId"], "owner": job["owner"], "deletedAt": {"$exists": True}}, {"_id": 1})):
            raise InterruptedError("The conversation was deleted.")
        update = {"$push": {"events": {"$each": [
            {"stage": stage, "message": message, "url": url, "at": now()}
        ], "$slice": -400}}}
        if stage in {"cache", "rewrite", "crawl", "answer"}:
            update["$set"] = {"stage": stage}
        db.jobs.update_one({"_id": job_id}, update)
    try:
        counts = None
        if job["kind"] == "answer":
            record_turn(db, job)
            if not db.messages.find_one({"_id": job_id}, {"_id": 1}):
                record_turn(db, job, automatic_answer(db, job, log))
        elif job["kind"] == "crawl":
            source = db.sources.find_one({"_id": job["sourceId"], "enabled": True})
            if not source:
                raise ValueError("Source disabled or missing")
            counts = crawl(source, job["limits"], job.get("goal", ""), log,
                           lambda *args: consume(db, source, job, *args, log), rank_links)
        else:
            raise ValueError("This legacy job action is no longer supported. Documents are indexed automatically.")
        finished = {"status": "done", "finishedAt": now()}
        if counts is not None:
            finished["counts"] = counts
        db.jobs.update_one({"_id": job_id}, {"$set": finished, "$unset": {"lock": "", "question": "", "context": ""}})
    except Exception as error:
        reason = str(error)[:250] if isinstance(error, (ValueError, OSError)) else type(error).__name__
        if isinstance(getattr(error, "status_code", None), int):
            reason += f" (upstream HTTP {error.status_code})"
        if job.get("versionId") and not db.documents.find_one({"activeVersion": job["versionId"]}):
            cleanup_version(db, job["versionId"], log)
        if job["kind"] == "answer":
            record_turn(db, job, result(interpret(job["question"]), "CampusIQ couldn't complete this search. Please try again.", "unavailable"))
        db.jobs.update_one({"_id": job_id}, {"$push": {"events": {"stage": "failure", "message": reason, "at": now()}}})
        db.jobs.update_one({"_id": job_id}, {"$set": {"status": "failed", "finishedAt": now(), "error": reason},
                                            "$unset": {"lock": "", "question": "", "context": ""}})

def main():
    db = database()
    owner = uuid4().hex
    db.command("ping")
    while not claim_worker(db, owner):
        sleep(5)
    done = Event()
    Thread(target=heartbeat, args=(db, owner, done), daemon=True).start()
    try:
        db.jobs.update_many({"status": "running"}, {"$set": {"status": "queued"}})
        last_schedule = now() - timedelta(minutes=1)
        while True:
            if now() - last_schedule >= timedelta(seconds=30):
                for version in db.versions.find({"needsVectorCleanup": True}, {"_id": 1}).limit(3):
                    vid = version["_id"]
                    if not db.documents.find_one({"activeVersion": vid}):
                        cleanup_version(db, vid, lambda _stage, message, _url: print(message, flush=True))
                last_schedule = now()
            job = db.jobs.find_one_and_update({"status": "queued"}, {"$set": {"status": "running", "startedAt": now()}},
                                               sort=[("createdAt", 1)], return_document=ReturnDocument.AFTER)
            if job:
                process_job(db, job)
            else:
                sleep(1)
    finally:
        done.set()
        db.runtime.delete_one({"_id": LEASE, "owner": owner})

if __name__ == "__main__":
    main()

