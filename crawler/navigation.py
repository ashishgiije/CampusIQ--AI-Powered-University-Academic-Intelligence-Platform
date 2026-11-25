"""Bounded SPPU navigation, based on v0.6 listing extraction and group expansion."""
from dataclasses import dataclass
from hashlib import sha256
import heapq
import ipaddress
import os
import re
import socket
import time
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
import requests
import urllib3

from crawler.intent import DATE, PATTERNS, fields, match, parse_date

UA = "CampusIQ/1.0"
PDF_LIMIT = 18 * 1024 * 1024
HTML_LIMIT = 2 * 1024 * 1024
REDIRECTS = {301, 302, 303, 307, 308}
PAGINATION = {"page", "pageno", "pageindex", "paged", "pagefirstrow"}
AUTH_QUERY = {"access_token", "auth_token", "id_token", "refresh_token", "client_secret", "password", "api_key"}
ASSET = re.compile(r"\.(?:gif|png|jpe?g|svg|ico|zip|docx?|xlsx?|mp[34]|woff2?|css|js)$", re.I)
DETAIL = re.compile(r"detail|viewnotice|viewcircular|noticeid|announcementid|download", re.I)
NAV = {
    "punishment": r"unfair\s*means|copy\s*case|punish",
    "timetable": r"time\s*table|schedul",
    "circular": r"circular|ordinance",
    "syllabus": r"syllab|curricul",
    "calendar": r"calend[ae]r|academic\s+schedule",
    "announcement": r"announcement|notice|recent\s+updates|news",
    "document": r"document|notice|fee|hostel|admission|scholarship|eligibility|ordinance|certificate|download"
}

def canonical(href, base=""):
    if not href or href.startswith(("#", "javascript:", "mailto:", "data:", "tel:")):
        return ""
    try:
        p = urlsplit(urljoin(base, href.strip()))
        if p.scheme not in {"https", "http"} or not p.hostname or p.port or p.username or p.password:
            return ""
        arguments = parse_qsl(p.query, keep_blank_values=True, max_num_fields=100)
        if any(key.lower() in AUTH_QUERY for key, _ in arguments):
            return ""
        query = [(key, val) for key, val in arguments
                 if not key.lower().startswith("utm_") and key.lower() not in {"fbclid", "gclid"}]
        return urlunsplit((p.scheme, p.hostname.lower(), quote(p.path or "/", safe="/%():!$&'*,;=~+@"), urlencode(sorted(query)), ""))
    except (ValueError, UnicodeError):
        return ""

def allowed_host(host):
    tenant = os.getenv("SPPU_SHAREPOINT_HOST", "").lower()
    return host == "unipune.ac.in" or host.endswith(".unipune.ac.in") or (
        host == tenant and host.endswith(".sharepoint.com"))

def public_ip(host):
    if not allowed_host(host):
        raise ValueError("Host outside the official SPPU allowlist")
    records = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    ips = sorted({r[4][0] for r in records}, key=lambda value: ":" in value)
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError("Host does not resolve exclusively to public IP addresses")
    return ips[0]

@dataclass
class Response:
    url: str
    status: int
    content_type: str
    data: bytes

