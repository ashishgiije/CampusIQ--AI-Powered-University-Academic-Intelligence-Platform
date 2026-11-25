"""Unauthenticated UI smoke tests through a running Vite or preview server."""
import os
from playwright.sync_api import sync_playwright, expect

base = os.getenv("CAMPUSIQ_WEB_TEST_URL", "http://localhost:5173")
with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    for dimensions in [{"width": 1440, "height": 900}, {"width": 390, "height": 844}]:
        page = browser.new_page(viewport=dimensions)
        page.goto(base)
        expect(page.get_by_role("heading", level=1)).to_contain_text("With a source.")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.get_by_role("link", name="Get started").click()
        expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
        page.get_by_role("link", name="Forgot password?").click()
        expect(page.get_by_role("heading", name="Reset password")).to_be_visible()
        page.goto(base + "/signup")
        expect(page.get_by_role("heading", name="Create an account")).to_be_visible()
        for private in ["/student/chat", "/admin/review"]:
            page.goto(base + private)
            expect(page.get_by_role("heading", name="Sign in")).to_be_visible()
        page.close()
    browser.close()
print("Passed public and protected-route UI smoke tests at desktop and mobile widths.")

