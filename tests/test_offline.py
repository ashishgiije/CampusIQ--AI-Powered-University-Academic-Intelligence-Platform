import json
from pathlib import Path
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pymupdf

from crawler.extraction import extract_html, extract_pdf
from crawler.intent import branch_section, exact, fields, identities, interpret, metadata_matches, validate
from crawler.navigation import PublicClient, canonical, crawl, expand_sharepoint, linked_timetable_library, links_from, public_ip, Response

ROOT = "https://exam.unipune.ac.in/Pages/UnfairMeans.html"
TABLE = """
<h1>SPPU Unfair Means</h1>
<table><tr><td>1</td><td>Minutes Punishment List 2026</td>
<td><a href='/Docs/list.pdf?utm_source=duplicate'>View</a></td></tr></table>
<a href='?page=2'>2</a><a href='https://outside.test/report.pdf'>Outside</a>
<a href='/Pages/Admission.html'>Admissions</a>
"""
DOC = "Minutes of unfair means examination punishment list. Published on 10.10.2026."

class CrawlerTests(unittest.TestCase):
    def test_robots_redirects_follow_official_hosts_and_block_external_hosts(self):
        client = PublicClient()
        with patch.object(client, "_request", side_effect=[
            (301, "https://exam.unipune.ac.in/robots.txt", b""),
            (200, "text/plain", b"User-agent: *\nDisallow: /private")
        ]) as request:
            self.assertTrue(client.permits("http://exam.unipune.ac.in/Pages/UnfairMeans.html"))
            self.assertEqual(request.call_count, 2)
        denied = PublicClient()
        with patch.object(denied, "_request", return_value=(302, "http://127.0.0.1/private", b"")) as request:
            self.assertFalse(denied.permits("http://exam.unipune.ac.in/"))
            self.assertEqual(request.call_count, 1)

    def test_general_document_search_checks_the_requested_subject_in_native_text(self):
        page = {"number": 1, "ocr": False, "text": "Savitribai Phule Pune University\nHostel fees and payment rules for students."}
        self.assertTrue(validate("Hostel fees", [page], "", "document", "hostel fees")["relevant"])
        self.assertFalse(validate("Timetable", [{"number": 1, "ocr": False, "text": "SPPU engineering examination schedule."}],
                                  "", "document", "hostel fees")["relevant"])

    def test_se_winter_session_and_electrical_typo_preserve_scope(self):
        header = "PROGRAMME OF SECOND YEAR ENGINEERING INSEM EXAM (2019 PATTERN)\nWinter Session-2026 (OCT/NOV-2026)"
        self.assertEqual(fields(header)["session"], "winter")
        query = interpret("can you provide me SE insem winter elecrtrical eng timetable")
        self.assertEqual(query["constraints"]["branch"], "electrical")
        self.assertEqual(query["constraints"]["studyYear"], "2")
        self.assertIn("electrical", query["rewritten"])
        self.assertIn("elecrtrical", query["original"])
        self.assertTrue(metadata_matches({"programme": "engineering", "studyYear": "2", "category": "timetable",
                                         "session": "winter", "examType": "insem",
                                         "branches": ["civil", "electrical"]}, query))
        self.assertIn("session", interpret("winter and summer timetable")["ambiguous"])
        self.assertFalse(interpret(header)["ambiguous"])

    def test_branch_sections_exclude_other_engineering_schedules(self):
        page = ("CIVIL ENGINEERING\nThursday 03-09-2026 Civil paper\n"
                "ELECTRICAL ENGINEERING\nSEMESTER - III\nThursday Power Generation 04.00 PM03-09-2026\n"
                "COMPUTER ENGINEERING\nThursday 03-09-2026 Computing")
        section = branch_section(page, "electrical")
        self.assertIn("Power Generation", section)
        self.assertIn("PM 03-09-2026", section)
        self.assertNotIn("Civil paper", section)
        self.assertNotIn("Computing", section)

    def test_legacy_timetable_origin_requires_the_official_https_portal_and_same_library(self):
        portal = "https://exam.unipune.ac.in/"
        folder = "http://collegecirculars.unipune.ac.in/sites/examdocs/Time%20Tables%20Demo/"
        listing = folder + "Forms/AllItems.aspx"
        self.assertTrue(linked_timetable_library(portal, listing, folder + "mca.pdf"))
        self.assertFalse(linked_timetable_library(portal.replace("https", "http"), listing, folder + "mca.pdf"))
        self.assertFalse(linked_timetable_library(portal, listing, folder + "different/mca.pdf"))
        self.assertFalse(linked_timetable_library(portal, listing, "http://outside.test/mca.pdf"))

    def test_timetable_programme_heading_and_generic_exam_instructions(self):
        text = ("SAVITRIBAI PHULE PUNE UNIVERSITY\nEXAMINATION CIRCULAR NO. 775 OF 2026\n"
                "PROGRAMME OF SECOND YEAR MCA(ENGG) (2020 Course)\nSESSION: WINTER SESSION EXAMINATION 2026\n"
                "(UNDER FACULTY OF SCIENCE AND TECHNOLOGY : B)ENGINEERING)\n"
                "Bring your seat number, and avoid material that can be treated as a malpractice.\nOct/Nov/Dec-2026\n"
                "Monday 23-Nov-2026 Example paper")
        result = validate("MCA timetable", [{"text": text, "ocr": False}], "", "timetable", "MCA second year 2020 pattern")
        self.assertTrue(result["relevant"])
        self.assertFalse(result["restricted"])
        self.assertEqual(result["metadata"]["year"], "2026")
        self.assertEqual(result["metadata"]["session"], "winter")
        personal = validate("MCA timetable", [{"text": text + "\nSeat Number SYNTH1234", "ocr": False}], "", "timetable")
        self.assertTrue(personal["restricted"])

    def test_canonical_and_table_context(self):
        links = links_from(TABLE, ROOT)
        self.assertEqual(links[0]["title"], "Minutes Punishment List 2026")
        self.assertEqual(links[0]["url"], "https://exam.unipune.ac.in/Docs/list.pdf")
        self.assertIn("Minutes Punishment List", links[0]["context"])
        self.assertTrue(links[1]["pager"])
        self.assertEqual(len(links), 3)
        self.assertEqual(canonical("http://user:pass@exam.unipune.ac.in/a"), "")
        self.assertEqual(canonical("https://exam.unipune.ac.in:444/a"), "")
        pages, _, _ = extract_html(TABLE)
        self.assertIn("1 | Minutes Punishment List 2026 | View", pages[0]["text"])

    def test_pinned_ip_and_host_guards(self):
        with patch("crawler.navigation.socket.getaddrinfo", return_value=[(0, 0, 0, "", ("127.0.0.1", 0))]):
            with self.assertRaises(ValueError):
                public_ip("exam.unipune.ac.in")
        client = PublicClient()
        with patch.object(client, "permits", return_value=True), patch.object(
                client, "_request", return_value=(302, "http://169.254.169.254/", b"")) as request:
            with self.assertRaises(ValueError):
                client.get(ROOT)
            self.assertEqual(request.call_count, 1)

    def test_unfair_means_crawl_avoids_off_topic_navigation(self):
        fetched, records = [], []
        def fetch(url):
            fetched.append(url)
            if url.endswith(".pdf"):
                return Response(url, 200, "application/pdf", b"%PDF- synthetic fixture")
            return Response(url, 200, "text/html", TABLE.encode())
        with patch("crawler.navigation.PublicClient.get", side_effect=fetch):
            summary = crawl({"name": "Unfair Means", "category": "punishment", "url": ROOT},
                            {"depth": 2, "maxPages": 1, "maxDocuments": 2}, "",
                            lambda *args: None, lambda *args: records.append(args))
        self.assertEqual(summary["documents"], 1)
        self.assertTrue(summary["bounded"])
        self.assertTrue(records[0][0]["url"].endswith("list.pdf"))
        self.assertFalse(any("Admission" in url for url in fetched))

    @unittest.skipUnless(os.getenv("CAMPUSIQ_BROWSER_TEST"), "Enable Chromium fixture test explicitly")
    def test_dynamic_sharepoint_group(self):
        markup = """<a href='#' onclick="ExpCollGroup()">Exam group</a>
        <script>function ExpCollGroup() {
        let a=document.createElement('a'); a.href='/Docs/list.pdf'; a.textContent='Punishment list'; document.body.append(a);
        }</script>"""
        links = expand_sharepoint(PublicClient(), markup, ROOT, lambda *args: None)
        self.assertIn("https://exam.unipune.ac.in/Docs/list.pdf", [link["url"] for link in links])

    @unittest.skipUnless(os.getenv("CAMPUSIQ_LIVE_SPPU"), "Enable live SPPU connectivity check explicitly")
    def test_live_sppu_listing(self):
        page = PublicClient().get(ROOT)
        links = links_from(page.data.decode("utf-8", errors="replace"), page.url)
        self.assertTrue(any("punishment" in item["title"].casefold() for item in links))

    @unittest.skipUnless(os.getenv("CAMPUSIQ_LIVE_SPPU"), "Enable live SPPU connectivity check explicitly")
    def test_live_sppu_bounded_pdf_crawl(self):
        processed = []
        def consume(link, response, digest, kind):
            pages, _, _ = extract_pdf(response.data, ocr_mode="off")
            processed.append((kind, bool(pages), len(digest), link["listing"]))
        crawl({"name": "Unfair Means", "category": "punishment", "url": ROOT},
              {"depth": 1, "maxPages": 2, "maxDocuments": 2}, "latest copy case punishment list",
              lambda *_: None, consume)
        self.assertTrue(any(kind == "pdf" and pages and length == 64 and source == ROOT
                            for kind, pages, length, source in processed))

    def test_pdf_native_and_ocr_fallback(self):
        with pymupdf.open() as doc:
            doc.new_page().insert_text((35, 60), DOC)
            doc.new_page()
            sample = doc.tobytes()
        with patch("crawler.extraction.ocr_page", return_value="Synthetic OCR page with unverified Case Number ABC1234.") as ocr:
            pages, warnings, readable = extract_pdf(sample)
        self.assertTrue(readable)
        self.assertFalse(pages[0]["ocr"])
        self.assertTrue(pages[1]["ocr"])
        self.assertIn("require visual verification", " ".join(warnings))
        ocr.assert_called_once()

    def test_relevance_and_identifiers(self):
        page = {"number": 1, "text": DOC + " Seat Number SPPU1234/03.", "ocr": False}
        good = validate("Punishment list", [page], "unfair means", "punishment", "copy case 2026")
        self.assertTrue(good["relevant"])
        self.assertTrue(good["restricted"])
        self.assertFalse(validate("Notice of Meeting of Copy Case", [page], "", "punishment")["relevant"])
        self.assertFalse(validate("Punishment list", [page], "", "punishment", "2025 copy case")["relevant"])
        self.assertFalse(validate("Punishment list", [{**page, "ocr": True}], "", "punishment",
                                  "case number SPPU1234/03")["relevant"])
        self.assertFalse(validate("Engineering timetable", [{"text": "Fees for 2026", "ocr": False}], "",
                                  "timetable")["relevant"])
        self.assertTrue(exact(page["text"], "SPPU1234/03"))
        self.assertFalse(exact(page["text"], "SPPU1234"))
        self.assertEqual(identities("Case No. | Seat Number | Note\nSYNTH-47 | SYNTH1234/03 | synthetic"),
                         [("case", "SYNTH-47"), ("seat", "SYNTH1234/03")])
        self.assertFalse(metadata_matches({"programme": "mca", "category": "timetable", "semester": "3"},
                                          interpret("MCA semester 2 timetable")))

    def test_synthetic_evaluation(self):
        cases = json.loads((Path(__file__).parent / "evaluation.json").read_text())
        for case in cases:
            with self.subTest(question=case["question"]):
                intent = interpret(case["question"])
                self.assertEqual(intent["latest"], case.get("latest", False))
                self.assertEqual(intent["constraints"], {k: v for k, v in case.items() if k not in {"question", "latest"}})
                self.assertIn(case["question"], intent["rewritten"])

if __name__ == "__main__":
    unittest.main()