class PublicClient:
    def __init__(self, seconds=720, requests_limit=180):
        self.delay = max(1.0, float(os.getenv("CRAWL_DELAY_SECONDS", "1.25")))
        self.last = {}
        self.rules = {}
        self.total = 0
        self.deadline = time.monotonic() + seconds
        self.requests_limit = requests_limit

    def exhausted(self):
        return self.total >= self.requests_limit or time.monotonic() > self.deadline

    def _request(self, url, cap):
        if self.exhausted():
            raise ValueError("Crawl network budget exhausted")
        self.total += 1
        prepared = requests.Request("GET", url).prepare()
        p = urlsplit(prepared.url)
        ip = public_ip(p.hostname)
        rule = self.rules.get(f"{p.scheme}://{p.hostname}")
        delay = max(self.delay, rule.crawl_delay(UA) or rule.crawl_delay("*") or 0) if rule else self.delay
        frequency = (rule.request_rate(UA) or rule.request_rate("*")) if rule else None
        if frequency and frequency.requests > 0:
            delay = max(delay, frequency.seconds / frequency.requests)
        remaining = max(0, self.last.get(p.hostname, 0) + delay - time.monotonic())
        if remaining > 30:
            raise ValueError("Site crawl delay exceeds the current job budget")
        time.sleep(remaining)
        self.last[p.hostname] = time.monotonic()
        timeout = urllib3.Timeout(connect=8, read=10)
        pool = (urllib3.HTTPSConnectionPool(ip, assert_hostname=p.hostname, server_hostname=p.hostname,
                cert_reqs="CERT_REQUIRED", ca_certs=requests.certs.where(), timeout=timeout)
                if p.scheme == "https" else urllib3.HTTPConnectionPool(ip, timeout=timeout))
        raw = None
        try:
            raw = pool.urlopen("GET", prepared.path_url, headers={"Host": p.hostname, "User-Agent": UA,
                "Accept-Encoding": "identity"}, redirect=False, retries=False, preload_content=False)
            if raw.status in REDIRECTS:
                return raw.status, raw.headers.get("Location", ""), b""
            body = bytearray()
            for block in raw.stream(65536, decode_content=True):
                if time.monotonic() > self.deadline or len(body) + len(block) > cap:
                    raise ValueError("Response exceeds download limits")
                body.extend(block)
            return raw.status, raw.headers.get("Content-Type", ""), bytes(body)
        finally:
            if raw is not None:
                raw.close()
            pool.close()

    def permits(self, url):
        p = urlsplit(url)
        origin = f"{p.scheme}://{p.hostname}"
        if origin not in self.rules:
            rule = RobotFileParser()
            try:
                robots_url = origin + "/robots.txt"
                for _ in range(5):
                    status, location, data = self._request(robots_url, 250_000)
                    if status not in REDIRECTS:
                        break
                    robots_url = canonical(location, robots_url)
                    if not robots_url or not allowed_host(urlsplit(robots_url).hostname):
                        raise ValueError("Robots redirect outside the official domain")
                else:
                    raise ValueError("Too many robots redirects")
                if status in {404, 410}:
                    rule.allow_all = True
                elif status == 200:
                    rule.parse(data.decode("utf-8", errors="replace").splitlines())
                else:
                    rule.disallow_all = True
            except (ValueError, OSError, urllib3.exceptions.HTTPError):
                rule.disallow_all = True
            self.rules[origin] = rule
        return self.rules[origin].can_fetch(UA, url)

    def get(self, url, cap=PDF_LIMIT):
        for _ in range(5):
            url = canonical(url)
            if not url or not allowed_host(urlsplit(url).hostname) or not self.permits(url):
                raise ValueError("URL refused by source or robots policy")
            for attempt in range(2):
                try:
                    status, header, data = self._request(url, cap)
                    if status not in {500, 502, 503, 504} or attempt:
                        break
                except (OSError, urllib3.exceptions.HTTPError):
                    if attempt:
                        raise
            if status not in REDIRECTS:
                if not 200 <= status < 300:
                    raise ValueError(f"Source returned HTTP {status}")
                return Response(url, status, header, data)
            url = canonical(header, url)
        raise ValueError("Too many redirects")

def is_pdf(url):
    p = urlsplit(url)
    return p.path.lower().endswith(".pdf") or any(value.lower().endswith(".pdf") for _, value in parse_qsl(p.query))

def linked_timetable_library(portal, listing, document=None):
    root, page = urlsplit(portal), urlsplit(listing)
    if (root.scheme, root.hostname, root.path.rstrip("/").casefold()) != ("https", "exam.unipune.ac.in", ""):
        return False
    if page.hostname != "collegecirculars.unipune.ac.in" or page.scheme not in {"https", "http"}:
        return False
    library = unquote(page.path).casefold()
    if not re.fullmatch(r"/sites/examdocs/[^/]*time\s*tables?[^/]*/forms/allitems\.aspx", library):
        return False
    if document is None:
        return True
    target = urlsplit(document)
    path = unquote(target.path).casefold()
    return (target.hostname == page.hostname and target.scheme == page.scheme and is_pdf(document)
            and path.rsplit("/", 1)[0] == library.removesuffix("/forms/allitems.aspx"))

