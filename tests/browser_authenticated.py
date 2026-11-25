"""Authenticated browser workflows use synthetic Firebase responses and an isolated real API/database."""
import base64
import json
import time
from playwright.sync_api import expect, sync_playwright

base = "http://localhost:5187"
def encoded(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(channel="chrome")
    for role in ("student", "admin"):
        context = browser.new_context()
        uid = "fixture-" + role
        email = role + "@example.test"
        def firebase(route):
            current = int(time.time())
            token = encoded({"alg": "RS256"}) + "." + encoded({
                "sub": uid, "user_id": uid, "email": email, "iat": current,
                "exp": current + 3600, "auth_time": current,
                "firebase": {"sign_in_provider": "password"},
            }) + ".fixture"
            if "accounts:lookup" in route.request.url:
                payload = {"users": [{"localId": uid, "email": email, "emailVerified": True}]}
            else:
                payload = {"localId": uid, "email": email, "idToken": token, "refreshToken": "fixture", "expiresIn": "3600"}
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))
        context.route("https://identitytoolkit.googleapis.com/**", firebase)
        page = context.new_page()
        page.goto(base + "/login")
        page.get_by_label("Email", exact=True).fill(email)
        page.get_by_label("Password", exact=True).fill("synthetic-password")
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.wait_for_url("**/" + role, timeout=20000)
        if role == "student":
            page.goto(base + "/student/chat")
            page.get_by_label("Question about SPPU").fill("MCA timetable?")
            page.get_by_role("button", name="Send question", exact=True).click()
            delete = page.get_by_role("button", name="Delete chat MCA timetable?")
            expect(delete).to_be_visible()
            page.on("dialog", lambda dialog: dialog.accept())
            delete.click()
            page.wait_for_url("**/student/chat")
            expect(page.get_by_role("button", name="Delete chat MCA timetable?")).to_have_count(0)
            page.reload()
            expect(page.get_by_role("button", name="Delete chat MCA timetable?")).to_have_count(0)
            print("Student can delete a chat with a queued search, and it stays deleted after reload.")
        else:
            for path in ("sources", "jobs", "review", "publications"):
                page.goto(base + "/admin/" + path)
                expect(page.get_by_role("main")).to_be_visible()
                expect(page.get_by_role("button", name="Approve and index")).to_have_count(0)
                expect(page.get_by_role("button", name="Reject", exact=True)).to_have_count(0)
                expect(page.get_by_role("button", name="Save source", exact=True)).to_have_count(0)
                expect(page.get_by_role("button", name="Queue crawl", exact=True)).to_have_count(0)
            print("Admin can inspect screens and has no document decision or crawl controls.")
        context.close()
    browser.close()
