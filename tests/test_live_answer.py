"""Opt-in question, official crawl, Gemini, saved-vector and reuse smoke test."""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ai-service"))

from bson import ObjectId
from config import now
from pymongo import MongoClient
import rag
import worker


@unittest.skipUnless(os.getenv("CAMPUSIQ_LIVE_ANSWER"), "Enable the real Gemini/SPPU test explicitly")
class LiveAnswerTest(unittest.TestCase):
    def test_live_question_crawls_cites_and_reuses_saved_source(self):
        self.exercise(
            "Which academic year does SPPU's tentative schedule of examinations cover for 2026-2027?",
            "https://exam.unipune.ac.in/Pages/SchedulesTimetables.html", "https://")

    def test_live_mca_timetable_from_official_library(self):
        if not os.getenv("CAMPUSIQ_LIVE_MCA"):
            self.skipTest("Enable the real timetable library check explicitly")
        self.exercise(
            "When do the SPPU MCA second year 2025 pattern winter 2026 examinations start according to the timetable?",
            "https://exam.unipune.ac.in/", "http://collegecirculars.unipune.ac.in/")

    def exercise(self, question, source, citation_prefix):
        key = "campusiq_live_" + uuid4().hex
        client = MongoClient(os.getenv("MONGO_URI", "mongodb://127.0.0.1:27017"), serverSelectionTimeoutMS=5000)
        db = client[key]
        self.addCleanup(client.close)
        self.addCleanup(client.drop_database, key)
        self.addCleanup(rag.vectors().delete_collection, key)
        db.pages.create_index([("text", "text")], default_language="none")
        db.sources.insert_one({
            "name": "SPPU Exam Schedules", "category": "timetable", "enabled": True,
            "url": source, "limits": {"maxPages": 3, "maxDocuments": 5, "depth": 2},
        })

        def submit():
            job = {"kind": "answer", "status": "running", "createdAt": now(), "question": question,
                   "chatId": ObjectId(), "questionId": ObjectId(), "owner": "synthetic-live-test", "events": []}
            db.jobs.insert_one(job)
            worker.process_job(db, job)
            status = db.jobs.find_one({"_id": job["_id"]})
            reply = db.messages.find_one({"_id": job["_id"]})
            self.assertEqual(status["status"], "done", status.get("error"))
            self.assertEqual(reply["status"], "answered",
                             (reply["text"], [(e["stage"], e["message"]) for e in status["events"]]))
            self.assertTrue(reply["citations"], reply["text"])
            self.assertTrue(all(cite["url"].startswith(citation_prefix) and cite["page"] >= 1
                                for cite in reply["citations"]), reply["citations"])
            self.assertIn("2026", reply["text"])
            if question.startswith("When do"):
                self.assertRegex(reply["text"], r"\b(?:\d{1,2}[-./]\d{1,2}[-./](?:20)?26|\d{1,2}[ -]+(?:Nov(?:ember)?|Dec(?:ember)?)[ -]+2026)\b")
            return status

        with TemporaryDirectory() as path, patch("worker.store", return_value=Path(path)), patch("rag.COLLECTION", key):
            first = submit()
            self.assertGreater(first["counts"]["saved"], 0)
            self.assertTrue(any(event["stage"] == "rewrite" for event in first["events"]))
            second = submit()
            self.assertTrue(all(event["stage"] != "crawl" for event in second["events"]))