def links_from(markup, page_url):
    soup = BeautifulSoup(markup, "html.parser")
    links = []
    for anchor in soup.select("a[href], iframe[src]"):
        url = canonical(anchor.get("href") or anchor.get("src"), page_url)
        if not url or not allowed_host(urlsplit(url).hostname) or ASSET.search(urlsplit(url).path):
            continue
        label = anchor.get_text(" ", strip=True) or anchor.get("title", "")
        row = anchor.find_parent("tr")
        context = row.get_text(" ", strip=True)[:450] if row else ""
        if row and label.lower() in {"view", "download", "pdf", "open", ""}:
            cells = (cell.get_text(" ", strip=True) for cell in row.find_all(["td", "th"], recursive=False))
            label = max(cells, key=len, default=label)
        base, target = urlsplit(page_url), urlsplit(url)
        before = {k: v for k, v in parse_qsl(base.query) if k.lower() not in PAGINATION}
        after = {k: v for k, v in parse_qsl(target.query) if k.lower() not in PAGINATION}
        pager = (base.hostname, base.path, before) == (target.hostname, target.path, after) and (
            any(k.lower() in PAGINATION for k, _ in parse_qsl(target.query)) or anchor.get("rel") == ["next"])
        links.append({"url": url, "title": (label or target.path.rsplit("/", 1)[-1])[:280],
                      "context": context, "listing": page_url, "pager": pager})
    return links

def expand_sharepoint(client, markup, url, log, scope=None):
    from playwright.sync_api import sync_playwright
    # All browser GETs are fulfilled through pinned public fetches. Chromium's
    # direct network route is disabled, including socket/worker side channels.
    pool = {url: Response(url, 200, "text/html; charset=utf-8", markup.encode("utf-8"))}
    with sync_playwright() as playwright:
        args = [
            "--proxy-server=http://127.0.0.1:1", "--proxy-bypass-list=<-loopback>",
            "--disable-background-networking", "--force-webrtc-ip-handling-policy=disable_non_proxied_udp"
        ]
        channel = os.getenv("PLAYWRIGHT_CHROMIUM_CHANNEL") or (
            "chrome" if os.name == "nt" and not os.path.isfile(playwright.chromium.executable_path) else None)
        browser = playwright.chromium.launch(headless=True, channel=channel, args=args)
        try:
            context = browser.new_context(user_agent=UA, accept_downloads=False, service_workers="block")
            def handle(route):
                req = route.request
                try:
                    if req.method != "GET" or req.resource_type not in {"document", "script", "xhr", "fetch", "stylesheet"}:
                        route.abort()
                        return
                    target = canonical(req.url)
                    response = pool.get(target) or client.get(target, HTML_LIMIT)
                    if response.url != target:
                        route.fulfill(status=302, headers={"location": response.url})
                    else:
                        route.fulfill(status=200, content_type=response.content_type, body=response.data)
                except Exception:
                    route.abort()
            context.route("**/*", handle)
            context.route_web_socket("**/*", lambda websocket: websocket.close())
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            clicked = set()
            match_limit = 1 if scope and scope.get("pattern") else 2
            for _ in range(16):
                if client.exhausted():
                    break
                controls = page.locator("a[onclick*='ExpCollGroup'], [aria-expanded='false']")
                for item in controls.all()[:80]:
                    try:
                        signature = (item.get_attribute("onclick", timeout=800), item.get_attribute("id", timeout=800),
                                     item.text_content(timeout=800))
                        visible = item.is_visible()
                    except Exception:
                        continue
                    if signature not in clicked and visible:
                        clicked.add(signature)
                        try:
                            item.click(timeout=1800)
                            page.wait_for_timeout(650)
                        except Exception:
                            pass
                        break
                else:
                    break
                if scope:
                    visible_links = links_from(page.content(), page.url)
                    matches = {item["url"] for item in visible_links if is_pdf(item["url"]) and
                               label_matches_scope(item["title"], scope)}
                    if len(matches) >= match_limit:
                        break
            log("browser", f"Inspected {len(clicked)} SharePoint group controls", url)
            return links_from(page.content(), page.url)
        finally:
            browser.close()

def label_matches_scope(label, scope):
    observed = fields(label.replace("_", " "))
    return all(observed.get(key) == value for key, value in scope.items())

def crawl(source, limits, goal, log, consume, rank_links=None, client=None):
    client = client or PublicClient()
    category = source["category"]
    root = canonical(source["url"])
    queue = [(0, 0, 0, 0, {"url": root, "title": source["name"], "context": "", "listing": root})]
    visited, content_seen, queued = set(), set(), {root}
    pages = documents = serial = failures = 0
    page_cap_hit = False
    noise = {"the", "for", "give", "and", "tell", "when", "are", "latest", "starting", "sppu",
             "examination", "exam", "exams", "university", "document", "table", "time", "timetable", "schedule"}
    terms = set(re.findall(r"[^\W_]+", goal.casefold())) - noise
    terms = {word for word in terms if len(word) >= 3 or word.isdigit()}
    extracted_scope = fields(goal)
    scope = {key: extracted_scope[key] for key in ("programme", "studyYear", "pattern") if key in extracted_scope}
    while queue and documents < limits["maxDocuments"] and not client.exhausted():
        _, _, _, depth, link = heapq.heappop(queue)
        url = link["url"]
        if url in visited:
            continue
        if pages >= limits["maxPages"] and not is_pdf(url):
            page_cap_hit = True
            continue
        visited.add(url)
        try:
            result = client.get(url)
            digest = sha256(result.data).hexdigest()
            if digest in content_seen or (result.url != url and result.url in visited):
                continue
            content_seen.add(digest)
            visited.add(result.url)
            if result.data.startswith(b"%PDF-") or is_pdf(result.url):
                documents += 1
                if consume(link, result, digest, "pdf") is True:
                    break
                continue
            if "html" not in result.content_type.lower() or len(result.data) > HTML_LIMIT:
                continue
            pages += 1
            markup = result.data.decode("utf-8", errors="replace")
            log("page", f"Inspected listing {pages}", result.url)
            found = links_from(markup, result.url)
            if "ExpCollGroup" in markup or "_layouts/" in markup and "sharepoint" in markup.lower():
                try:
                    found.extend(expand_sharepoint(client, markup, result.url, log, scope or None))
                except Exception as error:
                    log("browser_error", type(error).__name__, result.url)
            heading = BeautifulSoup(markup, "html.parser").select_one("article h1,main h1,h1,title")
            if depth and (DETAIL.search(result.url) or "<article" in markup.lower()) and heading and match(PATTERNS[category], heading.get_text(" ", strip=True)):
                documents += 1
                if consume(link, result, digest, "html") is True:
                    break
            # The reference ranks all candidate links with Gemini at shallow
            # depths, including direct PDFs and links in ordinary HTML tables.
            ranked_links = sorted(found, key=lambda item: (
                bool(match(NAV[category], item["title"])),
                len(terms & set(re.findall(r"[^\W_]+", item["title"].casefold())))), reverse=True)
            preferred = rank_links(ranked_links[:35], goal) if rank_links and goal and depth <= 2 else set()
            for item in found:
                dest = item["url"]
                label = item["title"] + " " + item["context"] + " " + unquote(urlsplit(dest).path).rsplit("/", 1)[-1]
                topical = bool(match(NAV[category], label))
                normalized = re.sub(r"\bm\.?c\.?a\b", "mca", label.casefold())
                overlap = len(terms & set(re.findall(r"[^\W_]+", normalized)))
                pdf = is_pdf(dest)
                pager = item["pager"]
                if dest in queued or len(queued) >= 700 or (not pdf and not pager and depth >= limits["depth"]):
                    continue
                if not (pager or topical or dest in preferred or overlap or
                        pdf and depth > 0 and category != "punishment"):
                    continue
                if category == "punishment" and pdf and not match(r"punish|minutes|decision|unfair\s*means", label):
                    continue
                if category == "timetable" and linked_timetable_library(result.url, dest):
                    item["legacyPortal"] = result.url
                if link.get("legacyPortal") and linked_timetable_library(link["legacyPortal"], result.url, dest):
                    item["legacyPortal"] = link["legacyPortal"]
                serial += 1
                queued.add(dest)
                score = (35 if topical else 0) + (35 if pdf else 0) + (12 if pager else 0) + min(48, 14 * overlap)
                if dest in preferred:
                    score += 40
                if pdf and scope and label_matches_scope(item["title"], scope):
                    score += 90
                if category == "timetable" and linked_timetable_library(result.url, dest):
                    score += 90
                date_rank = max((int(day.replace("-", "")) for value in re.findall(DATE, label, re.I)
                                 if (day := parse_date(value))), default=0)
                heapq.heappush(queue, (-score, -date_rank, serial, depth if pager else depth + 1, item))
        except Exception as error:
            failures += 1
            log("error", str(error)[:200], url)
    if not pages and not documents:
        raise ValueError("No source pages or documents could be inspected.")
    return {"pages": pages, "documents": documents, "errors": failures, "bounded": bool(queue) or page_cap_hit}

